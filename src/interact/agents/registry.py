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
    #: The repo/package the run belongs to — the grouping unit, derived from `cwd` at registration
    #: so it survives even if the directory is later moved or deleted.
    project: str = ""
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


#: Markers that make a directory the root of a PROJECT. Grouping on the working directory's own
#: name splits one repo across several groups the moment an agent runs in a subfolder — `src` and
#: `tests` show up as separate projects. The repo root is the unit people mean by "project".
#: A REPOSITORY boundary. Checked first and on its own, because a repo is the unit people mean by
#: "project": this repo's `vscode-extension/` has its own package.json, and treating that as a root
#: filed one repo's agents under two different projects — the "project detection is folder level"
#: complaint, still true after the first fix because a manifest counted equally with a VCS root.
_REPO_MARKERS = (".git", ".hg", ".svn")
#: A package boundary — only meaningful when nothing above it is a repo at all (a loose tool in a
#: directory nobody version-controls still deserves its own name rather than falling back to $HOME).
_PACKAGE_MARKERS = ("pyproject.toml", "package.json", "Cargo.toml", "go.mod")


def project_for(cwd: str) -> str:
    """The project a working directory belongs to — the enclosing REPOSITORY, by name.

    A repo root wins over any package manifest inside it, so a sub-package (this repo's own
    ``vscode-extension/`` and its package.json) files under the repo rather than as a project of
    its own. Only when nothing above is version-controlled does a package manifest count, so a
    loose tool still gets its own name instead of falling back to a home directory.

    Empty for an unknown directory — a wrong project label is worse than none, because it
    silently merges unrelated work.
    """
    if not cwd:
        return ""
    try:
        here = Path(cwd).expanduser().resolve()
    except (OSError, RuntimeError):
        return ""
    chain = (here, *here.parents)
    for markers in (_REPO_MARKERS, _PACKAGE_MARKERS):
        for candidate in chain:
            if any((candidate / marker).exists() for marker in markers):
                return candidate.name
    return here.name


def agents_dir() -> Path:
    """The fixed, well-known registry directory (see the module docstring on why it is fixed)."""
    return Path.home() / ".interact" / "out" / "agents"


def _record_path(run_id: str) -> Path:
    return agents_dir() / f"{run_id}.json"


def messages_path(run_id: str) -> Path:
    """Messages live BESIDE the vendor stream, never inside it. The stream is the vendor's own
    file and the mirror is rewritten from it, so anything appended there is clobbered on the next
    read — a message must outlive that."""
    return agents_dir() / f"{run_id}.messages.jsonl"


def events_path(run_id: str) -> Path:
    return agents_dir() / f"{run_id}.jsonl"


def raw_events_path(run_id: str) -> Path:
    """Where the child writes its OWN stream, verbatim. Owned by the OS, not by any interact
    process — so the record of what an agent did survives interact restarting or dying."""
    return agents_dir() / f"{run_id}.raw.jsonl"


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
                   project=project_for(cwd), model=model, parent_run_id=parent_run_id,
                   started_at=time.time())
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
    summary = event.summary(viewer=run_id)
    if summary:  # system/hook events summarise to nothing; they must not blank the row
        stored.last = summary
    _write(stored)


def record_message(*, from_run: str, to_run: str, text: str) -> bool:
    """Record one agent addressing another, on BOTH transcripts.

    Written to each side because an exchange visible to only one of them is not an exchange: the
    sender's history should show what it asked for, and the recipient's should show the request
    directly above whatever it did next. Returns False for an unknown recipient rather than
    writing a message nobody can receive.
    """
    if _read_record(to_run) is None:
        return False
    for side in (from_run, to_run):
        # Anchored to THIS side's raw stream: the message belongs before whatever that agent
        # writes next, and the two sides are at different points in their own streams.
        event = AgentEvent(kind="message", text=text, from_run=from_run, to_run=to_run,
                           raw_index=_raw_line_count(side))
        path = messages_path(side)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(event.model_dump_json() + "\n")
    # Keep the run rows current: a message is the most recent thing that happened to both.
    # Each side sees the exchange from its own point of view: the recipient reads "← sender",
    # the sender "→ recipient". One shared string would show one of them an arrow pointing at
    # itself, which is what made real messaging indistinguishable from noise.
    for side in (from_run, to_run):
        stored = _read_record(side)
        if stored is not None:
            stored.last = event.summary(viewer=side)
            _write(stored)
    return True


def _raw_line_count(run_id: str) -> int:
    """How many lines the vendor stream holds right now — where a message lands in it."""
    try:
        return sum(1 for _ in raw_events_path(run_id).open("rb"))
    except OSError:
        return 0


def _interleave(parsed: list[AgentEvent], messages: list[AgentEvent],
                total_raw: int) -> list[AgentEvent]:
    """Both streams in the order they happened.

    The vendor writes no timestamps, so a message carries the raw-line count at the moment it was
    sent: it belongs before every parsed event that came from a later line. Appending messages at
    the end instead showed each question after the answer it prompted.
    """
    def anchor(event: AgentEvent) -> int:
        # An event with no anchor is placed at the END: we do not know when it happened, and
        # reading "unknown" as position zero put every such message above the run's first turn.
        return event.raw_index if event.raw_index is not None else total_raw

    out: list[AgentEvent] = []
    pending = sorted(messages, key=anchor)
    for event in parsed:
        while pending and anchor(pending[0]) <= anchor(event):
            out.append(pending.pop(0))
        out.append(event)
    return out + pending


def _read_messages(run_id: str) -> list[AgentEvent]:
    try:
        lines = messages_path(run_id).read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(AgentEvent.model_validate_json(line))
        except ValueError:
            continue
    return out


def messages() -> list[AgentEvent]:
    """Every recorded exchange, in order — the edges a sequence or graph view draws. Deduped,
    since each message is stored on both sides."""
    seen: set[tuple] = set()
    out: list[AgentEvent] = []
    for run in list_runs():
        for event in read_events(run.run_id):
            if event.kind != "message":
                continue
            key = (event.from_run, event.to_run, event.text)
            if key in seen:
                continue
            seen.add(key)
            out.append(event)
    return out


def read_events(run_id: str) -> list[AgentEvent]:
    """Every event of a run, normalised.

    Reads the RAW vendor stream the child wrote itself and translates it through that provider's
    parser. A corrupt or half-written line is skipped, never fatal — a truncated write during a
    crash must not make the whole run unreadable.
    """
    stored = _read_record(run_id)
    provider = PROVIDERS.get(stored.provider) if stored else None
    try:
        raw_lines = raw_events_path(run_id).read_text(errors="replace").splitlines()
    except OSError:
        raw_lines = []

    # A raw stream is AUTHORITATIVE when present: the child wrote it itself, so it cannot be out
    # of date. The mirror below is derived from it, and re-reading both would double-count.
    if provider is not None and raw_lines:
        parsed: list[AgentEvent] = []
        for index, line in enumerate(raw_lines):
            try:
                event = provider.parse(line)
            except Exception:
                continue
            if event is not None:
                parsed.append(event.model_copy(update={"raw_index": index}))
        merged = _interleave(parsed, _read_messages(run_id), len(raw_lines))
        # The mirror is what the VS Code panel reads, so it must carry the WHOLE conversation.
        # Written without messages, the chat showed the agent talking to nobody.
        _mirror_normalised(run_id, merged)
        return merged

    # No raw stream — events were appended directly (a test, or a provider that has none).
    out: list[AgentEvent] = []
    try:
        for line in events_path(run_id).read_text().splitlines():
            try:
                out.append(AgentEvent.model_validate_json(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out + _read_messages(run_id)


def _mirror_normalised(run_id: str, events: list[AgentEvent]) -> None:
    """Keep a provider-AGNOSTIC copy of the stream beside the raw one.

    The VS Code panel cannot parse a vendor dialect — teaching it every provider's JSON would
    duplicate the adapters in a second language. Translating once here means the panel reads one
    stable shape whatever produced it. Rewritten only when the CONTENT changed, so a settled run
    costs nothing to re-read — comparing the LENGTH alone was not enough, because a change to how
    events are ordered or rendered leaves the count identical, so the panel kept serving the old
    shape forever and the only symptom was the UI quietly disagreeing with the CLI.
    """
    path = events_path(run_id)
    payload = "".join(e.model_dump_json() + "\n" for e in events)
    try:
        if path.read_text() == payload:
            return
    except OSError:
        pass
    try:
        path.write_text(payload)
    except OSError:
        pass


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
    if not run.project and run.cwd:
        run.project = project_for(run.cwd)
    """Re-check liveness, and SELF-HEAL the record from the child's own stream.

    The panel reads these records directly and cannot parse a vendor dialect, so cost and the
    activity line have to be ON the record. Recomputing them here from the raw stream means a run
    whose supervising process died still reports what it actually did, instead of looking healthy
    and empty."""
    run.status = _status_for(run)
    events = read_events(run.run_id)
    # The child's OWN stream is the authority on how it ended. If it reported a terminal event,
    # the run finished — even if nothing was watching to record an exit code. Without this, a run
    # whose supervisor died reports "crashed" while its transcript plainly says it completed.
    if run.exit_code is None and events:
        terminal = next((e for e in reversed(events) if e.kind in ("done", "error")), None)
        if terminal is not None:
            run.status = "done" if terminal.kind == "done" else "failed"
    # A process that dies never calls finish(), so an ended run routinely has no end TIME — and a
    # timeline cannot draw an interval without one. The last byte the child wrote is an OBSERVED
    # end: not when it died, but the last moment we know it was alive, which is honest and
    # drawable. Only ever stamped for a run that is no longer running.
    if run.finished_at is None and run.status != "running":
        try:
            run.finished_at = raw_events_path(run.run_id).stat().st_mtime
        except OSError:
            pass
    if events:
        costs = [e.cost_usd for e in events if e.cost_usd is not None]
        cost = sum(costs) if costs else None
        last = next((e.summary(viewer=run.run_id) for e in reversed(events)
                     if e.summary(viewer=run.run_id)), run.last)
        run.cost_usd, run.last = cost, last
    # Persist whatever we healed — status included. The panel reads these files directly and does
    # its own (downgrade-only) liveness check, so a status left stale on disk reappears there as
    # "crashed" no matter what Python worked out in memory.
    if _read_record(run.run_id) != run:
        _write(run)
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


def forget(run_id: str) -> bool:
    """Remove a finished run and everything it wrote. False if it is still running, or unknown.

    Nothing could remove a run before, so the panel grew forever — every agent ever spawned stayed
    listed, with its transcript and raw stream on disk. A live run is never forgotten: the record
    is the only handle on the process, so dropping it would leave an agent still working and
    invisible.
    """
    resolved = resolve_run_id(run_id)
    if resolved is None:
        return False
    run = _read_record(resolved)
    if run is None or _status_for(run) == "running":
        return False
    for path in (_record_path(resolved), events_path(resolved),
                 messages_path(resolved), raw_events_path(resolved)):
        try:
            path.unlink()
        except OSError:
            pass  # already gone, or not ours to delete — never fail a cleanup over one file
    return True


def clear_finished() -> list[str]:
    """Forget every run that has stopped; returns the ids removed."""
    return [r.run_id for r in list_runs() if not r.foreign and forget(r.run_id)]


def resolve_run_id(prefix: str) -> str | None:
    """The full run id a prefix names, or None if it names none or more than one.

    `interact agents list` prints 8-character ids, so an id copied off the tool's own output has
    to work everywhere an id is taken. Ambiguity resolves to None rather than to a guess: picking
    one at random would stop or message the WRONG agent.
    """
    if not prefix:
        return None
    ids = [r.run_id for r in list_runs(include_foreign=True)]
    if prefix in ids:
        return prefix  # an exact id is never ambiguous, even if it prefixes another
    matches = [rid for rid in ids if rid.startswith(prefix)]
    return matches[0] if len(matches) == 1 else None


def children_of(run_id: str) -> list[AgentRun]:
    """The runs a given run spawned — the cross-provider team tree."""
    return [r for r in list_runs() if r.parent_run_id == run_id]
