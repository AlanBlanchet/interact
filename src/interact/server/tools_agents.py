"""The agent-mesh MCP tools: spawn a teammate, see the team, read what one is doing, stop it.

These are what make cross-provider teamwork ordinary. A spawned agent gets interact declared as
one of its own MCP servers, so calling ``agent_spawn`` is available to a Claude agent and a Codex
agent alike — they meet on MCP, which is vendor-neutral. An agent spawning an agent is therefore
not a special case; it is one of these calls, and the parent id travels automatically so the team
tree stays connected.
"""

import os

from interact.agents import registry as reg
from interact.agents.providers import PROVIDERS, available_providers, provider_for
from interact.agents.run import run_agent
from interact.server.core import instrumented, mcp


def _fmt(run: reg.AgentRun) -> str:
    bits = [f"[{run.status}]", run.run_id[:8], f"({run.provider})", run.name]
    if run.foreign:
        bits.append("— not started by interact")
    if run.cost_usd is not None:
        bits.append(f"~${run.cost_usd:.4f}")
    if run.last:
        bits.append(f"· {run.last}")
    return "  " + " ".join(bits)


@mcp.tool()
@instrumented
async def agent_spawn(
    task: str,
    provider: str = "claude",
    name: str | None = None,
    model: str | None = None,
    cwd: str | None = None,
) -> str:
    """Start another agent to work alongside you, and return its run id immediately.

    The agent runs as its own process on this machine, using the vendor CLI's own login — you
    never handle a credential. It is given interact as an MCP server, so it can call these same
    tools: it can spawn agents of its own, including from a DIFFERENT provider than yours.

    Returns as soon as the agent is alive, not when it finishes — use agent_list / agent_events
    to watch it, and agent_stop to end it.

    task: what the agent should do — write it as a complete brief; the agent cannot ask you.
    provider: which CLI to run ("claude", "codex"). Only installed ones can be used.
    name: a short role label for the supervisor view (e.g. "reviewer"). Defaults to the provider.
    model: provider-specific model name/alias; omit for that CLI's default.
    cwd: directory to work in; defaults to interact's own working directory.
    """
    try:
        prov = provider_for(provider)
    except ValueError as e:
        return f"ERROR: {e}"
    if not prov.available():
        installed = ", ".join(p.name for p in available_providers()) or "none"
        return (f"ERROR: the {provider!r} CLI is not installed on this machine "
                f"(installed providers: {installed}). interact drives the vendor's own binary, "
                f"so it has to be present and signed in.")
    if not prov.verified:
        # Never let an unexercised adapter look as trustworthy as a tested one.
        pass
    try:
        handle = await run_agent(
            prov, task, name=name or prov.name, cwd=cwd or os.getcwd(), model=model,
        )
    except (OSError, RuntimeError) as e:
        return f"ERROR: could not start the {provider} agent — {e}"
    caveat = f"\nNOTE: the {provider} adapter is {prov.caveat}" if not prov.verified else ""
    return (f"Started {name or prov.name} ({provider}) — run_id={handle.run_id}\n"
            f"Watch it with agent_list, or agent_events(run_id=\"{handle.run_id}\").{caveat}")


@mcp.tool()
@instrumented
async def agent_list(include_foreign: bool = True) -> str:
    """The agent team: every run interact started, what it is doing now, and what it has cost.

    With include_foreign (default), also lists agent sessions interact did NOT start — the user's
    own editor windows — so this reflects the machine's real state rather than only our children.

    Costs are API-EQUIVALENT: on a subscription plan that value is already paid for, it is not
    fresh spend.
    """
    runs = reg.list_runs(include_foreign=include_foreign)
    if not runs:
        installed = ", ".join(p.name for p in available_providers()) or "none installed"
        return f"No agent runs. Providers available here: {installed}."
    lines = [_fmt(r) for r in runs]
    live = sum(1 for r in runs if r.status == "running")
    total = sum(r.cost_usd or 0 for r in runs)
    tree = [f"  {r.run_id[:8]} ← spawned by {r.parent_run_id[:8]}"
            for r in runs if r.parent_run_id]
    out = [f"{len(runs)} agent run(s), {live} running, ~${total:.4f} API-equivalent:", *lines]
    if tree:
        out += ["", "Team tree:", *tree]
    return "\n".join(out)


@mcp.tool()
@instrumented
async def agent_events(run_id: str, limit: int = 20) -> str:
    """What an agent has actually been doing — its most recent events, oldest first."""
    events = reg.read_events(run_id)
    if not events:
        known = {r.run_id for r in reg.list_runs()}
        if run_id not in known:
            return f"ERROR: no agent run {run_id!r}. Use agent_list to see the run ids."
        return f"{run_id[:8]}: no events yet (it may still be starting)."
    shown = events[-max(1, limit):]
    return "\n".join(f"  {e.kind}: {e.summary()}" for e in shown)


@mcp.tool()
@instrumented
async def agent_stop(run_id: str) -> str:
    """Stop a running agent (and the tool processes it spawned)."""
    if reg.stop(run_id):
        return f"Stopped {run_id[:8]}."
    return f"ERROR: no agent run {run_id!r}. Use agent_list to see the run ids."


@mcp.tool()
@instrumented
async def agent_providers() -> str:
    """Which agent CLIs can be spawned on this machine, and which are only declared."""
    lines = []
    for p in PROVIDERS.values():
        state = "available" if p.available() else f"not installed (no {p.binary!r} on PATH)"
        note = f" — {p.caveat}" if not p.verified else ""
        lines.append(f"  {p.name}: {state}{note}")
    return "Agent providers:\n" + "\n".join(lines)
