"""interact must not drive the editor window that is hosting the caller.

An agent typing a command into its own editor can destroy the process issuing the command —
"Developer: Reload Window" ends the session mid-task, and nothing survives to notice or repair
it. This actually happened: a reload aimed at another window landed in the caller's own, and the
session died.

The blast radius of an action must never include the actor. So a desktop target that resolves to
the caller's own editor window is refused by default, with the reason and the escape hatch named.
"""

import pytest

from interact.desktop.selfguard import is_self_window, self_window_hints


@pytest.fixture(autouse=True)
def _caller(monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/home/alan/dev/interact")
    yield


@pytest.mark.parametrize(
    "title",
    [
        "interact - Visual Studio Code",
        "interact — Visual Studio Code",       # em dash, some builds
        "● interact - Visual Studio Code",     # unsaved-changes marker
        "INTERACT - Visual Studio Code",       # case
    ],
)
def test_the_callers_own_editor_window_is_recognised(title):
    assert is_self_window(title) is True, f"{title!r} is the window running this session"


@pytest.mark.parametrize(
    "title",
    [
        "hintconf - Visual Studio Code",
        "AI-4-Alan - Visual Studio Code",
        "interactive-demo - Visual Studio Code",  # merely CONTAINS the word, different project
        "Google Chrome",
        "Xephyr on :99.0",
    ],
)
def test_other_windows_are_not_mistaken_for_it(title):
    assert is_self_window(title) is False


def test_a_caller_with_no_project_dir_claims_no_self_window(monkeypatch):
    # Guessing here would be worse than not guarding: it would block legitimate targets.
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setattr("interact.desktop.selfguard._cwd_name", lambda: "")
    assert self_window_hints() == []
    assert is_self_window("anything - Visual Studio Code") is False


def test_the_hint_is_the_project_name_not_a_path():
    assert "interact" in self_window_hints()
    assert not any("/" in h for h in self_window_hints())


# ── the guard has to be ON the path, not merely available ────────────────────────────────────


def test_run_actions_refuses_the_callers_own_editor(monkeypatch):
    """A helper nobody calls is not a guard. Mutating input aimed at the caller's own editor must
    be refused at the point the action is dispatched."""
    import asyncio

    import interact.server as srv

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/home/alan/dev/interact")
    from interact.actions import KeyPressAction

    out = asyncio.run(
        srv.run_actions(
            [KeyPressAction(key="ctrl+shift+p")],
            target="interact - Visual Studio Code",
        )
    )
    assert "REFUSED" in out and "hosting THIS session" in out


def test_reading_the_callers_own_window_is_still_allowed(monkeypatch):
    """Looking is harmless and useful — the guard is about INPUT, not observation. Blocking a
    screenshot would make the agent blind to its own editor for no safety gain."""
    import asyncio

    import interact.server as srv

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/home/alan/dev/interact")
    out = asyncio.run(srv.screenshot(target="interact - Visual Studio Code"))
    assert "REFUSED" not in str(out)


# ── typing must land where it was aimed ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_typing_verifies_the_window_actually_has_focus(monkeypatch):
    """`windowactivate` is asynchronous and best-effort — it can lose a race or be refused by the
    WM. Typing anyway sends the keystrokes to WHATEVER holds focus, which is how a reload aimed
    at one window landed in another and killed the session. Verify, then type."""
    from interact.desktop import DesktopWindow

    win = DesktopWindow(name="target", wid=4242, w=800, h=600, x=0, y=0)
    typed: list[str] = []

    async def fake_run(*args):
        if args[:2] == ("xdotool", "getwindowfocus"):
            return "9999"  # a DIFFERENT window ended up focused
        if args[1] == "type":
            typed.append(args[-1])
        return ""

    monkeypatch.setattr(win, "_run", fake_run)
    with pytest.raises(RuntimeError) as exc:
        await win.type_text("Developer: Reload Window")
    assert "focus" in str(exc.value).lower()
    assert typed == [], "keystrokes were sent to a window that was not the target"


@pytest.mark.asyncio
async def test_typing_proceeds_when_focus_landed(monkeypatch):
    from interact.desktop import DesktopWindow

    win = DesktopWindow(name="target", wid=4242, w=800, h=600, x=0, y=0)
    typed: list[str] = []

    async def fake_run(*args):
        if args[:2] == ("xdotool", "getwindowfocus"):
            return "4242"  # the intended window
        if args[1] == "type":
            typed.append(args[-1])
        return ""

    monkeypatch.setattr(win, "_run", fake_run)
    await win.type_text("hello")
    assert typed == ["hello"]
