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
    "prompt",      # what was asked OF the agent — the other half of the conversation
    "spawn",       # this agent started a subagent — the team growing a branch
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
    #: The vendor's tool_use id, carried on BOTH the call and its result. The summarised event is
    #: clipped by design; this is the stable key a viewer uses to pull the FULL input/output for
    #: one call out of the raw stream — prefix-matching breaks on two identical commands.
    tool_id: str = ""
    #: For a "message": which run sent it and which received it. Both sides record the same
    #: exchange, so a sequence view can draw the arrow from either transcript.
    from_run: str | None = None
    to_run: str | None = None
    #: Where this sits in the vendor's raw stream — for a MESSAGE, how many raw lines existed when
    #: it was sent. The vendor writes no timestamps, so this is what lets a message be shown where
    #: it actually happened instead of dumped after every reply it caused.
    raw_index: int | None = None
    # Cost is API-EQUIVALENT: on a subscription run the user is not billed this, they already paid
    # for the plan. The dashboard must label it accordingly rather than implying fresh spend.
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw_type: str = ""
    #: True when a terminal event itself carries the provider's final response (Claude structured
    #: output), rather than only a stop reason.  Media execution must prefer this over an earlier
    #: free-form assistant block.
    final_text: bool = False
    #: When interact FIRST OBSERVED this line, not when the agent produced it — the vendor writes
    #: no timestamp, but we watch the stream, so this is the one clock that is honestly available.
    #: It is what lets a view tell an agent that is working from one that has stopped, order a
    #: conversation, and fire a message animation once at the right moment instead of guessing.
    at: float | None = None

    def summary(self, viewer: str | None = None) -> str:
        """One line for a supervisor row — what this agent is doing right now."""
        if self.kind == "tool":
            return f"using {self.tool}" if self.tool else "using a tool"
        if self.kind == "rate_limit":
            return self.text or "rate limited"
        if self.kind == "message":
            return self._message_summary(viewer)
        if self.kind == "done":
            return "done"
        if self.kind == "error":
            return self.text or "failed"
        return " ".join(self.text.split())[:120]

    def _message_summary(self, viewer: str | None) -> str:
        """A message, from the reading agent's point of view.

        This used to render "→ <to_run>" always, so a message the agent RECEIVED showed an arrow
        pointing at its own id — indistinguishable from the agent-to-agent traffic the panel
        exists to show, while showing none of it. Direction is relative to whoever is reading, and
        the other end is named rather than hashed.
        """
        body = (self.text or "")[:80]
        if not self.to_run:
            return body
        if viewer and self.to_run == viewer:
            return f"← {_who(self.from_run)}: {body}"
        if viewer and self.from_run == viewer:
            return f"→ {_who(self.to_run)}: {body}"
        return f"{_who(self.from_run)} → {_who(self.to_run)}: {body}"


def _who(run_id: str | None) -> str:
    """A run's name, for a reader. "operator" is a person, not a run; an id we cannot resolve
    falls back to its short form rather than a bare empty string.

    Reads the stored record DIRECTLY rather than going through ``list_runs``: that derives each
    run's `last` line, which summarises an event, which asks who it was from — a loop that
    recursed until the stack ran out.
    """
    if not run_id:
        return "?"
    if run_id == "operator":
        return "operator"
    from interact.agents import registry as reg

    run = reg._read_record(run_id)
    return run.name if run is not None else run_id[:8]
