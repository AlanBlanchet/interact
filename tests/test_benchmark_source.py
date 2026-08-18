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
import time

import pytest

from interact import benchmark_source as bs


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
