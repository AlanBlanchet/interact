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
from dataclasses import dataclass, field

from interact.agents.profiles import overlay_for, profiles_from
from interact.agents import registry as reg
from interact.agents.providers import AgentProvider


def _interact_command() -> tuple[str, list[str]]:
    """How a spawned agent should launch interact's MCP server. Prefer the installed console
    script; fall back to this very interpreter so a checkout without a console script still
    meshes."""
    exe = shutil.which("interact")
    if exe:
        return exe, ["mcp"]
    return sys.executable, ["-m", "interact", "mcp"]


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
    run_id = str(uuid.uuid4())
    parent = parent_run_id or os.environ.get("INTERACT_PARENT_RUN_ID") or None
    # A run named after its agent DEFINITION ("visual-critic") is self-describing in the panel;
    # falling back to the provider ("claude") tells you nothing about what it is for.
    label = name or agent or provider.name
    argv = provider.command(
        task, cwd=cwd, model=model,
        mcp_config=mesh_config(run_id=run_id) if mesh else None,
        run_id=run_id, agent=agent, permission_mode=permission_mode,
    )
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
