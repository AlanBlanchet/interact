"""On-disk record of every agent run: what is running, who started it, what it cost.

Cross-process by design — the CLI spawns, the VS Code extension reads, another shell stops. So
the directory is a FIXED ``~/.interact/out/agents``, never ``debug_dir``-relative: two processes
disagreeing about where to look is exactly how metering broke before (0ef5fa4), and
``server_registry`` pins its own path for the same reason.

Status is DERIVED from the pid on every read. A record cannot assert it is still running — a
killed agent reports as crashed instead of spinning forever in the UI.
"""

import json
import os
import signal
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from interact.agents.events import AgentEvent
from interact.agents.providers import PROVIDERS
from interact.server_registry import _alive  # generic pid liveness (Windows-safe, no signal sent)

RunStatus = Literal["running", "done", "failed", "crashed", "stopped", "foreign"]


class AgentRun(BaseModel):
    """One supervised run. ``run_id`` is the vendor's own session id where the CLI lets us set it
    (Claude Code's ``--session-id``), so `claude --resume <run_id>` and this record agree with no
    mapping table to fall out of date."""

    run_id: str
    provider: str
    name: str
    task: str = ""
    cwd: str = ""
    pid: int | None = None
    model: str | None = None
    parent_run_id: str | None = None
    started_at: float = 0.0
    finished_at: float | None = None
    exit_code: int | None = None
    #: True for a session interact did NOT spawn — the user's own editor windows, surfaced so the
    #: supervisor shows the machine's real state rather than only its own children.
    foreign: bool = False

    status: RunStatus = "running"
    #: API-EQUIVALENT cost. On a subscription run the user is not billed this again; they already
    #: paid for the plan. Callers must label it as equivalent value, never as fresh spend.
    cost_usd: float | None = None
    last: str = ""


def agents_dir() -> Path:
    """The fixed, well-known registry directory (see the module docstring on why it is fixed)."""
    return Path.home() / ".interact" / "out" / "agents"


def _record_path(run_id: str) -> Path:
    return agents_dir() / f"{run_id}.json"


def events_path(run_id: str) -> Path:
    return agents_dir() / f"{run_id}.jsonl"


def _terminate(pid: int) -> bool:
    """Stop a run's whole process tree, best effort. Agent CLIs spawn children (their own tools),
    so signalling the group is what actually stops the work."""
    try:
        killpg, getpgid = getattr(os, "killpg", None), getattr(os, "getpgid", None)
        if killpg and getpgid:
            killpg(getpgid(pid), signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def register(*, run_id: str, pid: int | None, provider: str, name: str, task: str = "",
             cwd: str = "", model: str | None = None, parent_run_id: str | None = None) -> AgentRun:
    run = AgentRun(run_id=run_id, pid=pid, provider=provider, name=name, task=task, cwd=cwd,
                   model=model, parent_run_id=parent_run_id, started_at=time.time())
    d = agents_dir()
    d.mkdir(parents=True, exist_ok=True)
    _record_path(run_id).write_text(run.model_dump_json())
    return run


def finish(run_id: str, *, exit_code: int | None) -> None:
    """Record how a run ended, so its outcome survives the process disappearing."""
    stored = _read_record(run_id)
    if stored is None:
        return
    stored.finished_at = time.time()
    stored.exit_code = exit_code
    stored.status = _status_for(stored)
    _write(stored)


def stop(run_id: str) -> bool:
    """Ask a run to stop. Returns False for an unknown run rather than raising."""
    stored = _read_record(run_id)
    if stored is None:
        return False
    if stored.pid:
        _terminate(stored.pid)
    stored.finished_at = time.time()
    stored.exit_code = -signal.SIGTERM
    stored.status = "stopped"
    _write(stored)
    return True


def _read_record(run_id: str) -> AgentRun | None:
    try:
        return AgentRun.model_validate_json(_record_path(run_id).read_text())
    except (OSError, ValueError):
        return None


def _write(run: AgentRun) -> None:
    _record_path(run.run_id).write_text(run.model_dump_json())


def append_event(run_id: str, event: AgentEvent) -> None:
    """Persist an event AND fold it into the run record.

    The record has to carry the running totals, not just the event log: the VS Code panel reads
    these files directly and cannot replay a whole JSONL per row, so a cost or activity line
    computed only on the Python read path would show up there as blank and free. Folding here
    keeps it O(1) per event and makes the record authoritative for every reader.
    """
    path = events_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(event.model_dump_json() + "\n")

    stored = _read_record(run_id)
    if stored is None:
        return
    if event.cost_usd is not None:
        stored.cost_usd = (stored.cost_usd or 0.0) + event.cost_usd
    summary = event.summary()
    if summary:  # system/hook events summarise to nothing; they must not blank the row
        stored.last = summary
    _write(stored)


def read_events(run_id: str) -> list[AgentEvent]:
    """Every event of a run. A corrupt line is skipped, never fatal — a truncated write during a
    crash must not make the whole run unreadable."""
    try:
        lines = events_path(run_id).read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(AgentEvent.model_validate_json(line))
        except ValueError:
            continue
    return out


def last_event(run_id: str) -> AgentEvent | None:
    events = read_events(run_id)
    return events[-1] if events else None


def _status_for(run: AgentRun) -> RunStatus:
    """The one thing a file cannot assert about itself: whether it is still running."""
    if run.exit_code is not None:
        return ("stopped" if run.exit_code == -signal.SIGTERM
                else "done" if run.exit_code == 0 else "failed")
    if run.pid and _alive(run.pid):
        return "running"
    # It never recorded an ending and its process is gone — it died without saying so.
    return "crashed"


def _derive(run: AgentRun) -> AgentRun:
    """Re-check liveness on read. Cost and activity are already folded into the record by
    :func:`append_event`, so every reader — including the VS Code panel — sees the same values."""
    run.status = _status_for(run)
    return run


def _discover_foreign() -> list[dict]:
    """Sessions the providers can see that we did not spawn."""
    found: list[dict] = []
    for provider in PROVIDERS.values():
        try:
            found.extend(provider.discover())
        except Exception:  # a provider's discovery must never break the listing
            continue
    return found


def list_runs(*, include_foreign: bool = False) -> list[AgentRun]:
    """Every known run, newest last. With ``include_foreign``, also the sessions a provider can
    see that interact did not start — deduped against our own by id, since we deliberately reuse
    the vendor's session id as our run id."""
    d = agents_dir()
    runs: list[AgentRun] = []
    if d.exists():
        for path in sorted(d.glob("*.json")):
            try:
                runs.append(AgentRun.model_validate_json(path.read_text()))
            except (OSError, ValueError):
                continue  # a corrupt record must not hide every other run
    runs = [_derive(r) for r in runs]

    if include_foreign:
        known = {r.run_id for r in runs}
        for raw in _discover_foreign():
            sid = raw.get("sessionId") or raw.get("id")
            if not sid or sid in known:
                continue
            known.add(sid)
            runs.append(AgentRun(
                run_id=sid, provider="claude", foreign=True, status="foreign",
                name=raw.get("name") or sid[:8], cwd=raw.get("cwd") or "",
                pid=raw.get("pid"), started_at=(raw.get("startedAt") or 0) / 1000.0,
                last=raw.get("kind") or "",
            ))
    return sorted(runs, key=lambda r: r.started_at)


def children_of(run_id: str) -> list[AgentRun]:
    """The runs a given run spawned — the cross-provider team tree."""
    return [r for r in list_runs() if r.parent_run_id == run_id]
