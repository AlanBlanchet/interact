"""What a vendor said about its own quota, remembered past the run that heard it.

A quota refusal is a fact about the ACCOUNT for a period, not about one launch: the model that
answered "you've reached your Fable limit" answers the same thing to the next agent a second
later. Without a memory, every launch pays the same tax — spawn, wait, die at $0.00, fall
through — and a refusal arriving after the probe's window kills the run outright (#181).

So the refusal is written down, and a model under cooldown is passed over BEFORE anything is
spawned. The cooldown expires on its own, so nothing has to be cleared by hand when the vendor's
window rolls over; and when EVERY candidate is under cooldown the walk ignores the memory rather
than refusing to launch, because a stale note must never be the reason an agent cannot run.
"""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import suppress
from pathlib import Path

#: A vendor CLI's own refusal for QUOTA or RATE LIMIT, e.g. "You've reached your <model> limit.
#: Switch to another model." or "rate limit exceeded" — the one failure that cannot be seen
#: before the child starts, because only the provider itself knows its quota (#181).
REFUSAL = re.compile(
    r"reached your .{0,80}\b(limit|quota)\b"
    r"|usage limit reached"
    r"|quota exceeded"
    r"|switch to another model"
    # A vendor's own rate-limit line only counts when it says the request was REFUSED: a healthy
    # child opens its stream with `rate_limit_info: {"status":"allowed"}`, and reading that as a
    # refusal skipped every candidate on the list.
    r"|rate[ _-]?limit(?:ed)?\b[^\n]{0,80}?\b(exceeded|rejected|reached)"
    r"|\"status\"\s*:\s*\"rejected\"",
    re.IGNORECASE,
)

#: How long a refused model is passed over. Short enough that a five-hour window reopens by
#: itself within the hour, long enough that a seven-day window is not re-probed every launch.
DEFAULT_COOLDOWN = 3600.0
COOLDOWN_ENV = "INTERACT_QUOTA_COOLDOWN_SECONDS"


def _path() -> Path:
    return Path.home() / ".interact" / "out" / "agents" / "quota-cooldowns.json"


def _cooldown() -> float:
    raw = os.environ.get(COOLDOWN_ENV)
    if raw is None:
        return DEFAULT_COOLDOWN
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_COOLDOWN


def _key(provider: str, model: str | None) -> str:
    return f"{provider}/{model or ''}"


def _read() -> dict[str, float]:
    with suppress(Exception):
        raw = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {str(k): float(v) for k, v in raw.items() if isinstance(v, (int, float))}
    return {}


def _write(entries: dict[str, float]) -> None:
    path = _path()
    with suppress(Exception):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, sort_keys=True), encoding="utf-8")
        tmp.replace(path)


def blocked_until(provider: str, model: str | None, *, now: float | None = None) -> float | None:
    """When this model may be tried again, or None when nothing is remembered against it."""
    moment = time.time() if now is None else now
    until = _read().get(_key(provider, model))
    return until if until is not None and until > moment else None


def record_refusal(provider: str, model: str | None, *,
                   now: float | None = None, cooldown: float | None = None) -> float:
    """Remember that this model refused for quota; returns when it may be tried again."""
    moment = time.time() if now is None else now
    until = moment + (_cooldown() if cooldown is None else cooldown)
    entries = {k: v for k, v in _read().items() if v > moment}
    entries[_key(provider, model)] = until
    _write(entries)
    return until


def forget(provider: str | None = None, model: str | None = None) -> None:
    """Drop one remembered refusal, or all of them when called bare."""
    if provider is None:
        _write({})
        return
    entries = _read()
    entries.pop(_key(provider, model), None)
    _write(entries)
