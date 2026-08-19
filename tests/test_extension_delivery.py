"""Delivering the extension must not kill the session that asks for it.

`code --install-extension` makes VS Code reload its extension hosts. That reload kills whatever
agent session is hosted in one of those windows — observed repeatedly on 2026-08-19, exiting 0
through the graceful terminate path, so it reads as a mysterious crash rather than a consequence.
The result is a perverse gate: the one step that DELIVERS the work destroys the context doing it,
so it keeps not happening, and a whole day of work sat on disk unseen.

A .vsix is a zip. Unpacking it into the extensions directory puts the same bytes in the same place
without signalling a running editor to reload anything — new windows pick it up, running ones keep
their frozen snapshot exactly as they would either way. Verified by hand before being written down.
"""

import zipfile

import pytest

from interact import extension_status as es


def _vsix(path, version="9.9.9", body="console.log(1)"):
    """A minimal but REAL .vsix: a zip whose payload lives under `extension/`."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("extension/package.json", f'{{"name":"interact","version":"{version}"}}')
        z.writestr("extension/out/extension.js", body)
        z.writestr("[Content_Types].xml", "<Types/>")  # vsix metadata, not part of the payload
    return path


def test_it_unpacks_the_payload_into_a_version_directory(tmp_path, monkeypatch):
    ext = tmp_path / "extensions"
    ext.mkdir()
    monkeypatch.setattr(es, "_extensions_dir", lambda: ext)
    v = _vsix(tmp_path / "interact-9.9.9.vsix")

    assert es._install_vsix(v, "9.9.9") is True
    target = ext / "alanblanchet.interact-9.9.9"
    assert (target / "package.json").is_file(), "the payload never landed"
    assert (target / "out" / "extension.js").read_text() == "console.log(1)"
    assert not (target / "extension").exists(), "the `extension/` prefix must be stripped"


def test_it_never_shells_out_to_the_editor(tmp_path, monkeypatch):
    """The whole point. Any `code --install-extension` here reloads the hosts and kills us."""
    ext = tmp_path / "extensions"
    ext.mkdir()
    monkeypatch.setattr(es, "_extensions_dir", lambda: ext)
    called = []
    monkeypatch.setattr(es, "_run", lambda argv, cwd=None: called.append(argv) or (0, ""))

    es._install_vsix(_vsix(tmp_path / "interact-9.9.9.vsix"), "9.9.9")
    assert not called, f"delivery shelled out to {called} — that reload is what kills the session"


def test_a_reinstall_replaces_rather_than_merges(tmp_path, monkeypatch):
    """A stale file left behind from a previous version is a file the host will happily load."""
    ext = tmp_path / "extensions"
    (ext / "alanblanchet.interact-9.9.9" / "out").mkdir(parents=True)
    (ext / "alanblanchet.interact-9.9.9" / "out" / "gone.js").write_text("stale")
    monkeypatch.setattr(es, "_extensions_dir", lambda: ext)

    es._install_vsix(_vsix(tmp_path / "interact-9.9.9.vsix"), "9.9.9")
    assert not (ext / "alanblanchet.interact-9.9.9" / "out" / "gone.js").exists()


def test_a_corrupt_package_fails_loudly_rather_than_half_installing(tmp_path, monkeypatch):
    ext = tmp_path / "extensions"
    ext.mkdir()
    monkeypatch.setattr(es, "_extensions_dir", lambda: ext)
    bad = tmp_path / "broken.vsix"
    bad.write_bytes(b"not a zip")

    assert es._install_vsix(bad, "9.9.9") is False
    assert not list(ext.iterdir()), "a failed install must leave nothing behind"
