"""#109: a screenshot taken right after a JS-driven scroll showed the PRE-scroll pixels, while
`window.scrollY` already read the new value — so the DOM was right and the capture was stale.

The reporter hit it with `scroll-behavior: smooth` (a Tailwind reset sets it globally): the
`window.scrollTo` promise resolves immediately and the browser then animates for a few hundred
milliseconds, so anything that captures at once photographs the old position. It cost them ~10
tool calls, because a stale photo of a real app looks exactly like the app reverting your change.

The fix waits for the page to stop moving before the shutter opens, so it covers the whole class
(smooth scroll, a JS mutation that reflows, an in-flight transition), not just this repro.
"""

import pytest
from PIL import Image
import io
import base64

from interact.browser import BrowserManager
from interact.config import Config
from interact.state import PageState

# Top screen is red, the one below it blue. If the capture is stale we photograph red.
PAGE = (
    "<style>html{scroll-behavior:smooth}body{margin:0}div{height:100vh}</style>"
    "<div style='background:#ff0000'></div><div style='background:#0000ff'></div>"
)


def _centre(b64: str) -> tuple[int, int, int]:
    img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    return img.getpixel((img.width // 2, img.height // 2))


@pytest.mark.asyncio
async def test_capture_waits_for_a_smooth_scroll_to_land():
    mgr = BrowserManager(Config(headless=True, browser_type="chromium"))
    try:
        await mgr.ensure_ready()
    except Exception as exc:  # no launchable chromium (bare CI)
        pytest.skip(f"no launchable chromium: {exc}")
    try:
        page = await mgr.get_page()
        await page.set_content(PAGE)
        # The premise, asserted rather than assumed: set_content returns before layout is
        # necessarily tall enough to scroll, and a document that cannot scroll would photograph
        # the red screen for a reason that has nothing to do with settling. Under a loaded
        # machine that is exactly what happened, and the failure looked like the fix regressing.
        await page.wait_for_function("() => document.body.scrollHeight > window.innerHeight + 10")
        await page.evaluate("() => window.scrollTo(0, window.innerHeight)")
        state = await PageState.capture(page)  # no sleep: the capture must settle itself
        landed = await page.evaluate("() => window.scrollY")
        assert landed > 0, "the page never scrolled — the test's setup failed, not the capture"
        r, g, b = _centre(state.screenshot_base64)
        assert b > 200 and r < 60, f"captured the pre-scroll screen: rgb({r},{g},{b})"
    finally:
        await mgr.close()


@pytest.mark.asyncio
async def test_capture_does_not_hang_on_a_page_that_never_stops_moving():
    """A carousel/marquee scrolls forever. Settling must give up, not block the tool."""
    mgr = BrowserManager(Config(headless=True, browser_type="chromium"))
    try:
        await mgr.ensure_ready()
    except Exception as exc:
        pytest.skip(f"no launchable chromium: {exc}")
    try:
        page = await mgr.get_page()
        await page.set_content(
            "<style>body{margin:0}div{height:400vh}</style><div></div>"
            "<script>setInterval(() => window.scrollBy(0, 3), 8)</script>"
        )
        import time

        t0 = time.monotonic()
        await PageState.capture(page)
        assert time.monotonic() - t0 < 3.0, "settling must be bounded on a never-still page"
    finally:
        await mgr.close()


@pytest.mark.asyncio
async def test_an_element_capture_settles_too():
    """`screenshot(selector=...)` and `get_interactive_elements` photograph through their own
    paths, not through PageState.capture — so fixing only the funnel leaves the same staleness
    reachable two other ways. Worse for the annotated capture, where boxes are drawn at
    coordinates scanned before the page finished moving."""
    from interact.server import capture as cap

    mgr = BrowserManager(Config(headless=True, browser_type="chromium"))
    try:
        await mgr.ensure_ready()
    except Exception as exc:
        pytest.skip(f"no launchable chromium: {exc}")
    try:
        page = await mgr.get_page()
        await page.set_content(
            "<style>html{scroll-behavior:smooth}body{margin:0}div{height:100vh}</style>"
            "<div style='background:#ff0000'></div>"
            "<div id=target style='background:#0000ff'></div>"
        )
        await page.wait_for_function("() => document.body.scrollHeight > window.innerHeight + 10")
        await page.evaluate("() => window.scrollTo(0, window.innerHeight)")
        png, _ = await cap._annotate_page(mgr)
        assert await page.evaluate("() => window.scrollY") > 0, "setup failed, not the capture"
        img = Image.open(io.BytesIO(png)).convert("RGB")
        r, g, b = img.getpixel((img.width // 2, img.height // 2))
        assert b > 200 and r < 60, f"annotated capture is pre-scroll: rgb({r},{g},{b})"
    finally:
        await mgr.close()
