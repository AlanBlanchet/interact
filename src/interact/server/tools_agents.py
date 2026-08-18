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
    agent: str | None = None,
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
    agent: a definition the CLI resolves itself — Claude Code reads ~/.claude/agents/<name>.md —
        so the run IS that agent (e.g. "code-reviewer"), with its own system prompt and tools.
        The run is named after it, which is what makes a team readable at a glance.
    name: a short role label for the supervisor view. Defaults to the agent definition, then to
        the provider — so several runs are not all just called "claude".
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
            prov, task, name=name or agent or prov.name, cwd=cwd or os.getcwd(),
            agent=agent, model=model,
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
    """Which agent CLIs can be spawned here, and which named agents each can resolve.

    The definitions matter as much as the providers: `agent_spawn(agent=...)` runs one of them
    with its own system prompt and tools, and a caller — usually an agent, which cannot ask a
    follow-up question — has no other way to learn the names.
    """
    lines = []
    for p in PROVIDERS.values():
        state = "available" if p.available() else f"not installed (no {p.binary!r} on PATH)"
        note = f" — {p.caveat}" if not p.verified else ""
        lines.append(f"  {p.name}: {state}{note}")
        if definitions := p.agent_definitions():
            lines.append(f"    agents: {', '.join(definitions)}")
    return "Agent providers:\n" + "\n".join(lines)


@mcp.tool()
@instrumented
async def agent_send(run_id: str, message: str, wait: bool = False) -> str:
    """Send a message to another agent — it answers with its full context intact.

    Delivery resumes the recipient's own session rather than handing it a cold summary, so it
    remembers everything it has already done and its reply lands in the same transcript. That is
    what makes the exchange readable afterwards, and what a sequence view draws its arrows from.

    Use it to ask a teammate for something and to answer one. The exchange is recorded on BOTH
    sides, so either agent's history shows it.

    run_id: the agent to address (agent_list shows the ids).
    message: what to say — write it as a complete request; it cannot ask you a follow-up.
    wait: block until it has replied, instead of returning as soon as the message is delivered.
    """
    import asyncio
    import os

    from interact.agents import messaging

    # Shared with `interact agents send`, so the tool and the CLI refuse the same things.
    run, error = messaging.check_deliverable(run_id)
    if error:
        return error
    prov = provider_for(run.provider)
    if error := messaging.record_exchange(messaging.sender_id(), run_id, message):
        return error

    # The reply continues the recipient's OWN transcript, so it is appended to that run's stream.
    argv = prov.resume_command(run_id, message)
    raw = reg.raw_events_path(run_id)
    raw.parent.mkdir(parents=True, exist_ok=True)
    sink = raw.open("ab")  # append: this is another turn of the same conversation
    try:
        process = await asyncio.create_subprocess_exec(
            *argv, cwd=run.cwd or os.getcwd(), stdout=sink,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
        )
    except OSError as e:
        return f"ERROR: could not deliver to {run.name} — {e}"
    finally:
        sink.close()
    if wait:
        await process.wait()
        replies = [e for e in reg.read_events(run_id) if e.kind == "text"]
        answer = replies[-1].text if replies else "(no reply text)"
        return f"{run.name} replied:\n{answer}"
    return (f"Delivered to {run.name} ({run_id[:8]}). It is answering now — "
            f"agent_events(run_id=\"{run_id}\") to read the reply.")
