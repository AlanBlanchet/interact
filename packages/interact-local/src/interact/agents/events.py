"""One normalised event shape across every agent provider.

Each vendor CLI streams its own JSON dialect; supervisor and dashboard must not learn all of
them. Providers translate into :class:`AgentEvent`, so a Claude run and a Codex run render
identically, and a new provider costs one adapter, not a new UI.

Unrecognised line becomes ``kind="other"`` rather than dropped — a vendor adding an event type
must never make a run look idle.
"""

from collections.abc import Mapping
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

EventKind = Literal[
    "started",     # session is up (id, cwd, tools known)
    "text",        # the agent said something
    "thinking",    # model's own reasoning, kept distinct so a reader can fold it away
    "tool",        # agent used a tool — the live "what is it doing" line
    "tool_result", # what that tool gave back
    "message",     # one agent addressing another — the edge in a sequence/graph view
    "rate_limit",  # the account's pooled limit spoke; a run can die here
    "done",        # terminal: carries the run's cost and token totals
    "error",       # terminal: it failed
    "prompt",      # what was asked OF the agent — the other half of the conversation
    "spawn",       # this agent started a subagent — the team growing a branch
    "interaction", # a provider needs typed human input
    "interaction_resolved", # typed human input was returned to the provider
    "cancelled",   # a turn was interrupted and acknowledged
    "other",       # recognised as valid, not specially handled — never silently dropped
]
InteractionKind = Literal[
    "command_approval", "file_change_approval", "user_input", "permission_approval"
]
InteractionFieldKind = Literal["choice", "text", "boolean"]
EventStatus = Literal[
    "starting",
    "running",
    "waiting",
    "completed",
    "failed",
    "cancelled",
    "provider_failed",
    "interaction_required",
    "unknown",
]
_INTERACTION_KEY = r"^[A-Za-z0-9._:@+-]+$"
_UNSAFE_INTERACTION_KEYS = frozenset({".", "..", "__proto__", "prototype", "constructor"})


class InteractionField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=160, pattern=_INTERACTION_KEY)
    kind: InteractionFieldKind
    label: str = Field(min_length=1, max_length=500)
    required: bool = True
    options: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if self.key in _UNSAFE_INTERACTION_KEYS:
            raise ValueError("interaction field key is unsafe")
        if self.kind == "choice":
            if (
                not self.options
                or len(self.options) != len(set(self.options))
                or any(not option.strip() for option in self.options)
            ):
                raise ValueError("choice fields require unique nonblank options")
        elif self.options:
            raise ValueError("only choice fields may declare options")
        return self


class ConversationInteraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=160)
    kind: InteractionKind
    title: str = Field(min_length=1, max_length=500)
    fields: list[InteractionField] = Field(min_length=1)
    disclosure: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_fields(self) -> Self:
        keys = [field.key for field in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("interaction field keys must be unique")
        return self

    def validate_submission(
        self, values: Mapping[str, object]
    ) -> dict[str, str | bool]:
        fields = {field.key: field for field in self.fields}
        if set(values).difference(fields):
            raise ValueError("interaction submission has unknown fields")
        if any(field.required and field.key not in values for field in self.fields):
            raise ValueError("interaction submission is missing required fields")
        validated: dict[str, str | bool] = {}
        for key, value in values.items():
            field = fields[key]
            if field.kind == "boolean":
                if type(value) is not bool:
                    raise ValueError("interaction boolean field has the wrong value kind")
                validated[key] = value
                continue
            if not isinstance(value, str):
                raise ValueError("interaction string field has the wrong value kind")
            if field.kind == "choice" and value not in field.options:
                raise ValueError("interaction choice is outside its advertised options")
            if field.kind == "text" and not value.strip():
                if field.required:
                    raise ValueError("required interaction text must not be blank")
                continue
            validated[key] = value
        return validated


class AgentEvent(BaseModel):
    """A single thing that happened inside an agent run, provider-agnostic."""

    kind: EventKind
    #: Stable normalized identity. Provider replay is ignored by this key, never by text equality.
    event_id: str = ""
    #: Monotonic within one run after normalization; provider order is retained separately below.
    sequence: int | None = None
    #: Stable provider-side cursor/item identity when one exists.
    provider_cursor: str = ""
    parent_event_id: str | None = None
    turn_id: str | None = None
    #: The discrete run this event describes. For collaboration events this is the child run.
    agent_run_id: str | None = None
    text: str = ""
    session_id: str | None = None
    tool: str | None = None
    #: Compact rendering of the tool's arguments. A view showing "used Bash" without the
    #: command is a status line, not a transcript — this is what makes it readable.
    tool_input: str = ""
    #: Vendor's tool_use id, carried on BOTH the call and its result. Summarised event is
    #: clipped by design; this is the stable key a viewer uses to pull the FULL input/output
    #: for one call out of the raw stream — prefix-matching breaks on two identical commands.
    tool_id: str = ""
    #: For a "message": which run sent it, which received it. Both sides record the same
    #: exchange, so a sequence view can draw the arrow from either transcript.
    from_run: str | None = None
    to_run: str | None = None
    #: Where this sits in the vendor's raw stream — for a MESSAGE, how many raw lines existed
    #: when sent. Vendor writes no timestamps, so this lets a message show where it actually
    #: happened, not dumped after every reply it caused.
    raw_index: int | None = None
    # API-equivalent cost estimates usage VALUE, not billed spend. Charge path and account
    # impact remain separate typed facts; subscription usage may be included, limited, credited, or charged.
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    raw_type: str = ""
    interaction: ConversationInteraction | None = None
    status: EventStatus | None = None
    #: True when a terminal event itself carries the provider's final response (Claude
    #: structured output), not only a stop reason. Media execution must prefer this over an
    #: earlier free-form assistant block.
    final_text: bool = False
    #: When interact FIRST OBSERVED this line, not when the agent produced it — vendor writes
    #: no timestamp, we watch the stream, so this is the one honestly-available clock. Lets a
    #: view tell a working agent from a stopped one, order a conversation, and fire a message
    #: animation once at the right moment instead of guessing.
    at: float | None = None

    def summary(self, viewer: str | None = None) -> str:
        """One line for a supervisor row — what this agent is doing right now."""
        if self.kind == "tool":
            return f"using {self.tool}" if self.tool else "using a tool"
        if self.kind == "rate_limit":
            return self.text or "rate limited"
        if self.kind == "message":
            return self._message_summary(viewer)
        if self.kind == "interaction":
            return "waiting for input"
        if self.kind == "interaction_resolved":
            return "input answered"
        if self.kind == "cancelled":
            return "cancelled"
        if self.kind == "done":
            return "done"
        if self.kind == "error":
            return self.text or "failed"
        return " ".join(self.text.split())[:120]

    def _message_summary(self, viewer: str | None) -> str:
        """A message, from the reading agent's point of view.

        Used to render "→ <to_run>" always, so a message the agent RECEIVED showed an arrow
        pointing at its own id — indistinguishable from the agent-to-agent traffic the panel
        exists to show, while showing none of it. Direction is relative to whoever is reading;
        the other end is named, not hashed.
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
    """A run's name, for a reader. "operator" is a person, not a run; an id we can't resolve
    falls back to its short form, not a bare empty string.

    Reads the stored record DIRECTLY, not through ``list_runs``: that derives each run's
    `last` line, which summarises an event, which asks who it was from — a loop that recursed
    until the stack ran out.
    """
    if not run_id:
        return "?"
    if run_id == "operator":
        return "operator"
    # Deliberately local: registry imports AgentEvent from this module, so a module-level
    # import would create the events<->registry cycle before either side declared its models.
    from interact.agents import registry as reg

    run = reg._read_record(run_id)
    return run.name if run is not None else run_id[:8]
