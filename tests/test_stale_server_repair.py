"""#144: a Codex session showed no interact tools while `interact status` reported stale MCP
servers. Two gaps let that happen: `kill_stale_servers` claimed "restarted" for a pid it never
re-checked after SIGKILL, and `status` (the command that surfaced the warning) had no `--fix` of
its own — a second, undiscoverable command (`doctor --fix`) was the only repair. Both closed here.
"""

from pathlib import Path

import pytest

from interact import server_registry as sr
from interact.cli import app_commands


@pytest.fixture(autouse=True)
def _runtime_in_tmp(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))


# ── kill_stale_servers: never claim a pid is gone without re-reading it ────────────────────────


def test_a_pid_that_survives_SIGKILL_is_not_reported_killed(monkeypatch):
    """A pid owned by another user (or otherwise unsignalable past SIGTERM) must never be handed
    back as "restarted" — the caller's success message would then be a claim this function cannot
    back with a fresh read (exactly what made #144's "restarted" message false)."""
    monkeypatch.setattr(sr, "stale_servers", lambda: [{"pid": 4242, "version": "0.1.0"}])
    monkeypatch.setattr(sr, "_is_interact_mcp", lambda pid: True)
    monkeypatch.setattr(sr.os, "kill", lambda pid, sig: None)  # both signals "succeed" to send
    monkeypatch.setattr(sr, "_still_running", lambda pid: True)  # yet the pid never actually dies
    monkeypatch.setattr(sr, "_runtime_dir", lambda: Path("/nonexistent"))

    assert sr.kill_stale_servers() == []  # signalled, but never confirmed dead → not returned


def test_a_pid_confirmed_dead_after_SIGKILL_is_reported_killed(monkeypatch):
    sent: list[int] = []

    def fake_still_running(pid):
        return len(sent) < 2  # dies only once SIGKILL (the 2nd signal) has been sent

    monkeypatch.setattr(sr, "stale_servers", lambda: [{"pid": 4242, "version": "0.1.0"}])
    monkeypatch.setattr(sr, "_is_interact_mcp", lambda pid: True)
    monkeypatch.setattr(sr.os, "kill", lambda pid, sig: sent.append(sig))
    monkeypatch.setattr(sr, "_still_running", fake_still_running)
    monkeypatch.setattr(sr, "_runtime_dir", lambda: Path("/nonexistent"))

    assert sr.kill_stale_servers() == [4242]


# ── status/doctor: honest messaging, --fix reachable from status ───────────────────────────────


def test_status_command_accepts_fix(monkeypatch, tmp_path):
    """#144: `status` printed the stale-server warning but had no `--fix` of its own — repairing
    required knowing about a second command. It must be reachable from the command that reports it."""
    monkeypatch.setattr(app_commands, "stale_servers", lambda: [{"pid": 1, "version": "0.1.0", "reason": "version"}])
    monkeypatch.setattr(app_commands, "latest_version", lambda: "9.9.9")
    monkeypatch.setattr(app_commands, "kill_stale_servers", lambda: [1])
    monkeypatch.chdir(tmp_path)

    app_commands.status(fix=True)


def test_fix_reports_confirmed_stop_without_overclaiming_respawn(capsys):
    """The message must not assert every host reconnects automatically (#144's Codex host did
    not) — it states what is known (stopped) and names the manual fallback."""
    orig_stale, orig_latest, orig_kill = (
        app_commands.stale_servers, app_commands.latest_version, app_commands.kill_stale_servers,
    )
    try:
        app_commands.stale_servers = lambda: [{"pid": 1, "version": "0.1.0", "reason": "version"}]
        app_commands.latest_version = lambda: "9.9.9"
        app_commands.kill_stale_servers = lambda: [1]
        app_commands._print_stale_servers(fix=True)
    finally:
        app_commands.stale_servers, app_commands.latest_version, app_commands.kill_stale_servers = (
            orig_stale, orig_latest, orig_kill,
        )
    out = capsys.readouterr().out
    assert "stopped 1 stale MCP server" in out
    assert "reconnect" in out.lower()
    assert "guarantee every host reconnects" in out


def test_fix_names_the_unresolved_pid_and_the_manual_repair(capsys):
    orig_stale, orig_latest, orig_kill = (
        app_commands.stale_servers, app_commands.latest_version, app_commands.kill_stale_servers,
    )
    try:
        app_commands.stale_servers = lambda: [{"pid": 7, "version": "0.1.0", "reason": "version"}]
        app_commands.latest_version = lambda: "9.9.9"
        app_commands.kill_stale_servers = lambda: []  # could not confirm termination
        app_commands._print_stale_servers(fix=True)
    finally:
        app_commands.stale_servers, app_commands.latest_version, app_commands.kill_stale_servers = (
            orig_stale, orig_latest, orig_kill,
        )
    out = capsys.readouterr().out
    assert "pid 7" in out
    assert "v9.9.9" in out
    assert "reconnect" in out.lower() or "restart" in out.lower()
