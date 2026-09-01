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

import pytest

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
    tree = tmp_path / "tree"
    (tree / "out").mkdir(parents=True)
    (tree / "out" / "extension.js").write_text("// rebuilt just now\n")
    monkeypatch.setattr("interact.extension_status._extensions_dir", lambda: tmp_path)
    monkeypatch.setattr("interact.extension_status._extension_dir", lambda: tree)
    monkeypatch.setattr("interact.extension_status._tree_version", lambda: "0.28.0")
    # An editor that started an hour ago cannot be running a build written a moment ago.
    monkeypatch.setattr("interact.extension_status._editor_starts", lambda: [time.time() - 3600])

    st = extension_status()

    assert st is not None and (st["reason"], st["remedy"]) == ("code", "restart"), st


@pytest.mark.parametrize(
    ("installed_bundle", "expected_status"),
    [
        pytest.param(b"exports.activate = 'current';\n", None, id="matching-bundle"),
        pytest.param(
            b"exports.activate = 'stale';\n",
            ("code", "install"),
            id="different-bundle",
        ),
    ],
)
def test_matching_version_with_an_editor_started_after_the_build_uses_compiled_bundle(
    tmp_path, monkeypatch, installed_bundle, expected_status
):
    extensions = tmp_path / "extensions"
    ext = extensions / "alanblanchet.interact-0.28.0"
    installed_compiled = ext / "out" / "extension.js"
    installed_compiled.parent.mkdir(parents=True)
    installed_compiled.write_bytes(installed_bundle)

    tree = tmp_path / "tree"
    tree_compiled = tree / "out" / "extension.js"
    tree_compiled.parent.mkdir(parents=True)
    tree_compiled.write_bytes(b"exports.activate = 'current';\n")

    monkeypatch.setattr("interact.extension_status._extensions_dir", lambda: extensions)
    monkeypatch.setattr("interact.extension_status._extension_dir", lambda: tree)
    monkeypatch.setattr("interact.extension_status._tree_version", lambda: "0.28.0")
    monkeypatch.setattr(
        "interact.extension_status._editor_starts",
        lambda: [installed_compiled.stat().st_mtime + 60],
    )

    status = extension_status()
    actual_status = None if status is None else (status["reason"], status["remedy"])

    assert actual_status == expected_status, status


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
    tree = tmp_path / "tree"
    (tree / "out").mkdir(parents=True)
    (tree / "out" / "extension.js").write_text("x")
    monkeypatch.setattr(es, "_extensions_dir", lambda: tmp_path)
    monkeypatch.setattr(es, "_extension_dir", lambda: tree)
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
