"""Delivering the extension, not merely noticing it is stale.

`interact doctor` could always SAY the installed extension was older than the tree and do nothing
about it. A whole day's work once sat undelivered behind exactly that warning: the artifact on
disk predated every change, so even a brand-new window showed the old product while every harness
check passed.
"""

# --- Detecting a stale extension is half a feature ---------------------------------------------
#
# `interact doctor` has always SAID the installed extension is older than the tree, and could do
# nothing about it. A whole day's work once sat undelivered behind exactly that warning: the
# artifact on disk predated every change, so even a brand-new window showed the old product, and
# every harness check passed the entire time.
#
# Pairing the detection with the remedy is the point. It is NOT automatic — installing an
# extension makes VS Code reload its extension hosts, which kills whatever session asked for it,
# so this only ever runs when someone explicitly asks for `--fix`.


def test_a_stale_extension_can_be_rebuilt_and_installed(monkeypatch, tmp_path):
    from interact import extension_status as es

    ran: list[list[str]] = []
    monkeypatch.setattr(es, "extension_status",
                        lambda: {"installed": "0.28.0", "tree": "0.29.0", "reason": "version"})
    monkeypatch.setattr(es, "_run", lambda argv, cwd=None: ran.append(argv) or (0, ""))
    monkeypatch.setattr(es, "_extension_dir", lambda: tmp_path)
    (tmp_path / "interact-0.29.0.vsix").write_text("x")

    assert es.deliver_extension() is True
    joined = [" ".join(a) for a in ran]
    assert any("package" in j for j in joined), f"never packaged: {joined}"
    assert any("--install-extension" in j for j in joined), f"never installed: {joined}"


def test_nothing_is_installed_when_the_extension_is_already_current(monkeypatch):
    """Reinstalling for no reason costs the user every editor window's extension host."""
    from interact import extension_status as es

    ran: list[list[str]] = []
    monkeypatch.setattr(es, "extension_status", lambda: None)
    monkeypatch.setattr(es, "_run", lambda argv, cwd=None: ran.append(argv) or (0, ""))
    assert es.deliver_extension() is False
    assert ran == []


def test_a_failed_package_is_reported_rather_than_claimed(monkeypatch, tmp_path):
    """The failure this whole feature exists to prevent is a delivery that was never checked."""
    from interact import extension_status as es

    monkeypatch.setattr(es, "extension_status",
                        lambda: {"installed": "0.28.0", "tree": "0.29.0", "reason": "version"})
    monkeypatch.setattr(es, "_run", lambda argv, cwd=None: (1, "vsce exploded"))
    monkeypatch.setattr(es, "_extension_dir", lambda: tmp_path)
    assert es.deliver_extension() is False
