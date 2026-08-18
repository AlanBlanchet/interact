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
    "thinking",    # the model's own reasoning, kept distinct so a reader can fold it away
    "tool",        # the agent used a tool — the live "what is it doing" line
    "tool_result", # what that tool gave back
    "message",     # one agent addressing another — the edge in a sequence/graph view
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
    #: A compact rendering of the tool's arguments. A conversation view showing "used Bash" without
    #: the command is a status line, not a transcript — this is what makes it readable.
    tool_input: str = ""
    #: For a "message": which run sent it and which received it. Both sides record the same
    #: exchange, so a sequence view can draw the arrow from either transcript.
    from_run: str | None = None
    to_run: str | None = None
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
        if self.kind == "message":
            return f"→ {self.to_run[:8]}: {self.text[:80]}" if self.to_run else self.text[:80]
        if self.kind == "done":
            return "done"
        if self.kind == "error":
            return self.text or "failed"
        return " ".join(self.text.split())[:120]
