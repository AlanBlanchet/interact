"""Spawn an agent CLI and supervise it: stream its events, persist them, record how it ended.

Child leads its own process group (``start_new_session``): stopping a run must signal the whole
tree, else killing just the parent orphans its spawned subprocesses. Same reason sandbox does it
(#92).
"""

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
import json
import os
import re
import shutil
import sys
import threading
import uuid
from pathlib import Path
import subprocess
import tempfile
from typing import BinaryIO, Sequence
from interact_core import AgentRevisionRef

from interact.agents import registry as reg
from interact.agents.policy import Policy, policy_path
from interact.agents.profiles import overlay_for, profiles_from
from interact.agents.providers import PROVIDERS, AgentProvider, CodexProvider, UnsupportedToolPolicy, validate_denied_tools, _safe_process_detail
from interact.criteria import Criteria, CriteriaError, Variables
from interact.models import Model, ModelCapability



def resolve_model(
    model: str | None,
    env: dict[str, str],
    available_only: bool = True,
    provider: AgentProvider | None = None,
    weights: str = "",
) -> tuple[dict[str, str], str | None]:
    """Split a model id into (env overlay, what the vendor CLI should be asked for).

    A `provider/name` id says two things: WHERE to send the request, WHICH model to ask for. CLI
    understands only the second — hand it `ollama/deepseek-v4-pro:cloud` and it can't resolve
    anything; a company file doing exactly that once broke every researcher dispatch at startup,
    reverted and blamed elsewhere. Real cause: only a NAMED profile should ever go through this
    split.

    Unrecognised ids pass through untouched, deliberately: a bare `claude-sonnet-5` means the
    vendor's own endpoint; guessing an endpoint for an unknown prefix would send credentials
    somewhere unchosen.
    """
    if not model:
        return {}, None
    model = _resolve_criteria(model, available_only, env, provider, weights)
    overlay = overlay_for(model, env)
    if not overlay:
        return {}, model
    return overlay, overlay.get("ANTHROPIC_MODEL", model)


def rank_candidates(
    model: str, env: dict[str, str], *, providers: Sequence[AgentProvider], weights: str = "",
) -> tuple[reg.LaunchCandidate, ...]:
    """ONE ordered list across every given CLI — "we rank based on all providers, we get the
    first one from the criteria, and if not available we get the next one".

    `Criteria.ranked` runs once over the UNION of what the given CLIs can run, so a criterion has
    one answer whatever binary ends up running it; one provider given alone is that same list
    filtered, never a different ranking. A row two CLIs can run yields one candidate per CLI,
    in registry order, sharing the row's rank. A plain model id yields the CLIs that can run it,
    or every given CLI when the id is outside the catalog — passed through untouched, as
    :func:`resolve_model` does. The criterion itself is never relaxed: an empty list raises,
    naming the pools that were searched.
    """
    # The list is ranked over EVERY registered CLI and then filtered, so a rank means the same
    # thing whichever subset a caller asked for; the given providers only decide who may run.
    universe = list(PROVIDERS.values()) + [p for p in providers if p.name not in PROVIDERS]
    allowed = {p.name for p in providers}
    if model.startswith("@"):
        model = load_policy().rule(model)
    if not is_criterion(model):
        row = Model.by_id(model)
        candidates = tuple(
            reg.LaunchCandidate(provider=p.name, model=model, rank=0,
                                catalog_id=f"{row.provider}/{row.id}" if row is not None else None)
            for p in universe if p.name in allowed and (row is None or p.can_run(row, env))
        )
        if not candidates:
            names = ", ".join(sorted(allowed)) or "none"
            raise ModelUnavailable(f"The {names} CLIs cannot run model {model!r}")
        return candidates
    try:
        criteria = Criteria.parse(model)
    except CriteriaError as err:
        raise ModelUnavailable(f"{model!r} is not a usable model criterion: {err}") from err
    pool = lambda m: any(p.can_run(m, env) for p in universe if p.name in allowed)
    ranked = criteria.ranked(runnable=lambda m: any(p.can_run(m, env) for p in universe), weights=weights)
    candidates = tuple(
        reg.LaunchCandidate(provider=p.name, model=p.model_id_for(row),
                            catalog_id=f"{row.provider}/{row.id}", rank=rank)
        for rank, row in enumerate(ranked) for p in universe
        if p.name in allowed and p.can_run(row, env)
    )
    if not candidates:
        names = ", ".join(sorted(allowed)) or "none"
        raise ModelUnavailable(
            f"no model the {names} CLIs can run clears {criteria}:\n{criteria.explain(True, pool)}"
        )
    return candidates


async def _unavailable(
    provider: AgentProvider, policy: Policy, *, permission_mode: str | None, images: bool,
    allowed_tools: list[str], denied_tools: tuple[str, ...], env: dict[str, str],
    auth_cache: dict[tuple[str, str], bool | None], route_key: str,
) -> reg.SkipReason | None:
    """The machine-local fact stopping this candidate BEFORE anything runs, or None.

    Every check here is answerable without starting the task. Authentication runs the CLI's own
    auth-status command (no credential is read). Failed checks are distinct from logged-out
    status. Adapters without a status command leave authentication to their own launcher.
    """
    if not provider.available():
        return "cli_missing"
    if not policy.provider_active(provider.name):
        return "provider_off"
    try:
        provider.validate_permission_mode(permission_mode)
    except ValueError:
        return "permission_mode_unsupported"
    if images and not provider.image_attachment_support():
        return "images_unsupported"
    try:
        provider.validate_tool_policy(allowed_tools, denied_tools)
    except UnsupportedToolPolicy:
        return "tool_policy_unsupported"
    key = (provider.name, route_key)
    if key not in auth_cache:
        try:
            auth_cache[key] = await provider.authenticated(env, timeout=3)
        except NotImplementedError:
            auth_cache[key] = True
    if auth_cache[key] is None:
        return "auth_check_failed"
    if not auth_cache[key]:
        return "unauthenticated"
    return None


def load_policy() -> Policy:
    """Refresh server roles when configured; otherwise read the local policy file."""
    return Policy.load()


def model_for_agent(agent: str | None) -> str | None:
    """What this agent runs on, per policy — a profile's criterion, its own criterion, or a plain
    model id. None when policy doesn't mention it: leaves the caller's own choice (and ultimately
    the vendor's default) untouched."""
    if not agent:
        return None
    return load_policy().criterion_for(agent)


def tools_for_agent(agent: str | None) -> list[str]:
    """Tools this agent may use, expanded from its toolsets and fully prefixed."""
    if not agent:
        return []
    return load_policy().tools_for(agent)


def check_provider_active(provider: str) -> None:
    """Refuse to spawn through a provider the operator switched off.

    "we should be able to, from interact, chose if we activate the agents or not for a provider" —
    off means OFF at the one place every spawn passes through, not merely hidden in a picker.
    """
    active = load_policy().provider_active(provider)
    if not active:
        raise RuntimeError(
            f"agents are switched off for {provider!r} in {policy_path()} — "
            f'set {{"providers": {{"{provider}": true}}}} there to use it again'
        )


class ModelUnavailable(RuntimeError):
    """A criterion nothing currently clears. Raised rather than falling back: silently resolving
    to some other model is worse than none — it looks like it worked."""


#: A vendor CLI's own refusal for QUOTA or RATE LIMIT, e.g. "You've reached your <model> limit.
#: Switch to another model." or "rate limit exceeded" — the one failure `_unavailable()` cannot
#: see before the child starts, because only the provider itself knows its quota (#181).
_QUOTA_REFUSAL = re.compile(
    r"reached your .{0,80}\b(limit|quota)\b|rate.?limit(ed|ing)?|quota exceeded|"
    r"switch to another model|usage limit reached",
    re.IGNORECASE,
)


async def _quota_probe(run_id: str, process: "asyncio.subprocess.Process", *,
                        window: float = 4.0, interval: float = 0.2) -> reg.SkipReason | None:
    """Give a just-spawned child a short window to refuse for quota/rate-limit before this run
    commits to it. Such a refusal prints in the child's own stream and it exits almost
    immediately — the run "dies at $0.00" (#181) — while a genuinely working agent is still
    writing its first turn well past this window. Returns ``"quota_exceeded"`` when the refusal
    is seen, else ``None`` (including: still running past the window, which is the common case
    and must not be slowed down further than this one check).
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + window
    while process.returncode is None and loop.time() < deadline:
        await asyncio.sleep(interval)
    text = ""
    with suppress(Exception):
        text += reg.read_stderr(run_id)
    with suppress(Exception):
        raw = reg.raw_events_path(run_id)
        if raw.exists():
            text += raw.read_bytes()[-4000:].decode(errors="replace")
    return "quota_exceeded" if _QUOTA_REFUSAL.search(text) else None


_IMAGE_EXTENSIONS = frozenset({".jpeg", ".jpg", ".png", ".webp"})
_MAX_IMAGE_ATTACHMENTS = 8
_MAX_IMAGE_BYTES = 20 * 1024 * 1024


def validate_image_paths(
    image_paths: Sequence[str | Path] | None,
) -> tuple[Path, ...]:
    """Validate bounded, absolute raster paths without reading or logging their contents."""
    paths = tuple(Path(path) for path in (image_paths or ()))
    if len(paths) > _MAX_IMAGE_ATTACHMENTS:
        raise ValueError(
            f"at most {_MAX_IMAGE_ATTACHMENTS} image attachments are allowed; got {len(paths)}"
        )
    validated: list[Path] = []
    for path in paths:
        if not path.is_absolute():
            raise ValueError(f"image attachment path must be absolute: {path}")
        if path.suffix.lower() not in _IMAGE_EXTENSIONS:
            allowed = ", ".join(sorted(_IMAGE_EXTENSIONS))
            raise ValueError(f"unsupported image attachment type for {path}; use {allowed}")
        try:
            stat = path.stat()
            if not path.is_file():
                raise ValueError(f"image attachment is not a regular file: {path}")
            with path.open("rb"):
                pass
        except OSError as err:
            raise ValueError(f"image attachment is not readable: {path}") from err
        if stat.st_size <= 0:
            raise ValueError(f"image attachment is empty: {path}")
        if stat.st_size > _MAX_IMAGE_BYTES:
            raise ValueError(
                f"image attachment exceeds {_MAX_IMAGE_BYTES} bytes: {path}"
            )
        validated.append(path)
    return tuple(validated)


def _require_vlm_model(model: str | None) -> None:
    """Require catalog evidence that the resolved model accepts image input."""
    if not model:
        raise ModelUnavailable("image attachments require a resolved model with cap.vlm")
    Model.catalog()
    candidate = Model.match_published(model)
    if candidate is None:
        raise ModelUnavailable(
            f"model {model!r} is not known to the model catalog; image attachments require cap.vlm"
        )
    if not candidate.can(ModelCapability.VLM):
        raise ModelUnavailable(
            f"model {model!r} does not meet cap.vlm; image attachments were refused"
        )


def is_criterion(text: str) -> bool:
    """A model CRITERION vs a model id, told apart by SHAPE: a comparison operator, an `and`, or
    a lone variable name (`cap.vlm`) — no model id is spelled like a variable. Same shape test the
    spawn and the `agents policy` display share, so they cannot disagree."""
    return (
        any(op in text for op in ("<", ">", "="))
        or " and " in text
        or text.strip() in {v.name for v in Variables.all()}
    )


def _resolve_criteria(
    model: str, available_only: bool, env: dict[str, str] | None = None,
    provider: AgentProvider | None = None,
    weights: str = "",
) -> str:
    """A CRITERION where a model id goes.

    "we could say agent: 'MMLU > 0.8' to use a model that has MMLU above a criteria for a
    benchmark... Or also control price". A pin freezes at typing time; a criterion re-resolves
    every spawn, so a better or cheaper model shipping tomorrow is used tomorrow.

    Told apart by SHAPE, not a flag: a model id has no comparison operator or spaces, so
    `claude-sonnet-5` is an id and `gui.screenspot > 0.85 and price.in < 10` is a requirement.
    Vendor CLI never learns criteria exist — by invocation time this is a model name.

    With a `provider`, the pool is what THAT vendor CLI can be pointed at (`AgentProvider.can_run`)
    — its own models through its login, a routed one when its key is here — never the cheapest
    model in the whole catalog handed to a binary that cannot run it.
    """
    if model.startswith("@"):
        # A profile: a NAME for a criterion (`"profiles": {"eyes": "cap.vlm and ..."}`), honoured
        # wherever a model may be named — resolved to its rule here, read like any criterion.
        model = load_policy().rule(model)
    if not is_criterion(model):
        return model
    try:
        criteria = Criteria.parse(model)
    except CriteriaError as err:
        raise ModelUnavailable(f"{model!r} is not a usable model criterion: {err}") from err
    runnable = (lambda m: provider.can_run(m, env or {})) if provider is not None else None
    chosen = criteria.choose(available_only=available_only, runnable=runnable, weights=weights)
    if chosen is None:
        who = f"model the {provider.name} CLI can run" if provider is not None else "configured model"
        raise ModelUnavailable(
            f"no {who} clears {criteria}:\n{criteria.explain(available_only, runnable)}"
        )
    return provider.model_id_for(chosen) if provider is not None else chosen.id


def _interact_command() -> tuple[str, list[str]]:
    """How a spawned agent launches interact's MCP server. Prefer the installed console script;
    fall back to this interpreter so a checkout without one still meshes."""
    exe = shutil.which("interact")
    if exe:
        return exe, ["mcp"]
    return sys.executable, ["-m", "interact", "mcp"]


def already_meshed(provider: str, *, cwd: str | None = None) -> bool:
    """Whether this provider's OWN configuration already registers interact as an MCP server.

    "activate the agents for the provider, but once (and not twice)... no conflicts." `interact
    install` registers interact in the provider's user-scope config, so handing a spawned child
    `--mcp-config` with a second registration doubles the server in that session. Mesh exists for
    machines where the provider has NO interact of its own; where it does, attribution still
    flows — INTERACT_PARENT_RUN_ID rides the child's process env, the globally-configured server
    inherits it.

    Reads only. Codex configuration errors fail closed: an unreadable entry may disable
    the server, so injecting a replacement must not override that operator decision.
    """
    if provider == "codex":
        return CodexProvider().has_mcp_server("interact", cwd=cwd or str(Path.cwd()))
    checks = {
        "claude": Path.home() / ".claude.json",
        "cursor": Path.home() / ".cursor" / "mcp.json",
    }
    path = checks.get(provider)
    if path is None:
        return False
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    servers = data.get("mcpServers")
    return isinstance(servers, dict) and "interact" in servers


def mesh_config(*, run_id: str) -> str:
    """The ``--mcp-config`` payload handed to a spawned agent so it can reach back into interact.

    Makes cross-provider teamwork work with no bespoke protocol: child is an MCP client, interact
    is an MCP server, so a Claude agent and a Codex agent call the same tools.
    ``INTERACT_PARENT_RUN_ID`` travels with it so anything the child spawns attributes to it,
    keeping the team tree connected.

    Carries NO credential — the child's own CLI authenticates itself.
    """
    command, args = _interact_command()
    return json.dumps({
        "mcpServers": {
            "interact": {
                "command": command,
                "args": args,
                "env": {"INTERACT_PARENT_RUN_ID": run_id},
            }
        }
    })


@dataclass
class RunHandle:
    """A live run: its id, its process, and the task draining its output."""

    run_id: str
    process: asyncio.subprocess.Process
    pump: asyncio.Task = field(repr=False)
    model: str | None = None
    criterion: str | None = None
    reasoning: str | None = None

    async def wait(self) -> int:
        """Block until the run has ended AND every event has been persisted."""
        await self.pump
        return await self.process.wait()


class ContinuationHandle:
    """The launcher-owned lifecycle for a synchronous provider resume.

    The CLI and MCP surfaces both hand this same object around. Its daemon reaper survives either
    caller returning immediately, records the exit, and drains bounded stderr without leaving a
    child zombie behind.
    """

    def __init__(
        self, run_id: str, process: subprocess.Popen, raw_index: int,
        stderr_file: BinaryIO, lifecycle_token: str,
    ) -> None:
        self.run_id = run_id
        self.process = process
        self.raw_index = raw_index
        self.stderr_file = stderr_file
        self.lifecycle_token = lifecycle_token
        self.completed = threading.Event()
        self.reaper: threading.Thread | None = None
        self.exit_code: int | None = None

    def wait(self) -> int:
        """Wait for the child and the recorder, so the registry is current before reading it."""
        # The reaper is the sole owner of waitpid. Calling process.wait() here as well races it:
        # one waiter consumes the child and the other can block forever on the already-reaped pid.
        self.completed.wait()
        return self.exit_code if self.exit_code is not None else -1


_CONTINUATION_LOCKS: dict[str, threading.Lock] = {}
_CONTINUATION_LOCKS_GUARD = threading.Lock()


def continuation_lock(run_id: str) -> threading.Lock:
    """One lock per run; callers re-read the registry after acquiring it."""
    with _CONTINUATION_LOCKS_GUARD:
        return _CONTINUATION_LOCKS.setdefault(run_id, threading.Lock())


def _record_continuation_stderr(run_id: str, payload: bytes) -> None:
    if not payload:
        return
    # Keep only a bounded, redacted diagnostic. It is never included in a normal successful reply.
    detail = _safe_process_detail(payload.decode(errors="replace"))
    with suppress(OSError):
        sink = reg.open_stderr(run_id, append=False)
        try:
            sink.write(detail.encode())
            sink.flush()
        finally:
            sink.close()


def _reap_continuation(lifecycle: ContinuationHandle) -> None:
    run_id = lifecycle.run_id
    process = lifecycle.process
    stderr_file = lifecycle.stderr_file
    code: int | None = None
    try:
        code = process.wait()
        try:
            stderr_file.seek(0, os.SEEK_END)
            size = min(stderr_file.tell(), 8192)
            stderr_file.seek(-size, os.SEEK_END) if size else None
            payload = stderr_file.read(size) if size else b""
        except (OSError, ValueError):
            payload = b""
        if code:
            _record_continuation_stderr(run_id, payload)
        with suppress(Exception):
            reg.read_events(run_id)
        with suppress(Exception):
            reg.finish(
                run_id, exit_code=code, expected_pid=process.pid,
                expected_lifecycle_token=lifecycle.lifecycle_token,
            )
    except Exception:
        with suppress(Exception):
            reg.finish(
                run_id, exit_code=None, expected_pid=process.pid,
                expected_lifecycle_token=lifecycle.lifecycle_token,
            )
    finally:
        with suppress(Exception):
            stderr_file.close()
        lifecycle.exit_code = code
        lifecycle.completed.set()


def launch_continuation(
    provider: AgentProvider,
    run: reg.AgentRun,
    session_id: str,
    message: str,
    *,
    model: str | None,
    criterion: str | None,
    reasoning: str | None,
    raw_index: int,
    record_locked: bool = False,
) -> ContinuationHandle:
    """Spawn one resumed turn and start its reaper before returning to a caller."""
    policy = load_policy()
    policy, _ = policy.for_launch(run.agent, reference=run.agent_ref)
    catalog = policy.catalog
    routed: dict[str, str] = {}
    if catalog is not None:
        if not run.agent:
            raise ModelUnavailable("Server catalog continuation requires a named role")
        criterion = policy.criterion_for(run.agent)
        if not criterion:
            raise ModelUnavailable(f"No model criterion for {run.agent!r}")
        routed, model = resolve_model(criterion, dict(os.environ), provider=provider, weights=policy.weights_for(run.agent))
        reasoning = policy.reasoning_for(run.agent)
    provider.validate_tool_policy(policy.tools_for(run.agent), run.denied_tools)
    argv = provider.resume_command(
        session_id, message, model=model, permission_mode=run.permission_mode,
        reasoning=reasoning, agent=run.agent,
        allowed_tools=policy.tools_for(run.agent), denied_tools=run.denied_tools,
        agent_prompt=catalog.role_prompt(run.agent) if catalog is not None else None,
        mcp_config=mesh_config(run_id=run.run_id)
        if run.mesh_enabled and not already_meshed(provider.name, cwd=run.cwd) else None,
    )
    sink = reg.open_raw_events(run.run_id, append=True)
    stderr_file = tempfile.TemporaryFile()
    try:
        env = {**os.environ, **routed, "INTERACT_RUN_ID": run.run_id, "INTERACT_PARENT_RUN_ID": run.run_id}
        if provider.name == "claude":
            env["CLAUDE_CODE_EFFORT_LEVEL"] = reasoning
        process = subprocess.Popen(
            argv, cwd=run.cwd or ".", env=env, stdout=sink, stderr=stderr_file,
            start_new_session=True,
        )
    except BaseException:
        stderr_file.close()
        raise
    finally:
        sink.close()
    begin_turn = reg.begin_turn_locked if record_locked else reg.begin_turn
    current = begin_turn(
        run.run_id, pid=process.pid, model=model,
        requested_criterion=criterion, reasoning=reasoning,
    )
    if current is None:
        with suppress(Exception):
            process.terminate()
        with suppress(Exception):
            process.wait(timeout=5)
        stderr_file.close()
        raise RuntimeError(f"agent run {run.run_id!r} disappeared during continuation")
    lifecycle = ContinuationHandle(
        run.run_id, process, raw_index, stderr_file, current.lifecycle_token,
    )
    reaper = threading.Thread(
        target=_reap_continuation, args=(lifecycle,),
        name=f"interact-agent-reaper-{run.run_id[:8]}", daemon=True,
    )
    lifecycle.reaper = reaper
    reaper.start()
    return lifecycle


async def _mirror_while_alive(run_id: str, alive, *, interval: float = 1.0) -> None:
    """Keep the NORMALISED stream current while a run works.

    The child writes only the vendor's RAW stream; the provider-agnostic copy the VS Code panel
    reads is produced by ``read_events``. Nothing called it during a run, so a working agent
    looked idle its whole life and "watch the responses arrive" was impossible.

    Cheap by construction: ``read_events`` rewrites the mirror only when content actually changed,
    so a quiet run costs a parse and no write. Failures are swallowed — this runs beside a live
    agent, and a transient read must never take its stream down.
    """
    while alive():
        try:
            reg.read_events(run_id)
        except Exception:
            pass
        await asyncio.sleep(interval)
    with suppress(Exception):
        reg.read_events(run_id)  # last pass so the final turn is not left unmirrored


async def _mirror_running_runs(alive, *, interval: float = 1.0) -> None:
    """Keep EVERY live run's normalised stream current, not only the ones this process spawned.

    `agents spawn` detaches, so the pump started beside a run dies with its parent. The child
    keeps writing its raw stream, but the copy the VS Code panel reads is produced on demand — so
    a detached agent's activity froze on screen until something happened to call Python. Runs in
    the MCP server, alive whenever the user is working.

    Settled runs are skipped (nothing changes, re-reading wastes) and so are sessions interact did
    not start: reading someone else's transcript is not ours to do.
    """
    while alive():
        try:
            # `foreign` is checked as well as excluded by the query: reading someone else's
            # transcript isn't ours to do, and that guarantee shouldn't rest on one argument.
            runs = [r for r in reg.list_runs(include_foreign=False)
                    if r.status == "running" and not getattr(r, "foreign", False)]
        except Exception:
            runs = []
        for run in runs:
            try:
                reg.read_events(run.run_id)
            except Exception:
                continue  # one half-written stream must not stop the rest
        await asyncio.sleep(interval)


async def _reap(run_id: str, process, lifecycle_token: str) -> None:
    """Record how the run ended. EVENTS do not depend on this coroutine — the child writes them
    to disk itself (see :func:`run_agent`) — losing this task costs an exit code, never the
    stream."""
    try:
        code = await process.wait()
    except Exception:
        return
    with suppress(Exception):
        reg.read_events(run_id)
    reg.finish(
        run_id, exit_code=code, expected_pid=process.pid,
        expected_lifecycle_token=lifecycle_token,
    )


async def run_agent(
    provider: AgentProvider | None,
    task: str,
    *,
    name: str | None = None,
    cwd: str,
    agent: str | None = None,
    agent_ref: AgentRevisionRef | None = None,
    delegate: str | None = None,
    model: str | None = None,
    parent_run_id: str | None = None,
    permission_mode: str | None = None,
    profile: str | None = None,
    mesh: bool = True,
    image_paths: tuple[Path, ...] = (),
    denied_tools: tuple[str, ...] = (),
    provider_modes: dict[str, str] | None = None,
) -> RunHandle:
    """Spawn an agent run and register it, returning as soon as it is alive.

    Returns immediately by design: the supervisor's whole value is watching work in flight, so
    the run must be visible in the registry before it finishes.

    ``profile`` names one of the OPERATOR's own profiles (``INTERACT_PROFILE_*`` in config),
    deciding what this agent runs on — so the critic can sit on a local model while the reviewer
    stays frontier. Resolves through :mod:`interact.agents.profiles` to a fixed, allow-listed
    overlay; a caller cannot hand over an environment, because a model that can set
    ``LD_PRELOAD`` or ``PATH`` on the process it spawns has escaped every other guard here.

    ``parent_run_id`` defaults to ``INTERACT_PARENT_RUN_ID`` — set on a spawned agent's own MCP
    server by :func:`mesh_config` — so an agent spawning an agent produces a connected tree with
    nobody passing the id by hand.

    ``image_paths`` is an optional tuple of existing absolute PNG, JPEG, or WebP paths. The
    provider and resolved model are checked before any child process is created.

    ``provider`` None means the ranked choice: the role's criterion is ranked ONCE across every
    registered CLI (:func:`rank_candidates`) and the list is walked in order until a candidate
    can start here — installed, switched on, logged in, honouring the requested mode and
    attachments, AND not refused for quota or rate limit in the few seconds after it starts
    (:func:`_quota_probe`, #181) — the one failure only the provider itself can report, so it is
    checked moments after start rather than before. A named provider is the same list filtered
    to it and never falls through, quota included: the caller chose, so its failure is reported
    as such. Every other fall-through happens only BEFORE the child exists; whatever else
    happens once it can act — a denial, a crash, a stop — is that run's outcome and is never
    replayed on another candidate. Falling through never relaxes the criterion: the next
    candidate is still ranked under it, and every skip (quota included) is recorded on the run
    that finally started, naming which candidate ran and why each earlier one was passed over.
    """
    validated_images = validate_image_paths(image_paths)
    validate_denied_tools(denied_tools)
    for provider_name, mode in (provider_modes or {}).items():
        if provider_name not in PROVIDERS:
            raise ValueError(f"Unknown provider in workspace permissions: {provider_name!r}")
        PROVIDERS[provider_name].validate_permission_mode(mode)
    if provider is None and permission_mode is not None:
        # A mode NO registered CLI knows is a caller mistake, refused before any policy or
        # catalog is read — same edge as the named-provider check below, over the whole set.
        # A mode only SOME CLIs know is legal and narrows the walk (`permission_mode_unsupported`).
        accepted = {mode.id for p in PROVIDERS.values() for mode in p.permission_modes()}
        if permission_mode not in accepted:
            known = "; ".join(
                f"{p.name}: {', '.join(m.id for m in p.permission_modes()) or 'none'}"
                for p in PROVIDERS.values()
            )
            raise ValueError(
                f"{permission_mode!r} is not a permission mode any registered CLI accepts (known: {known})"
            )
    if provider is not None:
        provider.validate_permission_mode(permission_mode)
        if not provider.available():
            raise RuntimeError(
                f"the {provider.name!r} CLI is not installed (looked for {provider.binary!r} on PATH). "
                "interact drives the vendor's own binary with your own login; install and sign into "
                "it first."
            )
        if validated_images and not provider.image_attachment_support():
            raise RuntimeError(
                f"the {provider.name!r} provider does not support image attachments"
            )
    policy = load_policy()
    parent = parent_run_id or os.environ.get("INTERACT_PARENT_RUN_ID") or None
    parent_run = reg.get_run(parent) if parent is not None else None
    if policy.catalog is not None and parent is not None and (parent_run is None or parent_run.agent_ref is None):
        raise ModelUnavailable("Parent run has no recorded server revision; start the parent again")
    policy, agent = policy.for_launch(
        agent, reference=agent_ref,
        parent=parent_run.agent_ref if parent_run is not None else None, capability=delegate,
    )
    if provider is not None and not policy.provider_active(provider.name):
        raise ModelUnavailable(f"Agent provider {provider.name!r} is disabled by policy")
    if not agent:
        raise ModelUnavailable("Choose a named agent role; anonymous delegation bypasses role criteria")
    run_id = str(uuid.uuid4())
    selected_ref = None
    definition_path = None
    if policy.catalog is not None:
        selected = policy.catalog.role(agent)
        selected_ref = AgentRevisionRef(id=selected.id, revision=selected.revision)
        definition_path = policy.catalog.definition_path(agent)
    # Policy speaks for an agent with no own model: a profile is written once, worn by many —
    # the reason it exists.
    required_model = policy.criterion_for(agent)
    if profile:
        known = profiles_from(dict(os.environ))
        if profile not in known:
            raise RuntimeError(
                f"no such profile {profile!r}. Define it in ~/.interact/config.env as "
                f"INTERACT_PROFILE_{profile.upper()}=<provider>/<model>; "
                f"known: {', '.join(sorted(known)) or 'none'}"
            )
    if not required_model:
        raise ModelUnavailable(f"No model criterion for {agent!r}; configure it in the agent policy UI")
    if required_model and profile:
        raise ModelUnavailable(
            "A named agent's model policy cannot be bypassed with a provider profile. "
            "Change the agent's rule in the policy UI instead."
        )
    model = required_model or model
    weights = policy.weights_for(agent)
    # Explicit provider only narrows the pool; every candidate uses the same preflight.
    pool = [provider] if provider is not None else list(PROVIDERS.values())
    by_name = {p.name: p for p in pool}
    candidates = rank_candidates(model, dict(os.environ), providers=pool, weights=weights)
    skipped: list[reg.SkippedCandidate] = []
    chosen: reg.LaunchCandidate | None = None
    chosen_provider: AgentProvider | None = None
    process: "asyncio.subprocess.Process | None" = None
    model: str | None = None
    effort = policy.reasoning_for(agent)
    auth_cache: dict[tuple[str, str], bool | None] = {}
    allowed_tools = policy.tools_for(agent)
    base_env = dict(os.environ)
    for candidate in candidates:
        candidate_provider = by_name[candidate.provider]
        routed, resolved_model = resolve_model(candidate.model, base_env, provider=candidate_provider, weights=weights)
        reason = await _unavailable(
            candidate_provider, policy, permission_mode=permission_mode if permission_mode is not None else (provider_modes or {}).get(candidate.provider),
            images=bool(validated_images), allowed_tools=allowed_tools, denied_tools=denied_tools,
            env={**base_env, **routed}, auth_cache=auth_cache,
            route_key=json.dumps({key: value for key, value in routed.items() if key != "ANTHROPIC_MODEL"}, sort_keys=True),
        )
        if reason is None and validated_images:
            try:
                _require_vlm_model(resolved_model)
            except ModelUnavailable:
                reason = "model_capability_unsupported"
        if reason is not None:
            skipped.append(reg.SkippedCandidate(candidate=candidate, reason=reason))
            continue
        # Preflight cleared what's knowable BEFORE the child starts. Spawn it and give it a
        # short window to refuse for quota/rate-limit — the one failure only the provider itself
        # can report, discovered a moment after start rather than before (#181) — before this
        # run commits to this candidate. A refusal here falls through to the next ranked
        # candidate under the SAME criterion, same as any other skip; anything else the child
        # does past this point is that run's outcome, never replayed on another candidate.
        candidate_permission_mode = permission_mode
        if candidate_permission_mode is None:
            candidate_permission_mode = (provider_modes or {}).get(candidate_provider.name)
        # A run named after its agent DEFINITION ("visual-critic") self-describes in the panel;
        # falling back to the provider ("claude") says nothing about what it's for.
        label = name or agent or candidate_provider.name
        # Child inherits our environment MINUS any parent tag, set explicitly below — else a
        # grandchild would inherit its grandparent's id and the tree would be wrong.
        env = {**os.environ, "INTERACT_RUN_ID": run_id, "INTERACT_PARENT_RUN_ID": run_id}
        # The agent's policy is authoritative; caller profiles were rejected above. Its model id
        # can still carry a provider prefix resolved through the operator's allowed routing.
        candidate_routed, candidate_model = resolve_model(candidate.model, dict(os.environ), provider=candidate_provider, weights=weights)
        env.update(candidate_routed)
        if validated_images:
            _require_vlm_model(candidate_model)
        if candidate_provider.name == "claude":
            # This takes precedence over a session or agent-file effort setting.
            env["CLAUDE_CODE_EFFORT_LEVEL"] = effort
        if candidate_provider.name == "claude" and policy.catalog is None:
            definition = candidate_provider.definition_path(agent)
            if definition is None:
                raise ModelUnavailable(f"No installed definition for {agent!r}")
            raw = definition.read_text(encoding="utf-8")
            if not raw.startswith("---\n") or "\n---" not in raw[4:]:
                raise ModelUnavailable(f"Malformed agent definition for {agent!r}")
            frontmatter = raw[4:].split("\n---", 1)[0]
            pin = re.search(r"^model:\s*([^\n]+)$", frontmatter, re.MULTILINE)
            if pin and pin.group(1).strip().strip("\"'") not in {"inherit", candidate_model}:
                raise ModelUnavailable(
                    f"Agent definition {agent!r} has a model pin conflicting with its resolved policy; "
                    "remove the source pin and regenerate instead of bypassing the criterion"
                )
        brief = (
            f"Launch policy: role={agent}; model={candidate_model}; reasoning={effort}; criterion={required_model}.\n"
            f"First progress message: [{agent}] followed by your concrete task; then start immediately.\n\n"
            f"{task}"
        )
        # argv built AFTER the model is decided: used to build first with raw text, so a criterion,
        # a `@profile` or a routed `ollama/x` id reached the binary unresolved while the resolved
        # name went only into the env and run record.
        command_kwargs = dict(
            cwd=cwd, model=candidate_model,
            # Once, never twice: skip the mesh when the provider's own config already registers
            # interact — else the child would carry two registrations of the same server.
            mcp_config=mesh_config(run_id=run_id) if mesh and not already_meshed(candidate_provider.name, cwd=cwd) else None,
            run_id=run_id, agent=agent, permission_mode=candidate_permission_mode,
            allowed_tools=allowed_tools, reasoning=effort,
        )
        if policy.catalog is not None:
            command_kwargs["agent_prompt"] = policy.catalog.role_prompt(agent)
        if denied_tools:
            command_kwargs["denied_tools"] = denied_tools
        if validated_images:
            command_kwargs["image_paths"] = validated_images
        argv = candidate_provider.command(brief, **command_kwargs)
        # Child writes its OWN stream straight to disk. Piping it through a coroutine tied events to
        # the caller's event loop: a caller that spawned and returned lost every event, run then
        # looked HEALTHY (done, exit 0, no cost, no activity) — worse than looking crashed. At OS
        # level the stream survives the caller, or interact, dying.
        sink = reg.open_raw_events(run_id, append=False)
        stderr = reg.open_stderr(run_id, append=False)
        try:
            candidate_process = await asyncio.create_subprocess_exec(
                *argv, cwd=cwd, env=env,
                stdout=sink, stderr=stderr,
                start_new_session=True,  # own process group, so stop() can signal the whole tree
            )
        finally:
            sink.close()  # the child holds its own dup of the fd
            stderr.close()
        quota_reason = await _quota_probe(run_id, candidate_process)
        if quota_reason is not None:
            if candidate_process.returncode is None:
                with suppress(ProcessLookupError):
                    candidate_process.kill()
            with suppress(Exception):
                await candidate_process.wait()
            skipped.append(reg.SkippedCandidate(candidate=candidate, reason=quota_reason))
            continue
        chosen = candidate
        chosen_provider = candidate_provider
        process = candidate_process
        permission_mode = candidate_permission_mode
        model = candidate_model
        break
    if chosen is None or process is None or chosen_provider is None or model is None:
        walked = "\n".join(f"  {s.candidate.provider}/{s.candidate.model}: {s.reason}" for s in skipped)
        raise ModelUnavailable(
            f"No candidate for {agent!r} can start on this machine; the ranked list was:\n{walked}"
        )
    provider = chosen_provider
    registered = reg.register(
        run_id=run_id, pid=process.pid, provider=provider.name, name=label,
        task=task, cwd=cwd, model=model, parent_run_id=parent, agent=agent,
        permission_mode=permission_mode, requested_criterion=required_model,
        mesh_enabled=mesh,
        reasoning=effort,
        candidates=candidates, skipped=tuple(skipped), denied_tools=denied_tools,
        provider_session_id=run_id if provider.name == "claude" else None,
        agent_ref=selected_ref, definition_path=definition_path,
    )
    pump = asyncio.create_task(_reap(run_id, process, registered.lifecycle_token))
    # Keep the panel's copy of the stream current WHILE it works: a running agent can be watched,
    # not only read afterwards.
    asyncio.create_task(
        _mirror_while_alive(run_id, lambda: process.returncode is None)
    )
    return RunHandle(run_id=run_id, process=process, pump=pump,
                     model=model, criterion=required_model, reasoning=effort)
