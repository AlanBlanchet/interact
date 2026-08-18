"""#110: a `record()` on a session emulating an iPhone produced a 1280x720 video of the DESKTOP
layout — different headline copy, different theme state — while `evaluate_js` in that same named
session reported innerWidth 390 immediately before and after. The reporter read it as session
cross-talk (another caller's context) and abandoned record() for motion verification.

It is simpler and entirely local: the recording context asks for the emulated viewport but hard-codes
the VIDEO size to the configured desktop one, so the page renders at 390 and the frames are painted
at 1280x720. Recording also rebuilt the context around `pages[0]` rather than the session's ACTIVE
tab, and dropped the forced media features (`prefers-reduced-motion`, `color-scheme`) that
emulate_device had applied — so the clip could differ from the live session in three ways at once.
"""

from interact.browser import BrowserManager
from interact.config import Config


def _mgr() -> BrowserManager:
    return BrowserManager(Config(headless=True, browser_type="chromium"))


def test_a_recording_is_sized_to_the_emulated_device_not_the_desktop_default():
    mgr = _mgr()
    mgr._device_override = {"width": 390, "height": 664, "is_mobile": True, "has_touch": True}

    kw = mgr._context_kwargs(record_video_dir="/tmp/does-not-matter")

    assert kw["viewport"] == {"width": 390, "height": 664}
    assert kw["record_video_size"] == {"width": 390, "height": 664}, (
        "the frames must be painted at the size the page is rendered at"
    )


def test_a_recording_with_no_emulation_still_uses_the_configured_viewport():
    mgr = _mgr()
    kw = mgr._context_kwargs(record_video_dir="/tmp/does-not-matter")

    assert kw["record_video_size"] == {
        "width": mgr._config.viewport_width,
        "height": mgr._config.viewport_height,
    }


def test_recording_keeps_the_session_on_its_active_tab():
    """`record` rebuilt the context from `pages[0]`, so after switch_tab it carried the wrong
    page's URL across the rebuild — recording, and then leaving the session on, a different page
    than every other tool was looking at."""

    class FakeContext:
        pages = ["tab0", "tab1", "tab2"]

    mgr = _mgr()
    mgr._context = FakeContext()

    mgr._active_tab = 2
    assert mgr._active_page() == "tab2"

    mgr._active_tab = 0
    assert mgr._active_page() == "tab0"


def test_active_page_survives_a_tab_closing_under_it():
    """The index can outlive the tab it points at; clamp rather than raise mid-recording."""

    class FakeContext:
        pages = ["only"]

    mgr = _mgr()
    mgr._context = FakeContext()
    mgr._active_tab = 5
    assert mgr._active_page() == "only"


def test_no_pages_at_all_is_not_a_crash():
    class Empty:
        pages: list = []

    mgr = _mgr()
    mgr._context = Empty()
    assert mgr._active_page() is None
