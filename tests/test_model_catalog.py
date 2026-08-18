"""Live model metadata, so the panel shows what is TRUE today rather than what was baked in.

The shipped `models.json` is a snapshot that ages silently — a user reads a context window or a
price that stopped being right months ago and has no way to tell. This fetches OpenRouter's
public catalog (no key, no signup) and falls back to LiteLLM's MIT-licensed static file, which is
already a dependency.

The rule these tests encode: **the catalog always says where it came from and how old it is.**
Data whose provenance is invisible is exactly the problem being fixed, so a stale cache is
allowed to be served — but never allowed to pretend it is fresh.
"""

import json
import time

import pytest

from interact import model_catalog as mc


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    yield


_OPENROUTER = {
    "data": [
        {
            "id": "anthropic/claude-sonnet-5",
            "name": "Claude Sonnet 5",
            "context_length": 1_000_000,
            "pricing": {"prompt": "0.000003", "completion": "0.000015"},
            "architecture": {"input_modalities": ["text", "image"]},
        },
        {
            "id": "google/gemini-3-pro",
            "name": "Gemini 3 Pro",
            "context_length": 2_000_000,
            "pricing": {"prompt": "0.00000125", "completion": "0.00001"},
            "architecture": {"input_modalities": ["text", "image", "video"]},
        },
    ]
}


def _serve(monkeypatch, payload=_OPENROUTER, fail=False):
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        if fail:
            raise OSError("no network")

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return payload

        return R()

    monkeypatch.setattr(mc.httpx, "get", fake_get)
    return calls


def test_a_live_fetch_is_parsed_and_marked_live(monkeypatch):
    _serve(monkeypatch)
    cat = mc.load_catalog()
    assert cat.source == "openrouter"
    assert cat.age_seconds < 5
    ids = {m.id for m in cat.models}
    assert "anthropic/claude-sonnet-5" in ids
    sonnet = next(m for m in cat.models if m.id == "anthropic/claude-sonnet-5")
    assert sonnet.context_length == 1_000_000
    assert sonnet.input_cost_per_token == pytest.approx(3e-6)
    assert "image" in sonnet.input_modalities


def test_no_network_falls_back_and_says_so(monkeypatch):
    _serve(monkeypatch, fail=True)
    cat = mc.load_catalog()
    assert cat.source in ("litellm", "bundled")
    assert cat.models, "the fallback must actually carry models"
    # The whole point: the caller can tell this is not live.
    assert cat.is_live is False


def test_a_fresh_cache_is_not_refetched(monkeypatch):
    calls = _serve(monkeypatch)
    mc.load_catalog()
    mc.load_catalog()  # a second call, as a second process would: same cache file on disk
    assert len(calls) == 1, "a fresh cache must not hit the network again"


def test_refresh_bypasses_the_ttl_so_a_long_lived_server_does_not_serve_startup_data(monkeypatch):
    """`load_catalog` used to be `@lru_cache`d, which made any periodic refresher a silent no-op
    after its first call — the server would keep serving whatever it read the day it started."""
    calls = _serve(monkeypatch)
    mc.load_catalog()
    mc.load_catalog(refresh=True)
    assert len(calls) == 2, "refresh must re-fetch even while the cache is still inside its TTL"


def test_a_stale_cache_is_served_when_the_network_is_down_but_reports_its_age(monkeypatch):
    _serve(monkeypatch)
    mc.load_catalog()
    # Age the cache well past its TTL, then take the network away.
    raw = json.loads(mc.cache_path().read_text())
    raw["fetched_at"] = time.time() - (mc.TTL_SECONDS * 10)
    mc.cache_path().write_text(json.dumps(raw))
    _serve(monkeypatch, fail=True)

    cat = mc.load_catalog()
    assert cat.models, "a stale cache beats no data"
    assert cat.age_seconds > mc.TTL_SECONDS
    assert cat.is_live is False, "stale data must never claim to be current"


def test_a_corrupt_cache_never_raises(monkeypatch):
    mc.cache_path().parent.mkdir(parents=True, exist_ok=True)
    mc.cache_path().write_text("{ not json")
    _serve(monkeypatch, fail=True)
    assert mc.load_catalog().models  # degrades to the bundled fallback


def test_garbage_entries_are_skipped_not_fatal(monkeypatch):
    _serve(monkeypatch, payload={"data": [{"no_id": True}, _OPENROUTER["data"][0]]})
    cat = mc.load_catalog()
    assert [m.id for m in cat.models] == ["anthropic/claude-sonnet-5"]


def test_freshness_renders_for_a_human():
    assert "just now" in mc.describe_age(2).lower()
    assert "h" in mc.describe_age(7200) or "hour" in mc.describe_age(7200)
    assert "d" in mc.describe_age(86400 * 3) or "day" in mc.describe_age(86400 * 3)
