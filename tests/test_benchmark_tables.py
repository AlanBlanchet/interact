"""Runtime leaderboard tables for the vision/video/audio benchmarks.

The upstreams existed but were only ever run by hand, writing into the PACKAGED data file — so an
installed copy could never refresh, and the panel served a hand-written fallback forever. That is
how a months-old model stayed on screen as the best at MMMU.
"""

import time

import pytest

import interact.benchmark_tables as bt
from interact.benchmarks.published import PublishedEntry, PublishedTable
from interact.models import Model, ModelCapability
from interact.criteria import Criteria


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    yield


def _table(model="NewModel-9B", score=0.99):
    return PublishedTable(source_url="https://example.test", retrieved="2026-08-18",
                          freshness="current",
                          entries=[PublishedEntry(model_name=model, score=score, status="eligible")])


def test_a_fetch_is_cached_so_the_panel_does_not_hit_the_network_every_render(monkeypatch):
    calls = []
    monkeypatch.setattr("interact.benchmarks.upstream.fetch_all",
                        lambda *a, **k: calls.append(1) or {"mmmu": _table()})
    assert bt.load_tables()["mmmu"].entries[0].model_name == "NewModel-9B"
    bt.load_tables()
    assert len(calls) == 1, "a fresh cache must not refetch"


def test_refresh_bypasses_the_ttl(monkeypatch):
    calls = []
    monkeypatch.setattr("interact.benchmarks.upstream.fetch_all",
                        lambda *a, **k: calls.append(1) or {"mmmu": _table()})
    bt.load_tables()
    bt.load_tables(refresh=True)
    assert len(calls) == 2


def test_an_unreachable_upstream_serves_the_stale_cache_rather_than_nothing(monkeypatch):
    monkeypatch.setattr("interact.benchmarks.upstream.fetch_all", lambda *a, **k: {"mmmu": _table()})
    bt.load_tables()
    raw = bt._CACHE.read()
    raw["fetched_at"] = time.time() - (bt.TTL_SECONDS * 10)
    bt._CACHE.write(raw)

    def _boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr("interact.benchmarks.upstream.fetch_all", _boom)
    stale = bt.load_tables()["mmmu"]
    assert stale.entries[0].model_name == "NewModel-9B"
    assert stale.freshness == "stale"


def test_no_cache_and_no_network_is_empty_not_an_exception(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr("interact.benchmarks.upstream.fetch_all", _boom)
    assert bt.load_tables() == {}


def test_legacy_mmmu_snapshot_is_never_resurrected_from_cache(monkeypatch):
    legacy = PublishedTable(
        source_url="https://mmmu-benchmark.github.io/",
        retrieved="2026-06-07",
        lib_recommendation="GPT-5.4",
        entries=[PublishedEntry(model_name=name, score=score) for name, score in (
            ("GPT-5.4", 0.94), ("Claude Opus 4.7", 0.927),
            ("Gemini 3.1 Pro", 0.84), ("Qwen3.5", 0.77),
        )],
    )
    bt._CACHE.write({"fetched_at": time.time(), "tables": {
        "mmmu_pro": legacy.model_dump(mode="json"),
    }})

    assert "mmmu_pro" not in bt.load_tables()
    assert PublishedTable.load("mmmu_pro", bt.cache_path()) is None


@pytest.mark.parametrize(
    ("benchmark_id", "source_url", "models"),
    [
        ("video_mme", "https://video-mme.github.io/", ("Kimi K2.5", "Gemini 2.5 Pro", "Qwen3.6 Plus")),
        ("mmmu_pro", "https://mmmu-benchmark.github.io/", ("GPT-5.4", "Claude Opus 4.7", "Gemini 3.1 Pro", "Qwen3.5")),
    ],
)
def test_unreceipted_persisted_fallbacks_are_rejected(
    benchmark_id: str, source_url: str, models: tuple[str, ...],
) -> None:
    bt._CACHE.write({"schema_version": 1, "fetched_at": time.time(), "tables": {
        benchmark_id: {"source_url": source_url, "retrieved": "2026-06-07",
                       "entries": [{"model_name": model, "score": 0.8} for model in models]},
    }})
    assert benchmark_id not in bt.load_tables()


def test_mapped_numeric_entry_is_unverified_until_producer_opts_in(monkeypatch) -> None:
    model = Model(id="vendor/exact", provider="vendor", capabilities={ModelCapability.VLM})
    monkeypatch.setattr(Model, "_registry", [model])
    table = PublishedTable(source_url="https://example.test", retrieved="2026-09-06",
                           freshness="current", entries=[PublishedEntry(
                               model_name="exact", model_id=model.id, score=0.9,
                               normalized_score=0.9,
                           )])
    benchmark = next(b for b in __import__("interact.models", fromlist=["Benchmark"]).Benchmark.registry()
                     if b.id == "mmmu_pro").model_copy(update={"published": table})
    assert table.entries[0].status == "unverified"
    assert benchmark.recommend(available_only=False) == []
    assert benchmark.lib_recommendation_model() is None


def test_cache_requires_current_envelope_and_explicit_entry_authority() -> None:
    old = {"fetched_at": time.time(), "tables": {"x": _table().model_dump(mode="json")}}
    assert bt._parse(old) == {}


def test_one_corrupt_table_does_not_blank_the_others(monkeypatch):
    monkeypatch.setattr("interact.benchmarks.upstream.fetch_all",
                        lambda *a, **k: {"mmmu": _table(), "video_mme": _table("Other")})
    bt.load_tables()
    raw = bt._CACHE.read()
    raw["tables"]["mmmu"] = {"nonsense": True}
    bt._CACHE.write(raw)
    tables = bt.load_tables()
    assert "mmmu" not in tables and tables["video_mme"].entries[0].model_name == "Other"


def test_an_empty_upstream_table_is_not_cached_over_a_real_one(monkeypatch):
    """Observed live: the OpenVLM sources answered 200 with ZERO entries for MMMU and Video-MME.
    Caching that would replace a real (if old) snapshot with nothing — trading stale data for no
    data, which is the same mistake in the other direction."""
    monkeypatch.setattr("interact.benchmarks.upstream.fetch_all",
                        lambda *a, **k: {"mmmu": _table(), "video_mme": _empty()})
    tables = bt.load_tables()
    assert "mmmu" in tables
    assert "video_mme" not in tables, "an empty table carries no information; it must not win"


def _empty():
    return PublishedTable(source_url="https://example.test", retrieved="2026-08-18", entries=[])


@pytest.mark.parametrize(
    ("published_name", "registered_id"),
    [("Holo1.5", "azure/o1"), ("GPT-5.4", "azure/gpt5")],
)
def test_published_identity_never_uses_substring_aliases(
    published_name: str, registered_id: str,
) -> None:
    Model._reset()
    try:
        Model._register(Model(
            id=registered_id, provider="azure", capabilities={ModelCapability.VLM},
        ))
        assert PublishedTable._fuzzy_match_registered(published_name) is None
        assert Model.match_published(published_name) is None
    finally:
        Model._reset()


def test_live_display_table_is_the_same_score_criteria_executes(monkeypatch) -> None:
    monkeypatch.setattr(Model, "_registry", [])
    model = Model(id="vendor/exact-model", provider="vendor", capabilities={ModelCapability.VLM})
    Model._register(model)
    live = _table("exact-model")
    live.entries[0].score = 0.91
    live.entries[0].normalized_score = 0.91
    live.entries[0].model_id = model.id
    monkeypatch.setattr("interact.criteria.benchmark_tables.load_tables", lambda: {"mmmu_pro": live})

    assert Criteria.parse("aa.mmmu_pro > 0.9").choose(available_only=False) == model


@pytest.mark.parametrize(
    ("freshness", "status", "model_id", "normalized"),
    [("stale", "eligible", "vendor/exact-model", 0.99),
     ("current", "approximate", "vendor/exact-model", 0.99),
     ("current", "missing", "vendor/exact-model", None),
     ("current", "unmapped", None, 0.99)],
)
def test_non_authoritative_scores_never_qualify(
    monkeypatch, freshness: str, status: str, model_id: str | None, normalized: float | None,
) -> None:
    model = Model(id="vendor/exact-model", provider="vendor", capabilities={ModelCapability.VLM})
    monkeypatch.setattr(Model, "_registry", [model])
    table = PublishedTable(
        source_url="https://example.test", retrieved="2026-09-06", freshness=freshness,
        entries=[PublishedEntry(model_name="exact-model", model_id=model_id, score=0.99,
                                normalized_score=normalized, status=status)],
    )
    monkeypatch.setattr("interact.criteria.benchmark_tables.load_tables", lambda: {"mmmu_pro": table})
    assert Criteria.parse("aa.mmmu_pro > 0.9").choose(available_only=False) is None
