"""Durable accounting records shared by API and session media transports."""

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import litellm
from pydantic import BaseModel, Field

from interact import runtime
from interact.config import Config
from interact.vision.types import VLMResult

_log = logging.getLogger(__name__)


class UsageEntry(BaseModel):
    """Canonical on-disk media accounting row, owned by its only writer."""

    timestamp: datetime
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    backend: Literal["session", "api", "none"]
    provider: str = Field(min_length=1)
    billing: Literal["session_usage", "metered_api", "none"]
    outcome: Literal["succeeded", "failed", "cancelled"]
    request_id: str | None = None
    session_id: str | None = None
    incremental_cost_usd: float | None = None
    api_equivalent_cost_usd: float | None = None
    cost: float | None = 0.0

def append_usage(log: Path, entry: UsageEntry) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(entry.model_dump_json() + "\n")


def log_api_attempt(
    model: str,
    provider: str,
    response,
    config: Config | None = None,
    *,
    outcome: Literal["succeeded", "failed", "cancelled"] = "succeeded",
) -> float | None:
    """Persist an API dispatch even when usage/cost metadata is absent or the call failed."""
    try:
        usage = (
            response.get("usage")
            if isinstance(response, dict)
            else getattr(response, "usage", None)
        )
        try:
            cost = (
                litellm.completion_cost(completion_response=response)
                if response is not None
                else None
            )
        except Exception:  # noqa: BLE001 — third-party response shapes are not trustworthy
            cost = None
        input_tokens = (
            usage.get("prompt_tokens", usage.get("input_tokens", 0))
            if isinstance(usage, dict)
            else getattr(usage, "prompt_tokens", 0) if usage else 0
        )
        output_tokens = (
            usage.get("completion_tokens", usage.get("output_tokens", 0))
            if isinstance(usage, dict)
            else getattr(usage, "completion_tokens", 0) if usage else 0
        )
        append_usage(
            (config or runtime.config).usage_log,
            UsageEntry(
                timestamp=datetime.now(UTC), model=model, backend="api",
                provider=provider,
                billing="metered_api", outcome=outcome, input_tokens=input_tokens,
                output_tokens=output_tokens, incremental_cost_usd=cost,
                api_equivalent_cost_usd=cost, cost=cost,
            ),
        )
        return cost
    except Exception as exc:  # noqa: BLE001 — usage telemetry must not break a model result
        _log.debug("usage-log write failed (%s)", type(exc).__name__)
        return None


def log_session_attempt(
    result: VLMResult,
    config: Config,
    outcome: Literal["succeeded", "failed", "cancelled"],
) -> None:
    """Record one dispatched CLI turn; prompts, media, errors, and credentials are excluded."""
    try:
        append_usage(
            config.usage_log,
            UsageEntry(
                timestamp=datetime.now(UTC), model=result.model, backend="session",
                provider=result.provider, billing="session_usage", outcome=outcome,
                input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                incremental_cost_usd=None,
                api_equivalent_cost_usd=result.api_equivalent_cost_usd, cost=None,
                request_id=result.request_id, session_id=result.session_id,
            ),
        )
    except Exception as exc:  # noqa: BLE001 — usage telemetry must not break a model result
        _log.debug("session usage-log write failed (%s)", type(exc).__name__)
