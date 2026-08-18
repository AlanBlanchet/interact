"""Clean up sandbox X servers whose owner is gone.

Every interact MCP server owns its own sandbox, so a user with several editor windows genuinely
has several servers — and each spawns its own Xephyr on first launch. That part is by design.

What is NOT by design: when a server dies without tearing down (a crash, a reload, a killed
session), its X server survives. It is reparented to init, so nothing remembers it exists, and it
sits on the user's screen until they kill it by hand. This finds those and removes them.

An orphan has to satisfy BOTH conditions — it is one of OURS (spawned with our own flags) and its
parent is gone. Killing on either alone would destroy a display someone is still using, or a
Xephyr the user started themselves for their own reasons.
"""

import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass

from interact.desktop.backend import SANDBOX_TITLE
from pathlib import Path

#: What one of OUR sandbox displays looks like. These re-state flags owned by
#: `backend.nested_server_command`; `test_the_markers_still_match_the_command_we_actually_spawn`
#: binds them to it, so changing that builder fails a test instead of silently switching the
#: reaper off.
#:
#: HEADLESS (Xvfb) displays are deliberately NOT reaped. They render no window, so they cause none
#: of the symptoms this exists for, and their flags (`-screen`, `-nolisten tcp`) are what ANY Xvfb
#: carries — we could not tell ours from one the user started. Not reclaiming a resource is a much
#: cheaper mistake than killing someone else's server.
_OUR_EXECUTABLE = "Xephyr"
#: Our own window title, which nobody else sets — unlike `-noreset -no-host-grab`, which is
#: exactly the line a person types by hand and so never really identified anything.
_OUR_MARKERS = (SANDBOX_TITLE,)


@dataclass
class XServer:
    pid: int
    ppid: int
    cmdline: str


def _list_x_servers() -> list[XServer]:
    """Every running Xephyr, with its parent. Uses ps so there is no dependency to install."""
    out = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,args="], capture_output=True, text=True, timeout=10, check=True
    ).stdout
    servers = []
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        # Match the EXECUTABLE, never the text. Testing `"Xephyr" in cmdline` matched the very
        # command hunting for orphans (it mentions the name), and a grep, and anything else that
        # says the word — then signalled them. Same self-match trap as `pkill -f <own pattern>`.
        argv0 = parts[2].split()[0]
        if os.path.basename(argv0) != _OUR_EXECUTABLE:
            continue
        try:
            servers.append(XServer(pid=int(parts[0]), ppid=int(parts[1]), cmdline=parts[2]))
        except ValueError:
            continue
    return servers


def process_alive(pid: int) -> bool:
    """Whether a pid is running. PermissionError means it EXISTS and is not ours — alive.

    One definition, because the two copies of this disagreed on exactly that case (one read it as
    dead) and this one decides whether something gets killed.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _terminate(pid: int) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


#: Processes that ADOPT orphans. A modern Linux user session registers `systemd --user` as a
#: child-subreaper, so a dead owner's children are reparented to IT rather than to pid 1 —
#: observed directly on this machine, where a leaked Xephyr sat under systemd and a
#: pid-1-only rule never fired.
_REAPER_NAMES = ("systemd", "init", "launchd")


def _parent_is_reaper(ppid: int) -> bool:
    if ppid in (0, 1):
        return True
    try:
        comm = subprocess.run(
            ["ps", "-o", "comm=", "-p", str(ppid)],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except Exception:
        return False  # cannot tell → assume it is owned; never kill on a guess
    return os.path.basename(comm) in _REAPER_NAMES


def is_orphan(server: XServer) -> bool:
    """Ours AND adopted. A dead owner's X server is reparented — to pid 1, or on a systemd user
    session to `systemd --user` — and the process itself cannot tell us who used to own it."""
    if not all(marker in server.cmdline for marker in _OUR_MARKERS):
        return False  # not one of ours — never touch a display we did not create
    return _parent_is_reaper(server.ppid)


def display_of(cmdline: str) -> str | None:
    """The display an X server serves, read off its own command line (`Xephyr :99 …`)."""
    return next((tok for tok in cmdline.split()[1:] if re.fullmatch(r":\d+", tok)), None)


def sweep_if_owned(display: str | None, *, owned: bool) -> list[int]:
    """Sweep a display's clients only while WE still hold it.

    Display numbers are reclaimed the instant an X server's lock drops, and several interact
    servers at once is the normal state — so a sweep keyed on a display string must first prove
    our own X server is still running on it. Otherwise a server whose Xephyr died would kill the
    live sandbox of whichever server has since claimed that number.
    """
    return kill_display_clients(display) if owned else []


def reap_orphaned_displays() -> list[int]:
    """Terminate every orphaned sandbox display; returns the pids signalled.

    Best-effort by construction: it runs immediately before a launch, so a failure to enumerate
    must never be the reason a launch fails.
    """
    try:
        servers = _list_x_servers()
    except Exception:
        return []
    killed = []
    for server in servers:
        if not is_orphan(server):
            continue
        # Its CLIENTS outlive it: they keep running bound to a dead display and hold the editor
        # profile's socket, so the next launch hands its window to a zombie and opens nothing.
        # Killing the X server alone fixes the window on screen and leaves the real breakage.
        kill_display_clients(display_of(server.cmdline))
        if _terminate(server.pid):
            killed.append(server.pid)
    return killed


# ── Clients that outlive the display ────────────────────────────────────────────────────────

_PROC = Path("/proc")


def _all_pids() -> list[int]:
    try:
        return [int(p.name) for p in _PROC.iterdir() if p.name.isdigit()]
    except OSError:
        return []


def _proc_display(pid: int) -> str | None:
    """Which X display a process is bound to, read from its OWN environment.

    Authoritative and app-agnostic: it does not care whether the process is an editor, a browser
    or a terminal, only which display it would draw on.
    """
    try:
        raw = (_PROC / str(pid) / "environ").read_bytes()
    except OSError:
        return None  # gone, or another user's process we cannot read
    for entry in raw.split(b"\0"):
        if entry.startswith(b"DISPLAY="):
            return entry[len(b"DISPLAY="):].decode("utf-8", "replace")
    return None


def display_clients(display: str | None) -> list[int]:
    """Every process still bound to a sandbox display — minus this one.

    Killing the launcher's process GROUP misses these: Chromium (so VS Code and every Electron
    app) puts its helpers in their own session, so `killpg` never reaches them. They then outlive
    the display, hold the profile lock, and push the next launch onto a different display.
    """
    if not display or display == os.environ.get("DISPLAY"):
        return []  # never sweep the user's real session — that would kill their whole desktop
    me = os.getpid()
    return [pid for pid in _all_pids() if pid != me and _proc_display(pid) == display]


def _still_alive(pid: int) -> bool:
    return process_alive(pid)


def kill_display_clients(display: str | None, *, grace: float = 1.5) -> list[int]:
    """Terminate everything left on a sandbox display, escalating; returns the pids signalled.

    A polite SIGTERM is not always enough — a survivor that ignores it keeps the profile's IPC
    socket open, and the next launch hands its window to that displayless zombie instead of
    opening one, so the sandbox stays empty with no error anywhere.
    """
    targets = display_clients(display)
    signalled = [pid for pid in targets if _terminate(pid)]
    if not signalled:
        return []
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and any(_still_alive(pid) for pid in signalled):
        time.sleep(0.1)
    for pid in signalled:
        if _still_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    return signalled
