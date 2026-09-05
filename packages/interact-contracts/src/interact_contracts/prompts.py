"""Typed wire contracts shared by local clients and the private prompt service."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

_PART = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class PromptKey(BaseModel):
    """Stable prompt identity independent of revisions and publication channels."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    namespace: str
    slug: str

    @model_validator(mode="after")
    def validate_parts(self) -> "PromptKey":
        if not _PART.fullmatch(self.namespace) or not _PART.fullmatch(self.slug):
            raise ValueError("prompt namespace and slug must be lowercase kebab-case")
        return self


class PromptRevision(BaseModel):
    """Immutable prompt content and its verifiable publication provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    key: PromptKey
    revision: UUID
    parent_digest: str | None = None
    digest: str
    content: str
    source_commit: str
    created_at: datetime

    @model_validator(mode="after")
    def verify_digest(self) -> "PromptRevision":
        if self.parent_digest is not None and not _DIGEST.fullmatch(self.parent_digest):
            raise ValueError("parent digest must be lowercase SHA-256")
        if not _DIGEST.fullmatch(self.digest):
            raise ValueError("digest must be lowercase SHA-256")
        if hashlib.sha256(self.content.encode()).hexdigest() != self.digest:
            raise ValueError("prompt content digest does not match")
        return self


class PromptChannelEntry(BaseModel):
    """Compare-and-swap channel pointer to one immutable prompt revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    key: PromptKey
    channel: str
    revision: UUID
    digest: str
    lock_version: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_wire_values(self) -> "PromptChannelEntry":
        if not _PART.fullmatch(self.channel):
            raise ValueError("prompt channel must be lowercase kebab-case")
        if not _DIGEST.fullmatch(self.digest):
            raise ValueError("digest must be lowercase SHA-256")
        return self


class _PromptIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: PromptKey
    channel: str
    digest: str

    @model_validator(mode="after")
    def validate_wire_values(self) -> "PromptExecutionRef":
        if not _PART.fullmatch(self.channel):
            raise ValueError("prompt channel must be lowercase kebab-case")
        if not _DIGEST.fullmatch(self.digest):
            raise ValueError("digest must be lowercase SHA-256")
        return self


class PromptSelection(_PromptIdentity):
    """Untrusted channel and digest requested for server-backed resolution."""


class PromptExecutionRef(_PromptIdentity):
    """Server-verified immutable prompt identity persisted with one execution."""

    revision: UUID


class PromptCatalogPage(BaseModel):
    """One typed, cursor-addressed delta from the prompt catalogue."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    entries: tuple[PromptChannelEntry, ...]
    removed: tuple[PromptKey, ...] = ()
    cursor: str | None = None
    server_timestamp: datetime

    def by_key(self) -> dict[tuple[str, str], PromptChannelEntry]:
        return {(entry.key.namespace, entry.key.slug): entry for entry in self.entries}
