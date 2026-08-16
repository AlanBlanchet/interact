"""One normalised event shape across every agent provider.

Each vendor CLI streams its own JSON dialect; the supervisor and the dashboard must not learn all
of them. Providers translate into :class:`AgentEvent`, so a Claude run and a Codex run render
identically and a new provider costs one adapter, not a new UI.

An unrecognised line becomes ``kind="other"`` rather than being dropped — a vendor adding an
event type must never make a run look idle.
"""

from typing import Literal

from pydantic import BaseModel

EventKind = Literal[
    "started",     # the session is up (its id, cwd and tools are known)
    "text",        # the agent said something
    "tool",        # the agent used a tool — the live "what is it doing" line
    "rate_limit",  # the account's pooled limit spoke; a run can die here
    "done",        # terminal: carries the run's cost and token totals
    "error",       # terminal: it failed
    "other",       # recognised as valid, not specially handled — never silently dropped
]


class AgentEvent(BaseModel):
    """A single thing that happened inside an agent run, provider-agnostic."""

    kind: EventKind
    text: str = ""
    session_id: str | None = None
    tool: str | None = None
    # Cost is API-EQUIVALENT: on a subscription run the user is not billed this, they already paid
    # for the plan. The dashboard must label it accordingly rather than implying fresh spend.
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw_type: str = ""

    def summary(self) -> str:
        """One line for a supervisor row — what this agent is doing right now."""
        if self.kind == "tool":
            return f"using {self.tool}" if self.tool else "using a tool"
        if self.kind == "rate_limit":
            return self.text or "rate limited"
        if self.kind == "done":
            return "done"
        if self.kind == "error":
            return self.text or "failed"
        return " ".join(self.text.split())[:120]
