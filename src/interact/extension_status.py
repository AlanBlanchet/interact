"""Is the VS Code extension the user is running the one in this tree?

The MCP half of this question lives in :mod:`interact.server_registry`. This is the other half,
and the project's own notes record why it needs one: ``code <path>`` against a RUNNING editor is
handed to that instance's singleton, so the new window is served by the OLD extension host and
reinstalling at the same version never reaches it. `interact doctor` answered the question for
servers and said nothing at all about the extension, which left half the delivery gate missing.

Two ways it goes stale. A version behind the tree is the easy one. The one a version check
structurally cannot see is a matching version whose BUILD was written after the editor started —
which is every rebuild during development, i.e. exactly when it matters.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from interact.server_registry import _process_start

#: Shared with the server half on purpose: one question, one answer.
_process_start = _process_start

_DIR_RE = re.compile(r"^alanblanchet\.interact-(\d+\.\d+\.\d+)$", re.IGNORECASE)


def _extensions_dir() -> Path:
    return Path.home() / ".vscode" / "extensions"


def _tree_version() -> str | None:
    pkg = Path(__file__).resolve().parents[2] / "vscode-extension" / "package.json"
    try:
        return json.loads(pkg.read_text()).get("version")
    except (OSError, ValueError):
        return None


def _editor_starts() -> list[float]:
    """Start times of every running VS Code MAIN process.

    Electron helpers must be excluded — they are restarted freely and say nothing about which
    extension host is loaded. That is harder than it looks: some of them do not NUL-separate their
    argv at all, so the whole command line arrives as a single element and a `--type=` check over
    argv[1:] sees nothing. Match against the raw blob instead.
    """
    out: list[float] = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            raw = (proc / "cmdline").read_bytes()
        except OSError:
            continue
        if not raw:
            continue
        if b"--type=" in raw:
            continue  # a renderer / utility / zygote / broker, not the main process
        exe = raw.split(b"\0")[0].split(b" ")[0]
        if Path(exe.decode(errors="ignore")).name not in {"code", "electron"}:
            continue
        started = _process_start(int(proc.name))
        if started is not None:
            out.append(started)
    return out


def _build_mtime(ext: Path) -> float:
    newest = 0.0
    for f in ext.rglob("*.js"):
        try:
            newest = max(newest, f.stat().st_mtime)
        except OSError:
            continue
    return newest


def extension_status() -> dict | None:
    """What is stale about the installed extension, or ``None`` when nothing is.

    Returns ``{"installed", "tree", "reason"}`` where reason is ``"version"`` (an older build is
    installed) or ``"code"`` (the right version is installed, but an editor is running that
    started before it was built).
    """
    d = _extensions_dir()
    installed: list[tuple[str, Path]] = []
    try:
        for child in d.iterdir():
            m = _DIR_RE.match(child.name)
            if m:
                installed.append((m.group(1), child))
    except OSError:
        return None
    if not installed:
        return None  # MCP-only user; not a problem to report

    installed.sort(key=lambda p: [int(n) for n in p[0].split(".")])
    version, path = installed[-1]
    tree = _tree_version()
    if tree and version != tree:
        return {"installed": version, "tree": tree, "reason": "version"}

    built = _build_mtime(path)
    starts = _editor_starts()
    behind = [s for s in starts if s < built]
    if built and behind:
        # Not all of them, usually: windows opened since the rebuild are fine. Say how many are
        # not, because "your editor is stale" when five of eight are current is its own confusion.
        return {"installed": version, "tree": tree or version, "reason": "code",
                "behind": len(behind), "running": len(starts)}
    return None
