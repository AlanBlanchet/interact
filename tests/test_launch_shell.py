"""Agents naturally launch project apps with shell phrasing — `cd <repo> && uv run app` — but
launch_app exec'd the shlex argv verbatim, failing with the cryptic `[Errno 2] No such file or
directory: 'cd'` (hit as the FIRST attempt by two independent sessions driving a real app).
A command using shell syntax must run via a shell instead of raw exec."""

import pytest

from interact.launch import needs_shell


@pytest.mark.parametrize(
    "cmd",
    [
        "cd /home/me/proj && uv run app",  # the exact real-session failure
        "  cd /tmp && ./run.sh",  # leading whitespace
        "make build && ./out/app",
        "app --flag | tee log",
        "app; other",
        "app > /tmp/out.log",
        "app < /tmp/in.txt",
        "APP_DIR=$(pwd) app",
        "echo `date` && app",
        "a || b",
    ],
)
def test_shell_syntax_commands_need_a_shell(cmd):
    assert needs_shell(cmd) is True


@pytest.mark.parametrize(
    "cmd",
    [
        "xterm",
        "flutter run -d linux",
        "/path/to/bin --flag value",
        "env LANG=C google-chrome",
        'app --title "plain quoted arg"',
    ],
)
def test_plain_exec_commands_do_not(cmd):
    assert needs_shell(cmd) is False


# ── VS Code (and other Electron editors) in the sandbox ──────────────────────────────────────
# An editor has the same singleton escape a browser does: launching `code` while an instance is
# running hands the request to that instance, which opens a window on the USER'S desktop. The
# sandbox then sits empty with no error — indistinguishable from a slow start.


from interact.launch import _editor_isolate  # noqa: E402


def test_vscode_gets_its_own_user_data_dir():
    argv, note = _editor_isolate(["code", "/home/alan/dev/interact"], ":99")
    joined = " ".join(argv)
    assert "--user-data-dir" in joined, "without this it joins the running instance"
    assert "99" in joined, "the profile is per-display so two sandboxes never share a lock"
    assert note


def test_electron_needs_software_gl_and_no_sandbox_on_a_nested_display():
    argv, _ = _editor_isolate(["code", "."], ":99")
    joined = " ".join(argv)
    # A nested X display has no usable hardware GL, and Electron's own sandbox fails without
    # user namespaces — both render a black window or refuse to start.
    assert "--disable-gpu" in joined
    assert "--no-sandbox" in joined


def test_a_non_editor_command_is_untouched():
    argv, note = _editor_isolate(["xterm"], ":99")
    assert argv == ["xterm"] and note == ""


def test_it_is_idempotent():
    once, _ = _editor_isolate(["code", "."], ":99")
    twice, _ = _editor_isolate(once, ":99")
    assert once == twice, "re-running the rewrite must not duplicate flags"


def test_the_rewrite_is_actually_applied_by_the_launcher():
    from interact.launch import apply_launch_rewrites

    argv, note = apply_launch_rewrites(["code", "/tmp/proj"], ":99")
    assert "--user-data-dir" in " ".join(argv) and note
