"""Runtime leaderboard tables for the vision/video/audio benchmarks.

The upstreams existed but were only ever run by hand, writing into the PACKAGED data file — so an
installed copy could never refresh, and the panel served a hand-written fallback forever. That is
how a months-old model stayed on screen as the best at MMMU.
"""

import time

import pytest

import interact.benchmark_tables as bt
from interact.benchmarks.published import PublishedEntry, PublishedTable


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    yield


def _table(model="NewModel-9B", score=0.99):
    return PublishedTable(source_url="https://example.test", retrieved="2026-08-18",
                          entries=[PublishedEntry(model_name=model, score=score)])


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
    assert bt.load_tables()["mmmu"].entries[0].model_name == "NewModel-9B"


def test_no_cache_and_no_network_is_empty_not_an_exception(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr("interact.benchmarks.upstream.fetch_all", _boom)
    assert bt.load_tables() == {}


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
