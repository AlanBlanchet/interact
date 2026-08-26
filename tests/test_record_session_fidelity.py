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

import pytest

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


@pytest.mark.asyncio
async def test_a_rebuilt_context_keeps_the_forced_media_features():
    """emulate_device forces media features onto the context; every path that REBUILDS one has to
    re-assert them. The fix had been applied to the two recording paths and missed _rebuild_context
    — the same sub-bug, one call site over — so it now lives in _new_context, where forgetting it
    is not possible."""
    mgr = _mgr()
    try:
        await mgr.ensure_ready()
    except Exception as exc:
        pytest.skip(f"no launchable chromium: {exc}")
    try:
        await mgr.apply_media(reduced_motion="reduce", color_scheme="dark")
        page = await mgr.get_page()
        assert await page.evaluate(
            "() => matchMedia('(prefers-reduced-motion: reduce)').matches"
        ), "setup: the override did not apply at all"

        await mgr._rebuild_context()  # what a viewport / DPR / mobile change does

        page = await mgr.get_page()
        assert await page.evaluate("() => matchMedia('(prefers-reduced-motion: reduce)').matches")
        assert await page.evaluate("() => matchMedia('(prefers-color-scheme: dark)').matches")
    finally:
        await mgr.close()


@pytest.mark.asyncio
async def test_a_recording_keeps_the_pages_local_storage(http_origin):
    """#123: `record(start=True)` swapped the context carrying only its COOKIES, so the page came
    back with its localStorage gone — an app's logged-in / onboarded state — and the agent recorded
    a fresh-origin render, reading its first-visit banner as a "flash" regression. `document.cookie`
    surviving is what pinned the loss on the page instead of the recorder. The stop swap dropped it a
    second time. Real Playwright, real http origin: the mocked test cannot know what storage_state
    holds, only that it was handed over."""
    mgr = _mgr()
    try:
        await mgr.ensure_ready()
    except Exception as exc:
        pytest.skip(f"no launchable chromium: {exc}")
    try:
        page = await mgr.get_page()
        await page.goto(http_origin)
        await page.evaluate("() => localStorage.setItem('onboarded', '1')")

        url, trouble = await mgr.start_recording()

        assert trouble is None and url.rstrip("/") == http_origin
        page = await mgr.get_page()
        assert await page.evaluate("() => localStorage.getItem('onboarded')") == "1", (
            "record(start) wiped the page's localStorage"
        )

        await mgr.stop_recording()

        page = await mgr.get_page()
        assert page.url.rstrip("/") == http_origin
        assert await page.evaluate("() => localStorage.getItem('onboarded')") == "1", (
            "record(stop) wiped the page's localStorage"
        )
    finally:
        await mgr.close()


@pytest.mark.asyncio
async def test_the_recorded_frames_are_the_emulated_size_on_a_real_recording():
    """#110's symptom was PIXELS — ffprobe said 1280x720 — so the closing evidence has to be the
    produced video, not the kwargs that ask for it."""
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe not installed")
    mgr = _mgr()
    try:
        await mgr.ensure_ready()
    except Exception as exc:
        pytest.skip(f"no launchable chromium: {exc}")
    try:
        await mgr.emulate_device(device="iPhone 13")
        await mgr.start_recording()
        page = await mgr.get_page()
        await page.set_content("<body style='background:#0af'>hello</body>")
        await page.wait_for_timeout(400)
        video = await mgr.stop_recording()
        assert video, "no video produced"

        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "clip.webm"
            f.write_bytes(video)
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=width,height", "-of", "csv=p=0", str(f)],
                capture_output=True, text=True, timeout=30,
            ).stdout.strip()
        w, h = (int(v) for v in out.split(",")[:2])
        assert (w, h) != (1280, 720), "recorded the desktop default again"
        assert w < 500, f"frames are {w}x{h}, not the emulated mobile viewport"
    finally:
        await mgr.close()
