"""debug_dir: the single, overridable base for interact's logs + debug artifacts."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from interact import debug_utils
from interact.cli import usage
from interact.config import Config


def test_debug_dir_default_is_home_interact_out(monkeypatch):
    # Output lives under ~/.interact/out so the ~/.interact root stays clean (config.env + out/).
    # delenv first: importing interact.runtime loads the developer's OWN ~/.interact/config.env
    # into os.environ, so on a machine that sets INTERACT_DEBUG_DIR this asserted the developer's
    # override instead of the default — green in CI, permanently red locally.
    monkeypatch.delenv("INTERACT_DEBUG_DIR", raising=False)
    assert Config().debug_dir == Path.home() / ".interact" / "out"
    assert Config().usage_log == Path.home() / ".interact" / "out" / "usage.jsonl"


def test_debug_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("INTERACT_DEBUG_DIR", str(tmp_path))
    config = Config()
    assert config.debug_dir == tmp_path
    assert config.usage_log == tmp_path / "usage.jsonl"


@pytest.mark.parametrize(
    "field, attr",
    [
        ("INTERACT_DEBUG_DIR", "debug_dir"),
        ("INTERACT_SCREENSHOT_DUMP_DIR", "screenshot_dump_dir"),
        ("INTERACT_BROWSER_PROFILE_DIR", "browser_profile_dir"),
    ],
)
def test_path_settings_expand_tilde(monkeypatch, field, attr):
    """`~` is expanded once, where the value enters. The TUI and the VS Code settings UI both
    hand these fields free text and advertise `~/...` defaults, so a literal `PosixPath('~/x')`
    silently creates a `./~/x` dir next to wherever the server happened to start."""
    monkeypatch.setenv(field, "~/proj/out")
    assert getattr(Config(), attr) == Path.home() / "proj" / "out"


def test_usage_log_follows_expanded_tilde(monkeypatch):
    monkeypatch.setenv("INTERACT_DEBUG_DIR", "~/.interact/out")
    assert Config().usage_log == Path.home() / ".interact" / "out" / "usage.jsonl"


def test_bare_tilde_is_home(monkeypatch):
    monkeypatch.setenv("INTERACT_DEBUG_DIR", "~")
    assert Config().debug_dir == Path.home()


def test_unexpandable_tilde_gives_a_readable_error(monkeypatch):
    """`~nosuchuser` makes expanduser raise RuntimeError, which pydantic does NOT wrap — without
    the ValueError conversion the server dies with a bare traceback instead of a field error."""
    monkeypatch.setenv("INTERACT_DEBUG_DIR", "~nosuchuser12345/out")
    with pytest.raises(ValidationError, match="cannot expand"):
        Config()


def test_dump_dir_precedence(monkeypatch, tmp_path):
    # per-call arg > explicit screenshot_dump_dir > debug_dir base
    monkeypatch.setattr(debug_utils.config, "screenshot_dump_dir", None)
    monkeypatch.setattr(debug_utils.config, "debug_dir", tmp_path)
    assert debug_utils.Debug.dump_dir(None) == tmp_path
    assert debug_utils.Debug.dump_dir("out/claude") == tmp_path / "out" / "claude"

    monkeypatch.setattr(debug_utils.config, "screenshot_dump_dir", tmp_path / "shots")
    assert debug_utils.Debug.dump_dir(None) == tmp_path / "shots"


def test_dump_dir_expands_tilde(monkeypatch, tmp_path):
    """The per-call `debug_dir` tool arg is the same boundary as the env var — an agent passing
    `~/shots` must not get a literal `./~/shots` next to the server's cwd."""
    monkeypatch.setattr(debug_utils.config, "debug_dir", tmp_path / "artifacts")
    assert debug_utils.Debug.dump_dir("~/shots") == Path.home() / "shots"
    assert debug_utils.Debug.dump_dir("out/claude") == tmp_path / "artifacts/out/claude"


def test_usage_default_log_follows_debug_dir(monkeypatch, tmp_path):
    from interact.runtime import config as runtime_config

    monkeypatch.setattr(runtime_config, "debug_dir", tmp_path)
    assert usage.default_log_path() == tmp_path / "usage.jsonl"
