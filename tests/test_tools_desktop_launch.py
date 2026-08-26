"""launch_app command handling at the tool level: a shell-syntax command (`cd X && app`) runs via
bash instead of failing exec with `[Errno 2] No such file or directory: 'cd'`, `cwd=` starts the
app in a project directory directly, and a `VAR=value app` prefix (#117) becomes the launch's
environment instead of being exec'd as a literal program named `VAR=value`."""

import asyncio
from pathlib import Path

import pytest

import interact.server as srv


class _FakeBackend:
    display = ":88"

    def __init__(self):
        self.spawned: list[tuple[list[str], str | None, dict[str, str] | None]] = []
        self.spawn_error: OSError | None = None  # raised by spawn instead of launching

    def spawn(self, argv, cwd=None, env=None):
        if self.spawn_error is not None:
            raise self.spawn_error
        self.spawned.append((list(argv), cwd, env))
        return type("P", (), {"poll": lambda self: None, "returncode": None})()

    def list_windows(self):
        return [(7, "App")]


@pytest.fixture
def fake_backend(monkeypatch):
    fb = _FakeBackend()
    monkeypatch.setattr(srv.sandbox, "_get_sandbox", lambda size=None: fb)
    monkeypatch.setattr(srv.targets, "_desktop_unsupported", lambda: None)
    return fb


def test_cd_command_runs_via_shell(fake_backend):
    cmd = "cd /home/me/proj && exec uv run app"
    out = asyncio.run(srv.launch_app(cmd, wait=1))
    assert "ERROR" not in out and "No such file" not in out
    argv, _, _ = fake_backend.spawned[0]
    assert argv[:2] == ["bash", "-c"] and argv[2] == cmd


def test_cwd_param_spawns_in_that_directory(fake_backend, tmp_path):
    out = asyncio.run(srv.launch_app("uv run app", wait=1, cwd=str(tmp_path)))
    assert "ERROR" not in out
    assert fake_backend.spawned == [(["uv", "run", "app"], str(tmp_path), None)]


def test_missing_cwd_is_a_clear_error(fake_backend, tmp_path):
    out = asyncio.run(srv.launch_app("app", cwd=str(tmp_path / "nope")))
    assert out.startswith("ERROR") and "cwd" in out
    assert fake_backend.spawned == []  # never spawned into a wrong directory


# ── `VAR=value app` (#117) ───────────────────────────────────────────────────────────────────
# Agents write `FOO=bar app` as naturally as `cd X && app`. No shell marker matches it, so the
# shlex argv was exec'd verbatim: Popen(["FOO=bar", "app"]) → FileNotFoundError: 'FOO=bar',
# reaching the agent as FastMCP's generic exception text, not one of this module's `ERROR:` strings.


def test_leading_assignments_become_the_launch_env(fake_backend):
    out = asyncio.run(srv.launch_app("FOO=bar BAZ=1 app --x", wait=1))
    assert "ERROR" not in out
    assert fake_backend.spawned == [(["app", "--x"], None, {"FOO": "bar", "BAZ": "1"})]


def test_assignments_keep_the_launch_rewrites(fake_backend, tmp_path, monkeypatch):
    """The prefix must NOT reroute the command through bash: staying on the exec path is what keeps
    the sandbox rewrites (an editor's isolated profile here, Flutter's software-GL flag) — a
    `bash -c` launch bypasses them."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    out = asyncio.run(srv.launch_app("FOO=bar code /tmp/p", wait=1))
    assert "ERROR" not in out
    argv, _, env = fake_backend.spawned[0]
    assert argv[:2] == ["code", "/tmp/p"] and "--user-data-dir" in " ".join(argv)
    assert env == {"FOO": "bar"}


def test_an_env_binary_prefix_is_left_to_env_itself(fake_backend):
    """`env LANG=C xterm` names a real program — the `env` binary applies the assignment, so the
    argv reaches exec whole and no per-launch environment is built."""
    asyncio.run(srv.launch_app("env LANG=C xterm", wait=1))
    assert fake_backend.spawned == [(["env", "LANG=C", "xterm"], None, None)]


def test_assignments_without_a_command_are_a_clear_error(fake_backend):
    out = asyncio.run(srv.launch_app("FOO=bar", wait=1))
    assert out.startswith("ERROR") and "no command" in out
    assert fake_backend.spawned == []


@pytest.mark.parametrize(
    ("error", "phrase"),
    [
        (FileNotFoundError(2, "No such file or directory", "app"), "sandbox PATH"),
        (PermissionError(13, "Permission denied", "app"), "chmod +x"),
    ],
)
def test_a_failed_exec_is_a_guided_error_naming_the_real_command(fake_backend, error, phrase):
    """A program exec cannot start returns a guided `ERROR:` naming what was actually tried — `app`,
    the real command, now that the `FOO=bar` prefix is consumed rather than exec'd."""
    fake_backend.spawn_error = error
    out = asyncio.run(srv.launch_app("FOO=bar app --x", wait=1))
    assert out.startswith("ERROR") and "'app'" in out and phrase in out
