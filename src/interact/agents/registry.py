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
import re
import secrets
import signal
import stat
import sys
import time
from pathlib import Path
from typing import BinaryIO, Literal

from pydantic import BaseModel, Field, PrivateAttr

from interact.agents.events import AgentEvent
from interact.agents.providers import PROVIDERS
from interact.server_registry import (
    _alive,  # generic pid liveness (Windows-safe, no signal sent)
)

RunStatus = Literal[
    "starting", "running", "waiting", "done", "failed", "cancelled", "crashed", "stopped",
    "foreign",
]
RunKind = Literal["process", "conversation", "provider_child"]
ConnectionMode = Literal["local_session", "api"]
ChargePath = Literal[
    "subscription_quota", "usage_credit", "metered_api", "local_compute", "unknown"
]
CostCertainty = Literal["known", "unknown"]
AggregateChargePath = ChargePath | Literal["mixed"]
ConversationCapability = Literal[
    "streaming", "resume", "cancel", "approvals", "collaboration"
]
_RUN_ID = re.compile(r"^[A-Za-z0-9._:@+-]{1,160}$")


class AgentRun(BaseModel):
    """One supervised run. ``run_id`` is the vendor's own session id where the CLI lets us set it
    (Claude Code's ``--session-id``), so `claude --resume <run_id>` and this record agree with no
    mapping table to fall out of date."""

    run_id: str
    kind: RunKind = "process"
    provider: str
    name: str
    task: str = ""
    cwd: str = ""
    #: The repo/package the run belongs to — the grouping unit, derived from `cwd` at registration
    #: so it survives even if the directory is later moved or deleted.
    project: str = ""
    pid: int | None = None
    model: str | None = None
    #: The DEFINITION this run is — a name the provider resolves to a file holding its system
    #: prompt and tool set (Claude Code: ``~/.claude/agents/<agent>.md``). None for a plain run.
    #: Without it a run knows its label but not what it actually IS, so nothing can link to it.
    agent: str | None = None
    #: Where that definition's system prompt actually lives, resolved at registration. The name
    #: alone is only answerable by a caller that can import this module and ask the provider — and
    #: the panel reads these records straight off disk, so a name it cannot resolve is a link it
    #: cannot offer. Recorded, not derived on read, so it also survives the file being moved later.
    definition_path: str | None = None
    #: How much autonomy this run was GIVEN, when the choice was made explicitly. Recorded because
    #: it is the answer to "why did that one stop to ask" and "why did that one just do it" — a
    #: question about a run you are watching that nothing else on the record can answer. None
    #: means nobody chose, so the CLI's own configured default applied.
    permission_mode: str | None = None
    parent_run_id: str | None = None
    root_run_id: str | None = None
    spawned_by_event_id: str | None = None
    provider_session_id: str | None = None
    provider_turn_id: str | None = None
    connection: ConnectionMode | None = None
    requested_model: str | None = None
    requested_criterion: str | None = None
    cataloged_at: float | None = None
    charge_path: ChargePath = "unknown"
    cost_certainty: CostCertainty = "unknown"
    capabilities: list[ConversationCapability] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    started_at: float = 0.0
    finished_at: float | None = None
    exit_code: int | None = None
    #: True for a session interact did NOT spawn — the user's own editor windows, surfaced so the
    #: supervisor shows the machine's real state rather than only its own children.
    foreign: bool = False

    status: RunStatus = "running"
    #: API-equivalent value of observed usage. The actual account impact is represented separately
    #: by ``charge_path`` and ``cost_certainty`` and remains unknown without provider evidence.
    cost_usd: float | None = None
    #: Cumulative token use — how much CONTEXT this run has consumed, which is invisible from a
    #: cost figure alone (two models at the same price consume very differently).
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    last: str = ""

    @classmethod
    def from_foreign(cls, raw: dict) -> "AgentRun | None":
        """One of the user's OWN sessions, as reported by a provider's discovery.

        The class owns its own construction because this shape was being built in two places —
        the listing and the CLI's `agents discovered`, which the VS Code panel parses — with the
        same nine fields, the same id fallback and the same millisecond division duplicated. A
        field added here would have reached one and not the other, and the panel would never have
        noticed the difference.

        None when the payload carries no session id: there is nothing to address it by, so it is
        not a run we can show, resume or stop.
        """
        sid = raw.get("sessionId") or raw.get("id")
        if not sid:
            return None
        cwd = raw.get("cwd") or ""
        return cls(
            run_id=sid,
            provider="claude",
            name=raw.get("name") or sid[:8],
            cwd=cwd,
            # Filed like every registered run is. Without this a foreign session had a working
            # directory and no project — visible in the flat list, invisible to the workspace
            # switcher, which groups by project. That is exactly "i have agents in the sheets
            # folder elsewhere, and i can't change and see how they work".
            project=project_for(cwd),
            pid=raw.get("pid"),
            started_at=(raw.get("startedAt") or 0) / 1000.0,
            last=raw.get("kind") or "",
            status="foreign",
            foreign=True,
        )


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


def _ensure_registry_directory() -> Path:
    """Create and repair the private directory chain without changing the user's home mode."""
    directory = agents_dir()
    home = Path.home()
    try:
        relative = directory.relative_to(home)
    except ValueError:
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise OSError(f"unsafe agent registry directory: {directory}")
        directory.chmod(0o700)
    else:
        current = home
        for part in relative.parts:
            current /= part
            current.mkdir(mode=0o700, exist_ok=True)
            if current.is_symlink() or not current.is_dir():
                raise OSError(f"unsafe agent registry directory: {current}")
            current.chmod(0o700)
    return directory


def _open_private(path: Path, flags: int, *, create: bool = True) -> int:
    directory = _ensure_registry_directory()
    if path.parent != directory:
        raise OSError("agent registry file escaped its private directory")
    directory_descriptor = _registry_directory_descriptor()
    try:
        creation_flags = os.O_CREAT if create else 0
        descriptor = os.open(
            path.name, flags | creation_flags | _no_follow_flags(), 0o600,
            dir_fd=directory_descriptor,
        )
    finally:
        os.close(directory_descriptor)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("agent registry path is not a regular file")
        os.fchmod(descriptor, 0o600)
    except OSError:
        os.close(descriptor)
        raise
    return descriptor


def _no_follow_flags() -> int:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if (
        not isinstance(no_follow, int) or no_follow <= 0
        or not isinstance(directory, int) or directory <= 0
        or os.open not in os.supports_dir_fd
        or os.rename not in os.supports_dir_fd
        or os.unlink not in os.supports_dir_fd
    ):
        raise OSError("agent registry requires effective O_NOFOLLOW and dir_fd support")
    return no_follow


def _registry_directory_descriptor() -> int:
    no_follow = _no_follow_flags()
    directory_flag = os.O_DIRECTORY
    directory = _ensure_registry_directory()
    home = Path.home()
    try:
        relative = directory.relative_to(home)
    except ValueError as error:
        raise OSError("agent registry directory must be anchored beneath the user home") from error
    descriptor = os.open(home, os.O_RDONLY | directory_flag | no_follow)
    try:
        for part in relative.parts:
            child = os.open(
                part, os.O_RDONLY | directory_flag | no_follow, dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("agent registry directory handle is not a directory")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_private(path: Path) -> bytes | None:
    _no_follow_flags()
    try:
        descriptor = _open_private(path, os.O_RDONLY, create=False)
    except OSError:
        return None
    try:
        stream = os.fdopen(descriptor, "rb")
    except OSError:
        os.close(descriptor)
        raise
    with stream:
        return stream.read()


def _private_mtime(path: Path) -> float | None:
    descriptor = _open_private(path, os.O_RDONLY, create=False)
    try:
        return os.fstat(descriptor).st_mtime
    finally:
        os.close(descriptor)


def _append_private(path: Path, payload: bytes) -> None:
    descriptor = _open_private(path, os.O_APPEND | os.O_WRONLY)
    try:
        if os.write(descriptor, payload) != len(payload):
            raise OSError("short agent-registry append")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _private_leaf_matches(
    name: str, directory_descriptor: int, identity: tuple[int, int],
) -> bool:
    """Check identity already visible before publication, without promising atomic same-UID
    defence for the final check-to-rename window. Directory mode 0700 excludes other OS users;
    another process under the same account remains inside this bounded trust boundary."""
    try:
        comparison = os.open(
            name, os.O_RDONLY | _no_follow_flags(), dir_fd=directory_descriptor,
        )
    except OSError:
        return False
    matches = False
    try:
        opened = os.fstat(comparison)
        matches = stat.S_ISREG(opened.st_mode) and (
            opened.st_dev, opened.st_ino
        ) == identity
    except OSError:
        pass
    try:
        os.close(comparison)
    except OSError:
        return False
    return matches


def _replace_private(path: Path, payload: bytes) -> None:
    directory = _ensure_registry_directory()
    if path.parent != directory:
        raise OSError("agent registry file escaped its private directory")
    directory_descriptor = _registry_directory_descriptor()
    descriptor = -1
    replacement_name: str | None = None
    owned_identity: tuple[int, int] | None = None
    try:
        candidate_name = f".{path.name}.{secrets.token_hex(8)}.new"
        descriptor = os.open(
            candidate_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _no_follow_flags(),
            0o600,
            dir_fd=directory_descriptor,
        )
        replacement_name = candidate_name
        created = os.fstat(descriptor)
        owned_identity = (created.st_dev, created.st_ino)
        os.fchmod(descriptor, 0o600)
        if os.write(descriptor, payload) != len(payload):
            raise OSError("short agent-registry write")
        os.fsync(descriptor)
        written = os.fstat(descriptor)
        owned_identity = (written.st_dev, written.st_ino)
        if not _private_leaf_matches(
            replacement_name, directory_descriptor, owned_identity,
        ):
            raise OSError("agent registry replacement identity changed before publication")
        os.replace(
            replacement_name, path.name,
            src_dir_fd=directory_descriptor, dst_dir_fd=directory_descriptor,
        )
    finally:
        primary_error = sys.exception()
        cleanup_error: OSError | None = None
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError as error:
                cleanup_error = error
        if replacement_name is not None and owned_identity is not None and _private_leaf_matches(
            replacement_name, directory_descriptor, owned_identity,
        ):
            try:
                os.unlink(replacement_name, dir_fd=directory_descriptor)
            except FileNotFoundError:
                pass
            except OSError as error:
                cleanup_error = cleanup_error or error
        try:
            os.close(directory_descriptor)
        except OSError as error:
            cleanup_error = cleanup_error or error
        if primary_error is None and cleanup_error is not None:
            raise cleanup_error


def _safe_run_id(run_id: str) -> str:
    if run_id in (".", "..") or _RUN_ID.fullmatch(run_id) is None:
        raise ValueError("invalid agent run id")
    return run_id


def _record_path(run_id: str) -> Path:
    return agents_dir() / f"{_safe_run_id(run_id)}.json"


def messages_path(run_id: str) -> Path:
    """Messages live BESIDE the vendor stream, never inside it. The stream is the vendor's own
    file and the mirror is rewritten from it, so anything appended there is clobbered on the next
    read — a message must outlive that."""
    return agents_dir() / f"{_safe_run_id(run_id)}.messages.jsonl"


def events_path(run_id: str) -> Path:
    return agents_dir() / f"{_safe_run_id(run_id)}.jsonl"


def raw_events_path(run_id: str) -> Path:
    """Where the child writes its OWN stream, verbatim. Owned by the OS, not by any interact
    process — so the record of what an agent did survives interact restarting or dying."""
    return agents_dir() / f"{_safe_run_id(run_id)}.raw.jsonl"


def open_raw_events(run_id: str, *, append: bool) -> BinaryIO:
    """Open a provider-owned stream while preserving registry privacy under any umask."""
    flags = os.O_APPEND if append else os.O_TRUNC
    descriptor = _open_private(raw_events_path(run_id), flags | os.O_WRONLY)
    return os.fdopen(descriptor, "ab" if append else "wb")


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
             cwd: str = "", model: str | None = None, parent_run_id: str | None = None,
             agent: str | None = None, permission_mode: str | None = None) -> AgentRun:
    provider_impl = PROVIDERS.get(provider)
    definition = provider_impl.definition_path(agent) if (provider_impl and agent) else None
    run = AgentRun(run_id=run_id, pid=pid, provider=provider, name=name, task=task, cwd=cwd,
                   project=project_for(cwd), model=model, parent_run_id=parent_run_id,
                   agent=agent, definition_path=str(definition) if definition else None,
                   permission_mode=permission_mode, started_at=time.time())
    _write(run)
    try:
        descriptor = _open_private(
            raw_events_path(run_id), os.O_APPEND | os.O_WRONLY, create=False
        )
    except FileNotFoundError:
        pass
    else:
        os.close(descriptor)
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
    _no_follow_flags()
    try:
        payload = _read_private(_record_path(run_id))
        if payload is None:
            return None
        run = AgentRun.model_validate_json(payload)
    except (OSError, ValueError):
        return None
    if run.run_id != run_id:
        return None
    return _backfill_definition(run)


def _backfill_definition(run: AgentRun) -> AgentRun:
    """Repair a record written before ``definition_path`` was tracked.

    Every reader of these files — the VS Code panel above all — reads them straight off disk and
    cannot ask a provider where its definitions live. Without this, each client keeps its own copy
    of one vendor's directory layout, which is the hard-coding the field exists to remove. Repaired
    on disk rather than re-resolved on every read, so it costs one write per stale record, once.
    """
    if run.definition_path is not None or not run.agent:
        return run
    provider = PROVIDERS.get(run.provider)
    resolved = provider.definition_path(run.agent) if provider is not None else None
    if resolved is None:
        return run
    run.definition_path = str(resolved)
    try:
        _write(run)
    except OSError:
        pass  # a read-only or vanished registry must not break reading
    return run


def _write(run: AgentRun) -> None:
    path = _record_path(run.run_id)
    _replace_private(path, run.model_dump_json().encode())


def save_run(run: AgentRun) -> None:
    """Persist a typed run after its owning lifecycle changed it."""
    _write(run)


def get_run(run_id: str) -> AgentRun | None:
    """Read one canonical run record without deriving the whole registry."""
    return _read_record(run_id)


def append_event(run_id: str, event: AgentEvent) -> None:
    """Persist an event AND fold it into the run record.

    The record has to carry the running totals, not just the event log: the VS Code panel reads
    these files directly and cannot replay a whole JSONL per row, so a cost or activity line
    computed only on the Python read path would show up there as blank and free. Folding here
    keeps it O(1) per event and makes the record authoritative for every reader.
    """
    stored = _read_record(run_id)
    if stored is None:
        return
    terminal = stored.status in ("done", "failed", "cancelled", "crashed", "stopped")
    same_turn = event.turn_id is None or event.turn_id == stored.provider_turn_id
    newer_root_turn = (
        stored.kind == "conversation" and event.kind in ("started", "prompt")
        and event.turn_id is not None and event.turn_id != stored.provider_turn_id
    )
    if stored.kind == "conversation" and event.turn_id is not None and not same_turn \
            and not newer_root_turn:
        return
    if terminal and same_turn:
        return

    _append_private(events_path(run_id), (event.model_dump_json() + "\n").encode())
    if event.cost_usd is not None:
        stored.cost_usd = (stored.cost_usd or 0.0) + event.cost_usd
    if event.kind == "tool" and event.tool is not None and event.tool not in stored.tools:
        stored.tools.append(event.tool)
    for field in ("input_tokens", "output_tokens", "cached_input_tokens"):
        used = getattr(event, field)
        if used is not None:
            setattr(stored, field, (getattr(stored, field) or 0) + used)
    summary = event.summary(viewer=run_id)
    if summary:  # system/hook events summarise to nothing; they must not blank the row
        stored.last = summary
    if stored.kind == "conversation":
        if newer_root_turn:
            stored.provider_turn_id = event.turn_id
            stored.status = "running"
            stored.finished_at = None
        if event.kind == "done":
            stored.status = "done"
            stored.finished_at = event.at if event.at is not None else time.time()
        elif event.kind == "cancelled":
            stored.status = "cancelled"
            stored.finished_at = event.at if event.at is not None else time.time()
        elif event.kind == "error":
            stored.status = "failed"
            stored.finished_at = event.at if event.at is not None else time.time()
        elif event.kind == "interaction":
            stored.status = "waiting"
        elif not terminal and event.kind in ("started", "prompt", "text", "thinking", "tool"):
            stored.status = "running"
    elif stored.kind == "provider_child":
        was_terminal = stored.status in ("done", "failed", "cancelled", "crashed", "stopped")
        if event.kind == "done":
            stored.status = "done"
        elif event.kind == "cancelled":
            stored.status = "cancelled"
        elif event.kind == "error":
            stored.status = "failed"
        elif event.kind == "interaction" and not was_terminal:
            stored.status = "waiting"
        elif not was_terminal and event.kind in ("started", "prompt", "text", "thinking", "tool"):
            stored.status = "running"
        if event.kind in ("done", "error", "cancelled") and stored.finished_at is None:
            stored.finished_at = event.at if event.at is not None else time.time()
    _write(stored)


class _ConversationProjector(BaseModel):
    """The conversation event cursor, persistence, and snapshot boundary."""

    _seen: dict[str, set[str]] = PrivateAttr(default_factory=dict)
    _sequences: dict[str, int] = PrivateAttr(default_factory=dict)

    def apply_child(self, child: AgentRun, event: AgentEvent) -> AgentRun | None:
        parent_run_id = child.parent_run_id
        root_run_id = child.root_run_id
        spawned_by_event_id = child.spawned_by_event_id
        if parent_run_id is None or root_run_id is None or spawned_by_event_id is None:
            raise ValueError("provider child metadata is incomplete")
        upsert_provider_child(
            run_id=child.run_id,
            provider=child.provider,
            parent_run_id=parent_run_id,
            root_run_id=root_run_id,
            spawned_by_event_id=spawned_by_event_id,
            cwd=child.cwd,
            task=child.task or None,
            requested_model=child.requested_model,
            status=child.status,
            started_at=child.started_at,
            finished_at=child.finished_at,
        )
        return self.apply(parent_run_id, event)

    def apply(self, run_id: str, event: AgentEvent) -> AgentRun | None:
        if run_id not in self._seen:
            persisted = read_events(run_id)
            self._seen[run_id] = {item.event_id for item in persisted if item.event_id}
            self._sequences[run_id] = max(
                (item.sequence or 0 for item in persisted), default=0
            )
        if event.event_id and event.event_id in self._seen[run_id]:
            return None
        self._sequences[run_id] += 1
        event.sequence = self._sequences[run_id]
        if event.event_id:
            self._seen[run_id].add(event.event_id)
        if event.at is None:
            event.at = time.time()
        if event.kind == "text" and ":delta:" in event.event_id:
            return get_run(run_id)
        append_event(run_id, event)
        return get_run(run_id)


class _BillingSummary(BaseModel):
    charge_path: AggregateChargePath
    paths: list[ChargePath]
    cost_certainty: CostCertainty


def billing_summary(runs: list[AgentRun]) -> _BillingSummary:
    paths: list[ChargePath] = list(dict.fromkeys(run.charge_path for run in runs))
    aggregate: AggregateChargePath = paths[0] if len(paths) == 1 else "mixed"
    certainty: CostCertainty = (
        "known" if paths and all(run.cost_certainty == "known" for run in runs) else "unknown"
    )
    return _BillingSummary(charge_path=aggregate, paths=paths, cost_certainty=certainty)


def upsert_provider_child(
    *, run_id: str, provider: str, parent_run_id: str, root_run_id: str,
    spawned_by_event_id: str, cwd: str, task: str | None, requested_model: str | None,
    status: RunStatus, started_at: float | None = None, finished_at: float | None = None,
) -> AgentRun:
    """Create or enrich one provider-native child without replay or order regressions."""
    run = _read_record(run_id)
    if run is not None and (
        run.kind != "provider_child"
        or run.provider != provider
        or run.root_run_id != root_run_id
        or run.parent_run_id != parent_run_id
    ):
        raise ValueError("provider child identity collision")
    if run is None:
        observed_at = time.time()
        run = AgentRun(
            run_id=run_id,
            kind="provider_child",
            provider=provider,
            name="subagent",
            task=task or "",
            cwd=cwd,
            project=project_for(cwd),
            pid=None,
            model=requested_model,
            parent_run_id=parent_run_id,
            root_run_id=root_run_id,
            spawned_by_event_id=spawned_by_event_id,
            provider_session_id=run_id,
            connection="local_session",
            requested_model=requested_model,
            charge_path="unknown",
            cost_certainty="unknown",
            capabilities=["collaboration"],
            started_at=started_at if started_at is not None else observed_at,
            finished_at=finished_at,
            status=status,
        )
        _write(run)
    if task:
        run.task = task
    if requested_model:
        run.requested_model = requested_model
        run.model = requested_model
    if status in ("starting", "running") or run.spawned_by_event_id is None:
        run.spawned_by_event_id = spawned_by_event_id
    rank = {"starting": 0, "running": 1, "waiting": 2, "cancelled": 3,
            "done": 4, "failed": 4, "crashed": 4, "stopped": 4, "foreign": 4}
    if rank[status] >= rank[run.status]:
        run.status = status
    if started_at is not None:
        run.started_at = min(run.started_at, started_at)
    if finished_at is not None:
        run.finished_at = finished_at
    elif run.status in ("done", "failed", "cancelled") and run.finished_at is None:
        run.finished_at = time.time()
    _write(run)
    return run


def record_message(*, from_run: str, to_run: str, text: str) -> bool:
    """Record one agent addressing another, on BOTH transcripts.

    Written to each side because an exchange visible to only one of them is not an exchange: the
    sender's history should show what it asked for, and the recipient's should show the request
    directly above whatever it did next. Returns False for an unknown recipient rather than
    writing a message nobody can receive.
    """
    _no_follow_flags()
    if _read_record(to_run) is None:
        return False
    for side in (from_run, to_run):
        # Anchored to THIS side's raw stream: the message belongs before whatever that agent
        # writes next, and the two sides are at different points in their own streams.
        # Stamped here rather than by the mirror: an exchange is recorded as it happens, so this
        # clock is exact rather than "when we next noticed". It is what lets the workplace animate
        # a conversation once, at the right moment — and on a cold open, replay the last minute of
        # traffic honestly instead of guessing from what a previous render happened to remember.
        event = AgentEvent(kind="message", text=text, from_run=from_run, to_run=to_run,
                           at=time.time(), raw_index=_raw_line_count(side))
        _append_private(
            messages_path(side), (event.model_dump_json() + "\n").encode()
        )
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
        payload = _read_private(raw_events_path(run_id))
        return 0 if payload is None else len(payload.splitlines())
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
        payload = _read_private(messages_path(run_id))
        lines = [] if payload is None else payload.decode().splitlines()
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
    _no_follow_flags()
    stored = _read_record(run_id)
    provider = PROVIDERS.get(stored.provider) if stored else None
    try:
        payload = _read_private(raw_events_path(run_id))
        raw_lines = [] if payload is None else payload.decode(errors="replace").splitlines()
    except OSError:
        raw_lines = []

    # A raw stream is AUTHORITATIVE when present: the child wrote it itself, so it cannot be out
    # of date. The mirror below is derived from it, and re-reading both would double-count.
    if provider is not None and raw_lines:
        parsed: list[AgentEvent] = []
        for index, line in enumerate(raw_lines):
            try:
                event = provider.parse(line)
            except (KeyError, TypeError, ValueError):
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
        payload = _read_private(events_path(run_id))
        for line in ([] if payload is None else payload.decode().splitlines()):
            try:
                out.append(AgentEvent.model_validate_json(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out + _read_messages(run_id)


def _carry_observed_at(path: Path, events: list[AgentEvent]) -> None:
    """Stamp when each event was first seen, keeping the stamps already on record.

    The mirror is rebuilt wholesale from a re-parse on every pass, so stamping the clock of the
    moment would march every event's time forward and mean nothing. The stream is append-only, so
    an event keeps whatever time position ``i`` already carried and only genuinely new lines take
    the current clock. Carrying them forward is also what keeps the content comparison below
    stable — otherwise every pass would differ and a settled run would be rewritten forever.
    """
    seen: list[float | None] = []
    try:
        payload = _read_private(path)
        for line in ([] if payload is None else payload.decode().splitlines()):
            if line.strip():
                seen.append(json.loads(line).get("at"))
    except (OSError, ValueError):
        seen = []
    now = time.time()
    for i, event in enumerate(events):
        prior = seen[i] if i < len(seen) else None
        event.at = prior if isinstance(prior, (int, float)) else now


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
    _carry_observed_at(path, events)
    payload = "".join(e.model_dump_json() + "\n" for e in events)
    try:
        existing = _read_private(path)
        if existing is not None and existing.decode() == payload:
            return
    except OSError:
        pass
    try:
        _replace_private(path, payload.encode())
    except OSError:
        pass


def last_event(run_id: str) -> AgentEvent | None:
    events = read_events(run_id)
    return events[-1] if events else None


def _status_for(run: AgentRun) -> RunStatus:
    """The one thing a file cannot assert about itself: whether it is still running."""
    if run.kind == "provider_child":
        return run.status
    if run.kind == "conversation":
        if run.status in ("waiting", "done", "failed", "cancelled", "stopped"):
            return run.status
        if run.pid and _alive(run.pid):
            return run.status
        return "crashed"
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
            run.status = (
                "waiting" if run.kind == "conversation" and terminal.kind == "done"
                else "done" if terminal.kind == "done"
                else "failed"
            )
    # A process that dies never calls finish(), so an ended run routinely has no end TIME — and a
    # timeline cannot draw an interval without one. The last byte the child wrote is an OBSERVED
    # end: not when it died, but the last moment we know it was alive, which is honest and
    # drawable. Only ever stamped for a run that is no longer running.
    if run.finished_at is None and run.status != "running":
        try:
            run.finished_at = _private_mtime(raw_events_path(run.run_id))
        except OSError:
            pass
    if events:
        costs = [e.cost_usd for e in events if e.cost_usd is not None]
        cost = sum(costs) if costs else None
        # Tokens the same way: cost alone hides how much CONTEXT a run consumed, and two models at
        # the same price consume very differently.
        for field in ("input_tokens", "output_tokens"):
            used = [getattr(e, field) for e in events if getattr(e, field) is not None]
            if used:
                setattr(run, field, sum(used))
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
        except (OSError, ValueError):  # one unavailable provider must not break listing
            continue
    return found


def list_runs(*, include_foreign: bool = False) -> list[AgentRun]:
    """Every known run, newest last. With ``include_foreign``, also the sessions a provider can
    see that interact did not start — deduped against our own by id, since we deliberately reuse
    the vendor's session id as our run id."""
    d = agents_dir()
    runs: list[AgentRun] = []
    known: set[str] = set()
    if d.exists():
        for path in sorted(d.glob("*.json")):
            run = _read_record(path.stem)
            if run is None or run.run_id in known:
                continue  # a corrupt or aliased record must not hide every other run
            known.add(run.run_id)
            runs.append(run)
    runs = [_derive(r) for r in runs]

    if include_foreign:
        known = {r.run_id for r in runs}
        for raw in _discover_foreign():
            found = AgentRun.from_foreign(raw)
            if found is None or found.run_id in known:
                continue
            known.add(found.run_id)
            runs.append(found)
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
