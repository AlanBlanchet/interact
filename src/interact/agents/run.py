"""Spawn an agent CLI and supervise it: stream its events, persist them, record how it ended.

The child leads its own process group (``start_new_session``), so stopping a run signals the
whole tree — an agent CLI spawns its own tool subprocesses, and killing only the parent leaves
those orphaned. Same reason the sandbox does it (#92).
"""

import asyncio
import json
import os
import shutil
import sys
import uuid
from dataclasses import dataclass, field

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


async def _pump(run_id: str, provider: AgentProvider, process) -> None:
    """Read the child's stdout line by line, normalise, persist. Runs for the child's lifetime."""
    try:
        assert process.stdout is not None
        async for raw in process.stdout:
            line = raw.decode("utf-8", "replace")
            event = provider.parse(line)
            if event is not None:
                reg.append_event(run_id, event)
    except Exception:  # a decode/parse fault must not leave the child unreaped
        pass
    finally:
        code = await process.wait()
        reg.finish(run_id, exit_code=code)


async def run_agent(
    provider: AgentProvider,
    task: str,
    *,
    name: str,
    cwd: str,
    model: str | None = None,
    parent_run_id: str | None = None,
    mesh: bool = True,
) -> RunHandle:
    """Spawn an agent run and register it, returning as soon as it is alive.

    Returns immediately by design: the supervisor's whole value is watching work in flight, so
    the run must be visible in the registry before it finishes.

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
    argv = provider.command(
        task, cwd=cwd, model=model,
        mcp_config=mesh_config(run_id=run_id) if mesh else None,
        run_id=run_id,
    )
    # The child inherits our environment MINUS any parent tag, which we set explicitly below —
    # otherwise a grandchild would inherit its grandparent's id and the tree would be wrong.
    env = {**os.environ, "INTERACT_RUN_ID": run_id, "INTERACT_PARENT_RUN_ID": run_id}
    process = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,  # own process group, so stop() can signal the whole tree
    )
    reg.register(run_id=run_id, pid=process.pid, provider=provider.name, name=name,
                 task=task, cwd=cwd, model=model, parent_run_id=parent)
    pump = asyncio.create_task(_pump(run_id, provider, process))
    return RunHandle(run_id=run_id, process=process, pump=pump)
