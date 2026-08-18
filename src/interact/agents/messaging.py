"""Delivering a message to a running agent.

Two surfaces send messages: the ``agent_send`` MCP tool, where one agent addresses a teammate, and
the CLI (``interact agents send``), which is how the VS Code panel lets the OPERATOR join the
conversation instead of only watching it. Both must refuse the same things for the same reasons —
an unknown run, one of the user's own editor sessions, a provider that cannot resume — so the
checks live here once rather than being written twice and drifting apart.

Delivery RESUMES the recipient's own session rather than handing it a cold summary: it remembers
everything it has already done, and its reply lands in the same transcript, which is what makes
the exchange readable afterwards and what the sequence view draws its arrows from.
"""

import os

from interact.agents import registry as reg
from interact.agents.providers import provider_for


def check_deliverable(run_id: str):
    """(run, error) — the run a message may be delivered to, or why it may not be.

    Every refusal names the way forward, because the caller may be an agent that cannot ask a
    follow-up question and would otherwise simply stall.
    """
    # Accept the short id the tool itself prints, not only the full uuid.
    resolved = reg.resolve_run_id(run_id)
    run = next((r for r in reg.list_runs(include_foreign=True) if r.run_id == resolved), None)
    if run is None:
        return None, f"ERROR: no agent run {run_id!r}. Use agent_list to see the run ids."
    if getattr(run, "foreign", False):
        return None, (f"ERROR: {run.name!r} is one of your own editor sessions, not an agent "
                      "interact started — interact can watch it, but must not type into it.")
    try:
        prov = provider_for(run.provider)
    except ValueError as e:
        return None, f"ERROR: {e}"
    if not prov.can_resume:
        return None, (f"ERROR: the {run.provider!r} CLI cannot continue a session, so a message "
                      "would arrive with no context. Spawn a new agent with agent_spawn instead.")
    return run, None


def record_exchange(sender: str, run_id: str, message: str) -> str:
    """Record the message on BOTH sides; returns "" on success or the error to report.

    Recorded BEFORE delivery on purpose: a message that reached the agent but appears in no
    history is invisible to the panel and to the sequence view, which is worse than not sending.
    """
    if not reg.record_message(from_run=sender, to_run=run_id, text=message):
        return f"ERROR: could not record the message to {run_id!r}."
    return ""


def sender_id() -> str:
    """Who is speaking: a spawned agent carries its own run id, anyone else is the operator."""
    return os.environ.get("INTERACT_RUN_ID") or "operator"
