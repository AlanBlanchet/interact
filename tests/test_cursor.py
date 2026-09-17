"""`Cursor.current_type()` must read the DISPLAY it is TOLD, never always the process's own
$DISPLAY — the nested sandbox runs a separate isolated X server (":99" while the process's own
$DISPLAY is ":0" or unset), and `XOpenDisplay(None)` reads the wrong one, so a cursor step
reported through a sandbox target always said "default" no matter what the sandbox showed (#131).
"""

from unittest.mock import MagicMock

from interact.desktop.cursor import Cursor
import interact.desktop.cursor as cursor_mod
from interact.desktop.nested import NestedBackend


def _stub_x11(monkeypatch, cursor_name: bytes | None = b"xterm"):
    """Stub libX11/libXfixes so `current_type` runs its real logic against a fake display handle,
    and hand back the ctypes call log so the test can assert WHICH display was opened."""
    calls = {}

    fake_x11 = MagicMock()
    def _open(arg):
        calls["open_arg"] = arg
        return 0xDEAD

    fake_x11.XOpenDisplay.side_effect = _open
    fake_x11.XCloseDisplay.side_effect = lambda h: calls.__setitem__("closed", h)
    fake_x11.XFree.return_value = None

    fake_xfixes = MagicMock()
    fake_cursor = MagicMock()
    fake_cursor.name = cursor_name
    fake_cursor.width, fake_cursor.height = 10, 10
    fake_ptr = MagicMock()
    fake_ptr.contents = fake_cursor
    fake_ptr.__bool__ = lambda self: True
    fake_xfixes.XFixesGetCursorImage.return_value = fake_ptr

    monkeypatch.setattr(cursor_mod, "_libx11", fake_x11)
    monkeypatch.setattr(cursor_mod, "_libxfixes", fake_xfixes)
    return calls


def test_current_type_with_no_display_opens_the_process_default(monkeypatch):
    calls = _stub_x11(monkeypatch)
    assert Cursor.current_type() == "text"
    assert calls["open_arg"] is None, "no display given → must open the process's own $DISPLAY"


def test_current_type_with_explicit_display_opens_that_display_not_the_default(monkeypatch):
    calls = _stub_x11(monkeypatch)
    Cursor.current_type(":99")
    assert calls["open_arg"] == b":99", (
        "a target's OWN display must be opened — passing None here silently reads the host's "
        "cursor instead of the nested sandbox's (#131)"
    )


def test_nested_backend_cursor_type_reads_its_own_display_not_the_process_default(monkeypatch):
    """NestedBackend.cursor_type() must feed Cursor.current_type() ITS OWN `self.display`."""
    nb = NestedBackend.__new__(NestedBackend)
    nb.display = ":99"

    seen = {}
    monkeypatch.setattr(
        "interact.desktop.cursor.Cursor.current_type",
        classmethod(lambda cls, display=None: (seen.__setitem__("display", display), "pointer")[1]),
    )
    assert nb.cursor_type() == "pointer"
    assert seen["display"] == ":99", "must pass the sandbox's own display, not the process default"
