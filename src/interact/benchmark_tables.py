"""Live leaderboard tables for the GUI / vision / video / audio benchmarks.

Distinct from :mod:`interact.benchmark_source`, which serves Artificial Analysis's overall
intelligence ranking. AA publishes text and reasoning benchmarks only — no MMMU, no Video-MME, no
MMAU — so it cannot answer "which model is best at reading a screen", which is the question this
product is actually about. Those numbers come from the per-benchmark upstreams in
:mod:`interact.benchmarks.upstream` (OpenVLM and friends).

Those upstreams already existed and were only ever run by hand, writing into the PACKAGED data
file — a build step, so an installed copy could never refresh. The panel therefore served a
hand-written offline fallback forever, showing a months-old model as the best at MMMU with its
retrieved date buried in a tooltip. Fetching at runtime into the user's own cache is what makes
the displayed number able to change.
"""

import time

from interact.benchmarks.published import PublishedTable
from interact.ttl_cache import TTL_SECONDS, TTLCache, age_of

#: Leaderboards move slowly, but the cost of being wrong here is showing a stale model as best,
#: so this shares the catalog's TTL rather than inventing a longer one.
_CACHE = TTLCache("benchmark_tables.json", TTL_SECONDS)


def cache_path():
    return _CACHE.path


def load_tables(*, refresh: bool = False) -> dict[str, PublishedTable]:
    """The freshest per-benchmark tables available, keyed by benchmark id; ``{}`` when none.

    Never raises: a panel that cannot reach a leaderboard must still render, falling back to the
    packaged snapshot, which carries its own retrieved date.
    """
    cached = _CACHE.read()
    if not refresh and cached and age_of(float(cached.get("fetched_at", 0))) <= TTL_SECONDS:
        return _parse(cached)

    from interact.benchmarks.upstream import fetch_all

    try:
        fetched = fetch_all()
    except Exception:
        return _parse(cached) if cached else {}
    # An upstream that answers with NO entries carries no information — observed live, where the
    # OpenVLM sources returned 200 and zero rows for MMMU and Video-MME. Letting that through
    # would replace a real (if old) packaged snapshot with an empty panel: stale data traded for
    # no data, which is the same mistake pointing the other way.
    usable = {bid: table for bid, table in fetched.items() if table.entries}
    if not usable:
        return _parse(cached) if cached else {}
    _CACHE.write({
        "fetched_at": time.time(),
        "tables": {bid: table.model_dump(mode="json") for bid, table in usable.items()},
    })
    return usable


def _parse(raw: dict | None) -> dict[str, PublishedTable]:
    tables = (raw or {}).get("tables") or {}
    out = {}
    for bid, payload in tables.items():
        try:
            out[bid] = PublishedTable.model_validate(payload)
        except Exception:
            continue  # one unreadable table must not blank the rest
    return out
