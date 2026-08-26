"""Spawn an agent CLI and supervise it: stream its events, persist them, record how it ended.

The child leads its own process group (``start_new_session``), so stopping a run signals the
whole tree — an agent CLI spawns its own tool subprocesses, and killing only the parent leaves
those orphaned. Same reason the sandbox does it (#92).
"""

import asyncio
from contextlib import suppress
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from dataclasses import dataclass, field

from interact.agents.profiles import overlay_for, profiles_from
from interact.agents import registry as reg
from interact.agents.providers import AgentProvider
from interact.criteria import Criteria, CriteriaError, Variables



def resolve_model(
    model: str | None,
    env: dict[str, str],
    available_only: bool = True,
    provider: AgentProvider | None = None,
) -> tuple[dict[str, str], str | None]:
    """Split a model id into (env overlay, what the vendor CLI should be asked for).

    A `provider/name` id says two different things at once: WHERE to send the request, and WHICH
    model to ask for. The CLI only understands the second — hand it `ollama/deepseek-v4-pro:cloud`
    and it cannot resolve anything, which is why a company file that declared exactly that made
    every researcher dispatch die at startup and got reverted with the cause recorded as somebody
    else's configuration. It was ours: only a NAMED profile ever went through this split.

    Anything unrecognised is returned untouched, deliberately: a bare `claude-sonnet-5` means the
    vendor's own endpoint, and guessing an endpoint for an unknown prefix would send the operator's
    credentials somewhere nobody chose.
    """
    if not model:
        return {}, None
    model = _resolve_criteria(model, available_only, env, provider)
    overlay = overlay_for(model, env)
    if not overlay:
        return {}, model
    return overlay, overlay.get("ANTHROPIC_MODEL", model)


def load_policy():
    """The policy file, read fresh. Not cached: the whole point of a criterion is that it
    re-resolves, and a policy edited in the panel must bite on the very next spawn."""
    from interact.agents.policy import Policy

    return Policy.load()


def model_for_agent(agent: str | None) -> str | None:
    """What this agent runs on, per the policy — a profile's criterion, its own criterion, or a
    plain model id. None when the policy does not mention it, which leaves the caller's own
    choice (and ultimately the vendor's default) untouched."""
    if not agent:
        return None
    try:
        return load_policy().criterion_for(agent)
    except Exception:
        return None  # a broken policy must never make an unrelated spawn impossible


def tools_for_agent(agent: str | None) -> list[str]:
    """The tools this agent may use, expanded from its toolsets and fully prefixed."""
    if not agent:
        return []
    try:
        return load_policy().tools_for(agent)
    except Exception:
        return []


def check_provider_active(provider: str) -> None:
    """Refuse to spawn through a provider the operator switched off.

    "we should be able to, from interact, chose if we activate the agents or not for a provider" —
    off means OFF at the one place every spawn passes through, not merely hidden in a picker.
    """
    from interact.agents.policy import policy_path

    try:
        active = load_policy().provider_active(provider)
    except Exception:
        return  # a broken policy disables nothing; it is not a kill switch by accident
    if not active:
        raise RuntimeError(
            f"agents are switched off for {provider!r} in {policy_path()} — "
            f'set {{"providers": {{"{provider}": true}}}} there to use it again'
        )


class ModelUnavailable(RuntimeError):
    """A criterion nothing currently clears. Raised rather than falling back: a criterion that
    quietly resolves to some other model is worse than none, because it looks like it worked."""


def is_criterion(text: str) -> bool:
    """A model CRITERION rather than a model id, told apart by SHAPE: a comparison operator, an
    `and`, or a lone variable name (`cap.vlm`) — no model id is spelled like a variable. The one
    shape test the spawn and the `agents policy` display share, so they cannot disagree."""
    return (
        any(op in text for op in ("<", ">", "="))
        or " and " in text
        or text.strip() in {v.name for v in Variables.all()}
    )


def _resolve_criteria(
    model: str, available_only: bool, env: dict[str, str] | None = None,
    provider: AgentProvider | None = None,
) -> str:
    """A CRITERION where a model id goes.

    "we could say agent: 'MMLU > 0.8' to use a model that has MMLU above a criteria for a
    benchmark... Or also control price". A pin is frozen at the moment it was typed; a criterion
    is re-resolved every spawn, so a better or cheaper model that ships tomorrow is used tomorrow.

    Told apart by SHAPE, not by a flag: a model id has no comparison operator and no spaces, so
    `claude-sonnet-5` is an id and `gui.screenspot > 0.85 and price.in < 10` is a requirement. The
    vendor CLI never learns criteria exist — by the time it is invoked this is a model name.

    With a `provider`, the pool is what THAT vendor CLI can be pointed at (`AgentProvider.can_run`)
    — its own vendor's models through its login, a routed one when its key is here — never the
    cheapest model in the whole catalog handed to a binary that cannot run it.
    """
    if model.startswith("@"):
        # A profile: a NAME for a criterion (`"profiles": {"eyes": "cap.vlm and ..."}`), honoured
        # wherever a model may be named — resolved to its rule here, then read like any criterion.
        model = load_policy().rule(model)
    if not is_criterion(model):
        return model
    try:
        criteria = Criteria.parse(model)
    except CriteriaError as err:
        raise ModelUnavailable(f"{model!r} is not a usable model criterion: {err}") from err
    runnable = (lambda m: provider.can_run(m, env or {})) if provider is not None else None
    chosen = criteria.choose(available_only=available_only, runnable=runnable)
    if chosen is None:
        who = f"model the {provider.name} CLI can run" if provider is not None else "configured model"
        raise ModelUnavailable(
            f"no {who} clears {criteria}:\n{criteria.explain(available_only, runnable)}"
        )
    return provider.model_id_for(chosen) if provider is not None else chosen.id


def _interact_command() -> tuple[str, list[str]]:
    """How a spawned agent should launch interact's MCP server. Prefer the installed console
    script; fall back to this very interpreter so a checkout without a console script still
    meshes."""
    exe = shutil.which("interact")
    if exe:
        return exe, ["mcp"]
    return sys.executable, ["-m", "interact", "mcp"]


def already_meshed(provider: str) -> bool:
    """Whether this provider's OWN configuration already registers interact as an MCP server.

    "activate the agents for the provider, but once (and not twice)... no conflicts." `interact
    install` registers interact in the provider's user-scope config — so handing a spawned child
    `--mcp-config` with a second interact registration doubles the server in that session. The
    mesh exists for machines where the provider has NO interact of its own; where it does,
    attribution still flows, because INTERACT_PARENT_RUN_ID rides the child's process environment
    and the globally-configured server inherits it.

    Reads only; a corrupt or absent config means "not registered" — doubling a server is annoying,
    a spawn that refuses to start over a config file is worse.
    """
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

    This is what makes cross-provider teamwork work with no bespoke protocol: the child is an MCP
    client, interact is an MCP server, so a Claude agent and a Codex agent call the same tools.
    ``INTERACT_PARENT_RUN_ID`` travels with it so anything the child spawns is attributed to it
    and the team tree stays connected.

    It carries NO credential — the child's own CLI authenticates itself.
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

    async def wait(self) -> int:
        """Block until the run has ended AND every event has been persisted."""
        await self.pump
        return await self.process.wait()


async def _mirror_while_alive(run_id: str, alive, *, interval: float = 1.0) -> None:
    """Keep the NORMALISED stream current while a run works.

    The child writes only the vendor's RAW stream; the provider-agnostic copy the VS Code panel
    reads is produced by ``read_events``. Nothing called it during a run, so a working agent
    looked idle for its whole life and "watch the responses arrive" was impossible.

    Cheap by construction: ``read_events`` rewrites the mirror only when the content actually
    changed, so a quiet run costs a parse and no write. Failures are swallowed — this runs beside
    a live agent, and a transient read must never take its stream down.
    """
    while alive():
        try:
            reg.read_events(run_id)
        except Exception:
            pass
        await asyncio.sleep(interval)
    with suppress(Exception):
        reg.read_events(run_id)  # one last pass so the final turn is not left unmirrored


async def _mirror_running_runs(alive, *, interval: float = 1.0) -> None:
    """Keep EVERY live run's normalised stream current, not only the ones this process spawned.

    `agents spawn` detaches, so the pump started beside a run dies with its parent. The child keeps
    writing its raw stream, but the copy the VS Code panel reads is produced on demand — so a
    detached agent's activity froze on screen until something happened to call Python. This runs
    in the MCP server, the process alive whenever the user is working.

    Settled runs are skipped (nothing changes, so re-reading is waste) and so are sessions interact
    did not start: reading someone else's transcript is not ours to do.
    """
    while alive():
        try:
            # `foreign` is checked as well as excluded by the query: reading someone else's
            # transcript is not ours to do, and that guarantee should not rest on one argument.
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


async def _reap(run_id: str, process) -> None:
    """Record how the run ended. The EVENTS do not depend on this coroutine — the child writes
    them to disk itself (see :func:`run_agent`) — so losing this task costs an exit code, never
    the stream."""
    try:
        code = await process.wait()
    except Exception:
        return
    reg.finish(run_id, exit_code=code)


async def run_agent(
    provider: AgentProvider,
    task: str,
    *,
    name: str | None = None,
    cwd: str,
    agent: str | None = None,
    model: str | None = None,
    parent_run_id: str | None = None,
    permission_mode: str | None = None,
    profile: str | None = None,
    mesh: bool = True,
) -> RunHandle:
    """Spawn an agent run and register it, returning as soon as it is alive.

    Returns immediately by design: the supervisor's whole value is watching work in flight, so
    the run must be visible in the registry before it finishes.

    ``profile`` names one of the OPERATOR's own profiles (``INTERACT_PROFILE_*`` in config), which
    decides what this agent runs on — so the critic can sit on a local model while the reviewer
    stays on a frontier one. It resolves through :mod:`interact.agents.profiles` to a fixed,
    allow-listed overlay; a caller cannot hand over an environment, because a model that can set
    ``LD_PRELOAD`` or ``PATH`` on the process it spawns has escaped every other guard here.

    ``parent_run_id`` defaults to ``INTERACT_PARENT_RUN_ID`` — set on a spawned agent's own MCP
    server by :func:`mesh_config` — so an agent that spawns an agent produces a connected tree
    without anyone passing the id by hand.
    """
    if not provider.available():
        raise RuntimeError(
            f"the {provider.name!r} CLI is not installed (looked for {provider.binary!r} on PATH). "
            "interact drives the vendor's own binary with your own login; install and sign into "
            "it first."
        )
    check_provider_active(provider.name)
    run_id = str(uuid.uuid4())
    parent = parent_run_id or os.environ.get("INTERACT_PARENT_RUN_ID") or None
    # The policy speaks for an agent that did not bring its own model: a profile is written once
    # and worn by many, which is the whole reason it exists.
    model = model or model_for_agent(agent)
    # A run named after its agent DEFINITION ("visual-critic") is self-describing in the panel;
    # falling back to the provider ("claude") tells you nothing about what it is for.
    label = name or agent or provider.name
    # The child inherits our environment MINUS any parent tag, which we set explicitly below —
    # otherwise a grandchild would inherit its grandparent's id and the tree would be wrong.
    env = {**os.environ, "INTERACT_RUN_ID": run_id, "INTERACT_PARENT_RUN_ID": run_id}
    # What this agent runs on, decided BEFORE the call. The overlay is allow-listed by construction
    # (see profiles.ALLOWED_ENV) — an unknown profile name is refused rather than silently ignored,
    # because "it quietly ran on the wrong model" is the failure nobody notices.
    if profile:
        known = profiles_from(dict(os.environ))
        if profile not in known:
            raise RuntimeError(
                f"no such profile {profile!r}. Define it in ~/.interact/config.env as "
                f"INTERACT_PROFILE_{profile.upper()}=<provider>/<model>; "
                f"known: {', '.join(sorted(known)) or 'none'}"
            )
        overlay = overlay_for(known[profile], dict(os.environ))
        env.update(overlay)
        model = model or overlay.get("ANTHROPIC_MODEL")
    else:
        # No named profile, but the model id may still carry its own routing — a company file or the
        # panel can declare `ollama/deepseek-v4-pro:cloud` directly.
        routed, model = resolve_model(model, dict(os.environ), provider=provider)
        env.update(routed)
    # The argv is built AFTER the model is decided: it used to be built first, with the raw text,
    # so a criterion, a `@profile` or a routed `ollama/x` id reached the binary unresolved while
    # the resolved name went only into the env and the run record.
    argv = provider.command(
        task, cwd=cwd, model=model,
        # Once, never twice: skip the mesh when the provider's own config already registers
        # interact — the child would otherwise carry two registrations of the same server.
        mcp_config=mesh_config(run_id=run_id) if mesh and not already_meshed(provider.name) else None,
        run_id=run_id, agent=agent, permission_mode=permission_mode,
        allowed_tools=tools_for_agent(agent),
    )
    # The child writes its OWN stream straight to disk. Piping it through a coroutine tied the
    # events to the caller's event loop: a caller that spawned and returned lost every event, and
    # the run then looked HEALTHY — status done, exit 0, no cost, no activity — which is worse
    # than looking crashed. At the OS level the stream survives the caller, and interact dying.
    raw_path = reg.raw_events_path(run_id)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    sink = raw_path.open("wb")
    try:
        process = await asyncio.create_subprocess_exec(
            *argv, cwd=cwd, env=env,
            stdout=sink, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,  # own process group, so stop() can signal the whole tree
        )
    finally:
        sink.close()  # the child holds its own dup of the fd
    reg.register(run_id=run_id, pid=process.pid, provider=provider.name, name=label,
                 task=task, cwd=cwd, model=model, parent_run_id=parent, agent=agent,
                 permission_mode=permission_mode)
    pump = asyncio.create_task(_reap(run_id, process))
    # Keep the panel's copy of the stream current WHILE it works, so a running agent can be
    # watched rather than only read afterwards.
    asyncio.create_task(
        _mirror_while_alive(run_id, lambda: process.returncode is None)
    )
    return RunHandle(run_id=run_id, process=process, pump=pump)
