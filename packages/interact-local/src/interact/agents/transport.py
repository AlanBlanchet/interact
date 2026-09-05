"""Private live-connection contract for conversation routes."""

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from interact.agents.events import AgentEvent
from interact.agents.registry import AgentRun


class _ConversationStart(BaseModel):
    conversation_id: str
    model: str


class _TurnStart(BaseModel):
    turn_id: str


class _TransportUpdate(BaseModel):
    conversation_id: str
    event: AgentEvent
    child: AgentRun | None = None


class TokenCounts(BaseModel):
    """Provider cumulative token cursor with validated arithmetic dimensions."""

    input: int = Field(default=0, ge=0)
    output: int = Field(default=0, ge=0)
    cached_input: int = Field(default=0, ge=0)

    def delta_from(self, previous: "TokenCounts") -> "TokenCounts":
        return TokenCounts(
            input=max(0, self.input - previous.input),
            output=max(0, self.output - previous.output),
            cached_input=max(0, self.cached_input - previous.cached_input),
        )


class _ConversationTransport(BaseModel, ABC):
    """One route-owned connection, including cancellation and deterministic cleanup."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def pid(self) -> int | None:
        return None

    def bind_conversation(self, run: AgentRun) -> None:
        del run

    def has_conversation(self, conversation_id: str) -> bool:
        del conversation_id
        return False

    def has_interaction(self, *, run_id: str, interaction_id: str) -> bool:
        del run_id, interaction_id
        return False

    @abstractmethod
    async def start_conversation(
        self, *, model: str, workspace: Path, instruction: str | None
    ) -> _ConversationStart: ...

    @abstractmethod
    async def resume_conversation(
        self, *, conversation_id: str, model: str, workspace: Path
    ) -> _ConversationStart: ...

    @abstractmethod
    async def start_turn(self, *, conversation_id: str, prompt: str) -> _TurnStart: ...

    @abstractmethod
    async def cancel_turn(self, *, conversation_id: str, turn_id: str) -> None: ...

    @abstractmethod
    async def submit_interaction(
        self, *, run_id: str, interaction_id: str, values: dict[str, str | bool]
    ) -> None: ...

    @abstractmethod
    async def next_update(self) -> _TransportUpdate | None: ...

    @abstractmethod
    async def close(self) -> None: ...


__all__: list[str] = []
