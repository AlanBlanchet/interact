"""~/.interact/config.env is the live source of truth: a long-running server reflects file
edits on the next tool call (config.refresh()), and clearing a setting in the file reverts it —
no stale environment snapshot. This is the bug where a TUI/file model change didn't reach the
already-running MCP server."""

import os

import pytest

from interact.config import UserConfig
from interact.runtime import _LiveConfig, config


@pytest.fixture
def live_config(tmp_path, monkeypatch):
    monkeypatch.setattr(UserConfig, "PATH", tmp_path / "config.env")
    # Start from a clean environment for the settings under test.
    for name in ("INTERACT_COMPONENT_MODEL", "INTERACT_IMAGE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    config.clear_overrides()  # isolate from any override leaked by an earlier test
    return config


def test_spawned_interact_env_survives_file_overlay_and_removal(
    tmp_path, monkeypatch, caplog
) -> None:
    """VS settings arrive in the child environment, then config.env temporarily overrides them."""
    monkeypatch.setattr(UserConfig, "PATH", tmp_path / "config.env")
    monkeypatch.setenv("INTERACT_MEDIA_BACKEND", "session")
    monkeypatch.delenv(
        "INTERACT_MEDIA_SESSION_NO_EXTRA_USAGE_CONFIRMED_FOR", raising=False
    )
    monkeypatch.delenv("INTERACT_CLAUDE_MEDIA_MODEL", raising=False)
    monkeypatch.setattr(UserConfig, "_process_interact_env", None, raising=False)

    UserConfig.apply()
    live = _LiveConfig()
    assert live.refresh().media_backend == "session"
    assert live.media_session_no_extra_usage_confirmed_for == ()

    try:
        UserConfig.set("media.backend", "auto")
        UserConfig.set(
            "INTERACT_MEDIA_SESSION_NO_EXTRA_USAGE_CONFIRMED_FOR", "claude"
        )
        UserConfig.set("INTERACT_CLAUDE_MEDIA_MODEL", "must-not-appear-in-logs")
        assert live.refresh().media_backend == "auto"
        assert live.media_session_no_extra_usage_confirmed_for == ("claude",)
        assert live.claude_media_model == "must-not-appear-in-logs"
    finally:
        UserConfig.unset("media.backend")
        UserConfig.unset("INTERACT_MEDIA_SESSION_NO_EXTRA_USAGE_CONFIRMED_FOR")
        UserConfig.unset("INTERACT_CLAUDE_MEDIA_MODEL")

    assert live.refresh().media_backend == "session"
    assert live.media_session_no_extra_usage_confirmed_for == ()
    assert live.claude_media_model == ""
    assert "INTERACT_CLAUDE_MEDIA_MODEL" not in os.environ
    assert "must-not-appear-in-logs" not in caplog.text


def test_file_edit_is_picked_up_and_clearing_reverts(live_config):
    # No pin → the configured model is empty (resolves to the auto default downstream).
    assert live_config.refresh().component_model == ""

    # A file edit (what the TUI / hand-edit does) reaches a running server on the next refresh.
    UserConfig.set("component.model", "zai/glm-4.5v")
    assert live_config.refresh().component_model == "zai/glm-4.5v"

    # Clearing it in the file actually takes effect — the stale env var is dropped, not kept.
    UserConfig.unset("component.model")
    assert live_config.refresh().component_model == ""


def test_in_process_override_survives_refresh(live_config):
    # An explicit in-process set (tests, screenshot_dump_dir) wins over the file and persists
    # across refreshes — and is visible to methods that read self.field (model_for).
    live_config.component_model = "test/override"
    assert live_config.model_for("component") == "test/override"
    UserConfig.set("component.model", "zai/glm-4.5v")
    live_config.refresh()
    assert live_config.model_for("component") == "test/override"  # override still wins


def test_cleared_provider_key_is_dropped_from_env_not_leaked(live_config, monkeypatch):
    """A provider *_API_KEY the FILE defines is applied to os.environ, and when cleared from the
    file it is DROPPED from os.environ too — else a long-lived server keeps using it and it leaks
    into sandbox child processes. A key from the real shell env (never file-defined) is untouched."""
    import os

    monkeypatch.delenv("NOVITA_API_KEY", raising=False)
    UserConfig.set("NOVITA_API_KEY", "file-owned-value")
    live_config.refresh()
    assert os.environ.get("NOVITA_API_KEY") == "file-owned-value"

    UserConfig.unset("NOVITA_API_KEY")
    live_config.refresh()
    assert "NOVITA_API_KEY" not in os.environ  # cleared in the file → gone from env, no leak

    monkeypatch.setenv("COHERE_API_KEY", "from-the-shell")  # never file-defined
    live_config.refresh()
    assert os.environ.get("COHERE_API_KEY") == "from-the-shell"  # not file-owned → left alone


@pytest.fixture
def temp_cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(UserConfig, "PATH", tmp_path / "config.env")
    return UserConfig.PATH


@pytest.mark.parametrize(
    "env_name",
    ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AZURE_API_BASE", "AZURE_API_VERSION",
     "VERTEXAI_LOCATION", "VERTEXAI_PROJECT", "OPENAI_API_KEY"],
)
def test_env_shaped_key_stored_verbatim(temp_cfg, env_name):
    """A provider cred whose env name doesn't end in _API_KEY (AWS / Azure / Vertex) must be
    stored under its REAL env name, not a dead ``INTERACT_*`` alias nothing reads — the API-Keys
    tab bug where a set key still read 'unset' and the provider never authenticated."""
    assert UserConfig.normalize_key(env_name) == env_name
    UserConfig.set(env_name, "secret-val")
    assert UserConfig.read()[env_name] == "secret-val"
    assert f"INTERACT_{env_name}" not in UserConfig.read()


@pytest.mark.parametrize(
    "friendly,expected",
    [("image.model", "INTERACT_IMAGE_MODEL"),
     ("desktop.target", "INTERACT_DESKTOP_TARGET"),
     ("desktop-target", "INTERACT_DESKTOP_TARGET"),
     ("desktop.nestedHeadless", "INTERACT_DESKTOP_NESTEDHEADLESS"),
     ("INTERACT_DEBUG_DIR", "INTERACT_DEBUG_DIR")],
)
def test_friendly_keys_still_map_to_interact_env(friendly, expected):
    """The verbatim guard must NOT regress the friendly dotted/dashed setting keys."""
    assert UserConfig.normalize_key(friendly) == expected
