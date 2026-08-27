"""Focused contracts for stable media responses and canonical accounting ownership."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from interact.agents.providers import ClaudeCodeProvider, CodexProvider
from interact.server import vlm
from interact.vision.types import VLMResult
from interact.vision.usage import UsageEntry


@pytest.mark.asyncio
async def test_media_response_has_one_stable_shape(monkeypatch) -> None:
    async def analyze(*args, **kwargs) -> VLMResult:
        return VLMResult(
            text="visible", elapsed=0.1, model="", backend="session", provider="claude"
        )

    monkeypatch.setattr(vlm, "_vlm", analyze)
    response = await vlm._media_response(b"image", "context", "describe")
    assert response.text.startswith("visible")
    assert response.result is not None and response.result.provider == "claude"


def test_default_session_diagnostic_names_actual_provider() -> None:
    rendered = vlm._fmt_timing(
        VLMResult(text="ok", elapsed=0, backend="session", provider="claude", model="")
    )
    assert "claude subscription session (provider default)" in rendered.lower()


def test_usage_entry_is_owned_by_the_writer_and_serializes_one_schema() -> None:
    entry = UsageEntry(
        timestamp=datetime.now(UTC), model="claude default", backend="session",
        provider="claude", billing="session_usage", outcome="failed", cost=None,
    )
    payload = entry.model_dump(mode="json")
    assert payload["provider"] == "claude" and payload["cost"] is None
    assert "request_id" in payload and "session_id" in payload


def test_claude_media_argv_flags_exist_in_installed_help() -> None:
    provider = ClaudeCodeProvider()
    if not provider.available():
        pytest.skip("Claude CLI is not installed")
    help_text = provider.media_help_text()
    argv = provider.media_command(
        cwd=Path.cwd(), model="sonnet", media_paths=[Path("staged image.png")],
        schema_path=Path("schema.json"), schema_json='{"type":"object"}',
        mcp_config=Path("mcp.json"), settings_path=Path("settings.json"),
    )
    assert all(flag in help_text for flag in argv if flag.startswith("--"))


def test_codex_has_no_media_execution_surface() -> None:
    assert "media_command" not in CodexProvider.__dict__
    assert "media_isolation_args" not in CodexProvider.__dict__
    assert "media_model_field" not in CodexProvider.__dict__
    assert "no_extra_usage_guidance" not in CodexProvider.__dict__
    provider = CodexProvider()
    assert not hasattr(provider, "media_command")
    assert not hasattr(provider, "run_media_process")
