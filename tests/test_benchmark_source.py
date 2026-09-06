"""Benchmark scores must be CURRENT, and must say when they are not.

The panel shipped a snapshot baked into the package. It looked authoritative and quietly aged —
a model listed there was months out of date while the UI presented it as fact. Same defect class
the model catalog already fixed for prices: serving old data offline is fine, serving it as
today's truth is the bug.

Licensing shapes the design: Artificial Analysis's free tier is "internal use only, no
redistribution". So the scores are fetched at RUNTIME with the USER'S OWN key and cached under
their home directory — never vendored into the repo, which would be redistribution.
"""

import json
import re
import time

import pytest

from interact import benchmark_source as bs
from interact.data import PackageData
from interact.criteria import Criteria, CriteriaError
from interact.benchmarks.upstream import GroundingLeaderboardJS, UpstreamSource, fetch_all
from interact.benchmarks.published import PublishedEntry, PublishedTable
import interact.benchmark_tables as benchmark_tables
import interact.live_sources as live_sources
from interact.models import Benchmark


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("ARTIFICIAL_ANALYSIS_API_KEY", raising=False)
    yield


_PAYLOAD = {
    "data": [
        {
            "name": "Claude Sonnet 5",
            "model_creator": {"name": "Anthropic"},
            "evaluations": {"artificial_analysis_intelligence_index": 61.2},
        },
        {
            "name": "GPT-5.4",
            "model_creator": {"name": "OpenAI"},
            "evaluations": {"artificial_analysis_intelligence_index": 55.0},
        },
        {"name": "No scores", "model_creator": {"name": "X"}, "evaluations": {}},
    ]
}


def test_scores_are_parsed_with_their_creator():
    scores = bs._from_artificial_analysis(_PAYLOAD)
    assert len(scores) == 2, "a model with no evaluations carries no score and is dropped"
    top = scores[0]
    assert top.name == "Claude Sonnet 5" and top.creator == "Anthropic"
    assert top.intelligence == pytest.approx(61.2)


def test_scores_come_back_ranked():
    scores = bs._from_artificial_analysis(_PAYLOAD)
    assert [s.name for s in scores] == ["Claude Sonnet 5", "GPT-5.4"]


def test_without_a_key_it_says_so_rather_than_pretending():
    board = bs.load_scores()
    assert board.source == "unavailable"
    assert board.is_live is False
    assert "ARTIFICIAL_ANALYSIS_API_KEY" in board.describe()


def test_a_fresh_cache_is_used_and_reported_live(monkeypatch):
    bs.cache_path().parent.mkdir(parents=True, exist_ok=True)
    bs.cache_path().write_text(json.dumps({
        "source": "artificial_analysis",
        "fetched_at": time.time(),
        "scores": [{"name": "Claude Sonnet 5", "creator": "Anthropic", "intelligence": 61.2}],
    }))
    board = bs.load_scores()
    assert board.is_live is True and board.scores[0].name == "Claude Sonnet 5"


def test_a_stale_cache_is_still_served_but_never_called_live(monkeypatch):
    # Offline with old data is useful; offline with old data presented as current is the defect.
    bs.cache_path().parent.mkdir(parents=True, exist_ok=True)
    bs.cache_path().write_text(json.dumps({
        "source": "artificial_analysis",
        "fetched_at": time.time() - (bs.TTL_SECONDS * 3),
        "scores": [{"name": "Old", "creator": "X", "intelligence": 1.0}],
    }))
    board = bs.load_scores()
    assert board.scores and board.is_live is False
    assert "ago" in board.describe()


def test_the_cache_lives_under_home_not_in_the_repo():
    # AA's free tier forbids redistribution, so scores must never be vendored into the package.
    path = str(bs.cache_path())
    assert "/dev/interact/src" not in path
    assert path.endswith("benchmark_scores.json")


def test_a_corrupt_cache_degrades_to_unavailable():
    bs.cache_path().parent.mkdir(parents=True, exist_ok=True)
    bs.cache_path().write_text("{ not json")
    assert bs.load_scores().source == "unavailable"


def test_artificial_analysis_visual_provenance_names_only_its_actual_metric() -> None:
    benchmarks = json.loads(PackageData.read(PackageData.BENCHMARKS) or "{}")["benchmarks"]
    artificial_analysis = [
        benchmark for benchmark in benchmarks
        if benchmark.get("source") == "Artificial Analysis public evaluation"
    ]
    assert {benchmark["id"] for benchmark in artificial_analysis} == {"mmmu_pro"}
    assert artificial_analysis[0]["name"] == "MMMU Pro"
    assert artificial_analysis[0]["url"] == "https://artificialanalysis.ai/evaluations/mmmu-pro"
    assert artificial_analysis[0]["methodology_url"] == (
        "https://artificialanalysis.ai/methodology/intelligence-benchmarking#mmmu-pro"
    )
    assert artificial_analysis[0]["score_range"] == [0.0, 1.0]
    assert artificial_analysis[0]["higher_is_better"] is True


def test_aa_api_limit_is_not_misstated_as_publication_absence() -> None:
    docs = " ".join((live_sources.__doc__ or "", benchmark_tables.__doc__ or ""))
    assert "AA does not publish" not in docs
    assert "AA publishes text and reasoning benchmarks only" not in docs
    assert re.search(
        r"current Artificial Analysis API adapter does not expose\s+per-benchmark MMMU Pro",
        docs,
    )
    benchmark = Benchmark.by_id("mmmu_pro")
    assert benchmark is not None
    assert benchmark.namespace == "aa"
    assert benchmark.variable == "aa.mmmu_pro"
    assert benchmark.source == "Artificial Analysis public evaluation"
    assert benchmark.source_auth == ""


def test_generated_benchmark_snapshot_preserves_typed_publication_fields() -> None:
    benchmarks = json.loads(PackageData.read(PackageData.BENCHMARKS) or "{}")["benchmarks"]
    screen = next(benchmark for benchmark in benchmarks if benchmark["id"] == "screenspot_pro")
    table = screen["published"]
    assert {"source_url", "retrieved", "freshness"} <= table.keys()
    assert {"model_id", "status", "normalized_score"} <= table["entries"][0].keys()


def test_generated_recommendation_requires_an_authorized_current_entry() -> None:
    benchmarks = json.loads(PackageData.read(PackageData.BENCHMARKS) or "{}")["benchmarks"]
    for benchmark in benchmarks:
        table = benchmark["published"]
        recommendation = table and table.get("lib_recommendation")
        if not recommendation:
            continue
        matching = [entry for entry in table["entries"] if entry["model_name"] == recommendation]
        assert table["freshness"] == "current"
        assert matching and matching[0]["status"] == "eligible"


def test_generated_refresh_capability_is_derived_from_exact_upstream_ids() -> None:
    benchmarks = {
        row["id"]: row
        for row in json.loads(PackageData.read(PackageData.BENCHMARKS) or "{}")["benchmarks"]
    }
    registered = {source.benchmark_id for source in UpstreamSource.registry()}
    for benchmark_id, benchmark in benchmarks.items():
        assert benchmark["refresh_supported"] is (benchmark_id in registered)
    assert benchmarks["mmmu_pro"]["refresh_supported"] is False
    assert benchmarks["mmmu_pro"]["source_auth"] == ""
    assert benchmarks["mmmu_pro"]["requires_auth"] is False


def test_runtime_refresh_uses_exact_registered_benchmark_id(monkeypatch) -> None:
    source = next(source for source in UpstreamSource.registry() if source.benchmark_id == "mmmu")
    table = PublishedTable(
        source_url=source.url, retrieved="2026-09-06",
        entries=[PublishedEntry(model_name="exact", score=0.8, status="eligible")],
    )
    monkeypatch.setattr(GroundingLeaderboardJS, "fetch", lambda self: table)
    monkeypatch.setattr(UpstreamSource, "_registry", [source])
    assert set(fetch_all(["mmmu", "mmmu_pro"])) == {"mmmu"}
    assert set(benchmark_tables.load_tables(refresh=True)) == {"mmmu"}


@pytest.mark.parametrize(
    ("legacy", "replacement"),
    [("aa.mmmu > 0.8", "aa.mmmu_pro"), ("aa.mmbench > 0.8", "oc.mmbench")],
)
def test_semantically_corrected_benchmark_names_fail_with_migration_guidance(
    legacy: str, replacement: str,
) -> None:
    with pytest.raises(CriteriaError, match=replacement.replace(".", r"\.")):
        Criteria.parse(legacy)
