"""The VS Code extension is the OTHER long-lived consumer, and `doctor` said nothing about it.

The project's own notes record the trap: `code <path>` against a RUNNING instance is handed to
that instance's singleton, so the new window is served by the OLD extension host and reinstalling
the same version never reaches it. `doctor` already answers this question for MCP servers — "is
the thing you are running actually running my fix" — and answered nothing for the extension, so
half the delivery gate was missing.

Two ways it goes stale, and the second is the one a version check cannot see:
  * the installed extension is an older VERSION than the tree;
  * the versions match, but the running editor started BEFORE that build was written.
"""

import time

from interact import server_registry as reg
from interact.extension_status import extension_status


def test_an_older_installed_version_is_reported(tmp_path, monkeypatch):
    (tmp_path / "alanblanchet.interact-0.27.0").mkdir()
    monkeypatch.setattr("interact.extension_status._extensions_dir", lambda: tmp_path)
    monkeypatch.setattr("interact.extension_status._tree_version", lambda: "0.28.0")

    st = extension_status()

    assert st is not None
    assert st["installed"] == "0.27.0"
    assert st["tree"] == "0.28.0"
    assert st["reason"] == "version"


def test_a_matching_version_with_a_newer_build_than_the_editor_is_still_stale(tmp_path, monkeypatch):
    ext = tmp_path / "alanblanchet.interact-0.28.0"
    ext.mkdir()
    (ext / "out").mkdir()
    (ext / "out" / "extension.js").write_text("// rebuilt just now\n")
    monkeypatch.setattr("interact.extension_status._extensions_dir", lambda: tmp_path)
    monkeypatch.setattr("interact.extension_status._tree_version", lambda: "0.28.0")
    # An editor that started an hour ago cannot be running a build written a moment ago.
    monkeypatch.setattr("interact.extension_status._editor_starts", lambda: [time.time() - 3600])

    st = extension_status()

    assert st is not None and st["reason"] == "code", st


def test_a_matching_version_with_an_editor_started_after_the_build_is_clean(tmp_path, monkeypatch):
    ext = tmp_path / "alanblanchet.interact-0.28.0"
    ext.mkdir()
    (ext / "out").mkdir()
    (ext / "out" / "extension.js").write_text("x")
    monkeypatch.setattr("interact.extension_status._extensions_dir", lambda: tmp_path)
    monkeypatch.setattr("interact.extension_status._tree_version", lambda: "0.28.0")
    monkeypatch.setattr("interact.extension_status._editor_starts", lambda: [time.time() + 60])

    assert extension_status() is None


def test_no_installed_extension_is_not_a_complaint(tmp_path, monkeypatch):
    """Plenty of people use interact purely as an MCP server; that is not a problem to report."""
    monkeypatch.setattr("interact.extension_status._extensions_dir", lambda: tmp_path)
    assert extension_status() is None


def test_it_reuses_the_process_start_helper():
    """Same question as the MCP half, so it must not grow a second answer to it."""
    import interact.extension_status as es

    assert es._process_start is reg._process_start


# --- code-reviewer findings: it must not crash off Linux, and it must not count language servers ---


def test_it_does_not_crash_where_proc_does_not_exist(monkeypatch, tmp_path):
    """`/proc` is Linux-only. Reading it unguarded means `interact doctor` — a DIAGNOSTIC, the
    command someone runs precisely when things are wrong — tracebacks for every macOS and Windows
    user with the extension installed. The server half already carries a platform guard; this one
    did not, which is the same class the project has been bitten by in CI before."""
    import interact.extension_status as es

    ext = tmp_path / "alanblanchet.interact-0.28.0"
    (ext / "out").mkdir(parents=True)
    (ext / "out" / "extension.js").write_text("x")
    monkeypatch.setattr(es, "_extensions_dir", lambda: tmp_path)
    monkeypatch.setattr(es, "_tree_version", lambda: "0.28.0")

    def no_proc():
        raise FileNotFoundError("/proc")

    monkeypatch.setattr(es, "_iter_proc", no_proc)

    assert es.extension_status() is None  # unknown, not a crash


def test_a_language_server_is_not_an_editor(tmp_path, monkeypatch):
    """VS Code spawns pylance/tsserver/copilot as `code <server.js>` with ELECTRON_RUN_AS_NODE and
    no `--type=`, so a filter of "basename is code, no --type=" counted 14 editors for one open
    window. The verdict was still right — a server is a child, so it cannot predate its parent —
    but a count nobody can reconcile with their screen is not a diagnostic."""
    import interact.extension_status as es

    assert es._is_editor_cmdline(b"/usr/share/code/code\x00") is True
    assert es._is_editor_cmdline(b"/usr/share/code/code\x00--ozone-platform-hint=auto\x00") is True
    assert es._is_editor_cmdline(b"/usr/share/code/code\x00--type=renderer\x00") is False
    assert es._is_editor_cmdline(
        b"/usr/share/code/code\x00/home/alan/.vscode/extensions/ms-python/server.js\x00--stdio\x00"
    ) is False, "a language server run through the code binary is not an editor window"


def test_other_vs_code_flavours_are_recognised():
    """Insiders, VSCodium and code-server are the same product for this purpose."""
    import interact.extension_status as es

    for exe in (b"code-insiders", b"codium", b"code-server", b"electron"):
        assert es._is_editor_cmdline(b"/usr/bin/" + exe + b"\x00"), exe
