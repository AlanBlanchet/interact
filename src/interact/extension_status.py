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

#: VS Code installs an extension as `<publisher>.<name>-<version>`. Both halves already live in
#: the manifest this module reads, so they are derived rather than spelled a second time here.
def _dir_re() -> re.Pattern[str]:
    manifest = _manifest()
    publisher = (manifest.get("publisher") or "alanblanchet").lower()
    name = (manifest.get("name") or "interact").lower()
    return re.compile(rf"^{re.escape(publisher)}\.{re.escape(name)}-(\d+\.\d+\.\d+)$", re.IGNORECASE)


def _extensions_dir() -> Path:
    return Path.home() / ".vscode" / "extensions"


def _manifest() -> dict:
    pkg = Path(__file__).resolve().parents[2] / "vscode-extension" / "package.json"
    try:
        return json.loads(pkg.read_text())
    except (OSError, ValueError):
        return {}


def _tree_version() -> str | None:
    return _manifest().get("version")


_EDITOR_EXES = {"code", "code-insiders", "codium", "vscodium", "code-server", "electron"}


def _is_editor_cmdline(raw: bytes) -> bool:
    """Whether this command line is an editor WINDOW rather than one of its helpers.

    Two things masquerade as the main process. Electron helpers carry `--type=`, and several of
    them do not NUL-separate their argv at all, so the flag has to be matched against the whole
    blob. Language servers are subtler: VS Code runs pylance, tsserver, copilot and friends
    through the SAME binary with ELECTRON_RUN_AS_NODE and no `--type=`, so a check of "basename is
    code, no --type=" counted fourteen editors for one open window. They are told apart by their
    first argument being a script to run.
    """
    if not raw or b"--type=" in raw:
        return False
    parts = [p for p in raw.split(b"\0") if p]
    if not parts:
        return False
    exe = Path(parts[0].split(b" ")[0].decode(errors="ignore")).name.lower()
    if exe not in _EDITOR_EXES:
        return False
    # `code /path/to/server.js --stdio` is a language server wearing the editor's binary.
    return not any(arg.endswith(b".js") for arg in parts[1:])


def _iter_proc():
    """Every /proc entry, or a FileNotFoundError where /proc does not exist."""
    return Path("/proc").iterdir()


def _editor_starts() -> list[float]:
    """Start times of every running VS Code MAIN process.

    Electron helpers must be excluded — they are restarted freely and say nothing about which
    extension host is loaded. That is harder than it looks: some of them do not NUL-separate their
    argv at all, so the whole command line arrives as a single element and a `--type=` check over
    argv[1:] sees nothing. Match against the raw blob instead.
    """
    out: list[float] = []
    try:
        entries = list(_iter_proc())
    except OSError:
        return []  # no /proc: macOS, Windows. Unknown, not a crash — this is a diagnostic.
    for proc in entries:
        if not proc.name.isdigit():
            continue
        try:
            raw = (proc / "cmdline").read_bytes()
        except OSError:
            continue
        if not _is_editor_cmdline(raw):
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
    pattern = _dir_re()
    try:
        for child in d.iterdir():
            m = pattern.match(child.name)
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


def _extension_dir() -> Path:
    """The extension SOURCE in this checkout — where the package is built from."""
    return Path(__file__).resolve().parent.parent.parent / "vscode-extension"


def _run(argv: list[str], cwd: Path | None = None) -> tuple[int, str]:
    """Run a build/install step, returning (code, output). Kept tiny and injectable so the
    delivery logic can be tested without packaging a real extension."""
    import subprocess

    try:
        done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=600)
        return done.returncode, (done.stdout or "") + (done.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def deliver_extension() -> bool:
    """Rebuild and install the extension when the installed one is older than this tree.

    `interact doctor` has always been able to SAY the installed extension was stale and do nothing
    about it — and a detector for a condition you can remedy is half a feature. A whole day's work
    once sat undelivered behind exactly that warning: the artifact on disk predated every change,
    so even a brand-new window showed the old product while every test passed.

    NOT automatic, deliberately. Installing an extension makes VS Code reload its extension hosts,
    which kills whatever session asked for it — so this runs only when somebody explicitly asks.

    Returns True only when a new package was actually installed; a failure at any step returns
    False and says why, because the failure this exists to prevent IS an unverified delivery.
    """
    status = extension_status()
    if not status:
        return False  # already current: a needless reinstall costs every window its host

    where = _extension_dir()
    code, out = _run(["npm", "run", "package"], cwd=where)
    if code != 0:
        print(f"could not package the extension: {out.strip()[-400:]}")
        return False

    vsix = sorted(where.glob("interact-*.vsix"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not vsix:
        print("packaging reported success but produced no .vsix")
        return False

    code, out = _run(["code", "--install-extension", str(vsix[0]), "--force"])
    if code != 0:
        print(f"could not install {vsix[0].name}: {out.strip()[-400:]}")
        return False
    return True
