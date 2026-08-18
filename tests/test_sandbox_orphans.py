"""Leaked Xephyr displays.

Two complaints, one cause. Every interact MCP server owns its own sandbox, so several servers
(one per editor window) means several Xephyr windows — "2 at the start". And when a server dies
without tearing down, its X server survives as an orphan: reparented to init, invisible to the
owner that could have cleaned it up, sitting on the user's screen until they kill it by hand.

An orphan is identifiable: it is OUR X server (our own flags), and its parent is gone.
"""

import os
import signal

import pytest

from interact.desktop import orphans


@pytest.fixture(autouse=True)
def _never_signal_a_real_process(monkeypatch):
    """No test in this module may signal or enumerate a REAL process.

    This module's whole subject is code that kills things, and its fixtures carry a real display
    number (":99"), so a test that patches only part of the path reaches live processes through
    the rest of it — one such test was collecting the pids of the running sandbox. Cutting both
    sinks here makes that impossible rather than merely unlikely; a test needing specific
    behaviour overrides these itself.
    """
    monkeypatch.setattr(orphans.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(orphans, "_all_pids", lambda: [])
    yield


def _proc(pid, ppid, cmdline):
    return orphans.XServer(pid=pid, ppid=ppid, cmdline=cmdline)


_OURS = "Xephyr :99 -screen 1280x800 -br -ac -noreset -no-host-grab"


def test_an_orphan_is_ours_and_has_lost_its_parent():
    assert orphans.is_orphan(_proc(10, 1, _OURS)) is True


def test_a_live_parent_means_it_is_still_owned():
    # Someone is still using it — killing this would destroy a running session's display.
    assert orphans.is_orphan(_proc(10, 4242, _OURS)) is False


@pytest.mark.parametrize(
    "cmdline",
    [
        "Xephyr :50 -screen 800x600",              # a user's own Xephyr, not ours
        "Xvfb :77 -screen 0 1280x1024x24",         # not even the same server
        "/usr/bin/some-other-thing --noreset",
    ],
)
def test_a_foreign_x_server_is_never_touched(cmdline):
    # Killing a display we did not create is destroying someone else's work.
    assert orphans.is_orphan(_proc(10, 1, cmdline)) is False


def test_reaping_kills_only_the_orphans(monkeypatch):
    listed = [
        _proc(1, 1, _OURS),          # orphan
        _proc(2, 999, _OURS),        # owned
        _proc(3, 1, "Xephyr :50 -screen 800x600"),  # foreign
    ]
    killed: list[int] = []
    monkeypatch.setattr(orphans, "_list_x_servers", lambda: listed)
    monkeypatch.setattr(orphans, "_terminate", lambda pid: killed.append(pid) or True)
    assert orphans.reap_orphaned_displays() == [1]
    assert killed == [1]


def test_reaping_never_raises_when_nothing_can_be_listed(monkeypatch):
    # Cleanup is best-effort: it must never break the launch it runs before.
    monkeypatch.setattr(orphans, "_list_x_servers", lambda: (_ for _ in ()).throw(OSError("nope")))
    assert orphans.reap_orphaned_displays() == []


def test_a_process_that_merely_mentions_xephyr_is_not_an_x_server(monkeypatch):
    """Caught live: matching any command line CONTAINING "Xephyr" matched the very shell command
    that was hunting for orphans. Same self-match family as `pkill -f` on your own pattern — and
    here it would have sent SIGTERM to an innocent process."""
    ps_output = (
        "  10     1 Xephyr :99 -screen 1280x800 -br -ac -noreset -no-host-grab\n"
        "  11     1 python -c print('Xephyr -noreset -no-host-grab')\n"
        "  12     1 grep Xephyr -noreset -no-host-grab\n"
    )

    class _Done:
        stdout = ps_output

    monkeypatch.setattr(orphans.subprocess, "run", lambda *a, **k: _Done())
    found = orphans._list_x_servers()
    assert [s.pid for s in found] == [10], "matched something that only talks about Xephyr"


def test_an_orphan_adopted_by_systemd_is_still_an_orphan(monkeypatch):
    """Observed on the real machine: a leaked Xephyr's parent was `systemd --user`, not pid 1.
    Modern Linux user sessions register systemd as a child-subreaper, so orphans are adopted by
    it — a rule that only recognises pid 1 never fires, which is exactly why the leak survived."""
    monkeypatch.setattr(orphans, "_parent_is_reaper", lambda ppid: ppid == 1704)
    assert orphans.is_orphan(_proc(10, 1704, _OURS)) is True


def test_a_parent_that_is_a_real_owner_still_protects_it(monkeypatch):
    monkeypatch.setattr(orphans, "_parent_is_reaper", lambda ppid: False)
    assert orphans.is_orphan(_proc(10, 4242, _OURS)) is False


def test_systemd_user_is_recognised_as_a_reaper(monkeypatch):
    class _Done:
        stdout = "systemd\n"

    monkeypatch.setattr(orphans.subprocess, "run", lambda *a, **k: _Done())
    assert orphans._parent_is_reaper(1704) is True


# ── Clients that outlive the display ────────────────────────────────────────────────────────
# Killing the launcher's process GROUP is not enough: Chromium (so VS Code, and every Electron
# app) puts its helper processes in their own session, so killpg never reaches them. Observed
# live — after a sandbox teardown, `--type=gpu-process/renderer/utility` processes were still
# running under systemd, holding the profile lock and pushing the next launch onto a new display.
# A sandbox owns its display, so anything still bound to it at teardown is the sandbox's to clean.


def test_a_process_bound_to_the_sandbox_display_is_a_client(monkeypatch):
    monkeypatch.setattr(orphans, "_proc_display", lambda pid: ":99" if pid == 7 else ":0")
    monkeypatch.setattr(orphans, "_all_pids", lambda: [7, 8])
    assert orphans.display_clients(":99") == [7]


def test_our_own_process_is_never_a_client(monkeypatch):
    """The sweep must not signal the process running it — the self-kill trap again."""
    monkeypatch.setattr(orphans, "_proc_display", lambda pid: ":99")
    monkeypatch.setattr(orphans, "_all_pids", lambda: [os.getpid(), 12])
    assert orphans.display_clients(":99") == [12]


@pytest.mark.parametrize("display", ["", None, ":0"])
def test_it_refuses_to_sweep_the_real_session_display(monkeypatch, display):
    """A bug that pointed this at the user's own display would kill their whole desktop."""
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(orphans, "_proc_display", lambda pid: ":0")
    monkeypatch.setattr(orphans, "_all_pids", lambda: [7])
    assert orphans.display_clients(display) == []


def test_killing_clients_reports_what_it_signalled(monkeypatch):
    monkeypatch.setattr(orphans, "display_clients", lambda d: [21, 22])
    monkeypatch.setattr(orphans, "_terminate", lambda pid: pid != 22)
    assert orphans.kill_display_clients(":99") == [21]


def test_proc_display_reads_the_processes_own_environment(tmp_path, monkeypatch):
    proc = tmp_path / "42"
    proc.mkdir()
    (proc / "environ").write_bytes(b"PATH=/bin\x00DISPLAY=:99\x00HOME=/home/x\x00")
    monkeypatch.setattr(orphans, "_PROC", tmp_path)
    assert orphans._proc_display(42) == ":99"


def test_proc_display_is_none_when_unreadable(tmp_path, monkeypatch):
    monkeypatch.setattr(orphans, "_PROC", tmp_path)
    assert orphans._proc_display(999) is None


def test_a_client_that_ignores_SIGTERM_is_killed(monkeypatch):
    """Observed live: a survivor stayed up through SIGTERM and kept the profile's IPC socket, so
    the next launch handed its window to a displayless zombie and the sandbox stayed empty."""
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(orphans, "display_clients", lambda d: [31])
    monkeypatch.setattr(orphans.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    # Without this the grace loop calls the REAL os.kill(31, 0) and then SIGKILLs pid 31.
    monkeypatch.setattr(orphans, "_still_alive", lambda pid: len(sent) < 2)
    assert orphans.kill_display_clients(":99") == [31]
    assert [sig for _, sig in sent] == [signal.SIGTERM, signal.SIGKILL]


# ── Never sweep a display we no longer own ──────────────────────────────────────────────────
# Display numbers are reclaimed the moment a Xephyr's lock drops, and several interact servers
# running at once is the NORMAL state. So if OUR X server died and server B claimed :99, sweeping
# ":99" on our way out would SIGKILL B's live sandbox. Our Xephyr still running is the proof that
# nobody else can hold that display — so that, and only that, licenses the sweep.


def test_teardown_sweeps_while_our_x_server_still_holds_the_display(monkeypatch):
    swept: list[str] = []
    monkeypatch.setattr(orphans, "kill_display_clients", lambda d, **k: swept.append(d) or [])
    orphans.sweep_if_owned(":99", owned=True)
    assert swept == [":99"]


def test_teardown_does_NOT_sweep_a_display_our_x_server_already_lost(monkeypatch):
    """Our Xephyr is gone → another server may already own :99 → its apps are not ours to kill."""
    swept: list[str] = []
    monkeypatch.setattr(orphans, "kill_display_clients", lambda d, **k: swept.append(d) or [])
    orphans.sweep_if_owned(":99", owned=False)
    assert swept == []


# ── Reaping an orphan must take its clients too ─────────────────────────────────────────────
# Killing the orphaned X server alone leaves its clients running and bound to a dead display —
# the very zombies that hold the editor profile socket and make the NEXT launch open nothing.
# The crash path has to clean both halves, exactly as teardown does.


def test_reaping_an_orphan_display_also_removes_its_clients(monkeypatch):
    swept: list[str] = []
    monkeypatch.setattr(orphans, "_list_x_servers",
                        lambda: [_proc(10, 1, _OURS + " :99 -screen 1280x800")])
    monkeypatch.setattr(orphans, "_parent_is_reaper", lambda ppid: True)
    monkeypatch.setattr(orphans, "_terminate", lambda pid: True)
    monkeypatch.setattr(orphans, "kill_display_clients", lambda d, **k: swept.append(d) or [])
    assert orphans.reap_orphaned_displays() == [10]
    assert swept == [":99"], "a reaped display's clients outlive it and break the next launch"


def test_the_display_a_server_serves_is_read_off_its_own_command_line():
    assert orphans.display_of("Xephyr :101 -screen 1280x800 -br -ac") == ":101"
    assert orphans.display_of("Xephyr -screen 1280x800") is None


def test_the_markers_still_match_the_command_we_actually_spawn():
    """`_OUR_MARKERS` re-states flags owned by `nested_server_command`. If that builder changes,
    the reaper silently stops recognising our OWN displays and the leak returns with no test
    failing — so bind them here."""
    from interact.desktop.backend import nested_server_command

    argv = nested_server_command(":99", "1280x800", headless=False)
    assert os.path.basename(argv[0]) == orphans._OUR_EXECUTABLE
    for marker in orphans._OUR_MARKERS:
        assert marker in argv, f"{marker!r} is no longer in the command we spawn"


def test_a_headless_xvfb_is_deliberately_left_alone():
    """Headless mode is invisible (no window, so no user-facing symptom) and its flags — `-screen`,
    `-nolisten tcp` — are what ANY Xvfb carries, so we could not tell ours from the user's. Not
    reaping it is a deliberate choice in favour of never killing someone else's server."""
    from interact.desktop.backend import nested_server_command

    headless = " ".join(nested_server_command(":99", "1280x800", headless=True))
    assert orphans.is_orphan(_proc(10, 1, headless)) is False


def test_doctor_labels_an_ownerless_sandbox_so_the_extra_window_is_explained(capsys, monkeypatch):
    """"Why do I see two Xephyr windows?" — one per interact server is BY DESIGN, one with no
    owner left is the leak. The report has to tell those two apart, or every window looks wrong."""
    from interact.cli.app import _print_sandboxes

    monkeypatch.setattr(orphans, "_list_x_servers", lambda: [
        _proc(10, 1, _OURS),        # adopted → orphan
        _proc(11, 4242, _OURS),     # a live server still owns it
    ])
    monkeypatch.setattr(orphans, "_parent_is_reaper", lambda ppid: ppid == 1)
    monkeypatch.setattr(orphans, "display_clients", lambda d: [1, 2])
    _print_sandboxes(":1")
    out = capsys.readouterr().out
    assert "2 open" in out
    assert "ORPHANED" in out
    assert "owner pid 4242" in out
