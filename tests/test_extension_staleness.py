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
