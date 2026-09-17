"""#138, #139, #140, #147, #149, #162 — the run_actions batch used to die on its first surprise:

one failing step raised straight out of `_run_actions_browser`, discarding every earlier step's
report (#139) and aborting every step still queued (#138). A 0-match selector's error pointed the
agent at a SEPARATE get_interactive_elements call instead of just showing what IS on the page
(#140). A `wait_for` timeout said "check the page state" and attached none (#147). `navigate`
collapsed an unreachable target and an interact-side failure into the same generic ValueError
(#149). `sleep` capped at 30s, too short for a slow app start (#162).

Real Chromium (headless, no VLM/key) for anything that needs a live page; self-skips where no
browser is provisioned. The classification tests use synthetic Playwright-shaped error text so
they stay deterministic and network-free.
"""

import pytest
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

from interact.actions import EvaluateJsAction, ScreenshotAction, WaitForAction
from interact.actions.dispatch import _classify_navigate_failure, _execute_browser_action, _run_actions_browser
from interact.actions.models import SleepAction, _click_selector
from interact.browser import BrowserManager
from interact.config import Config


def _mgr() -> BrowserManager:
    return BrowserManager(Config(headless=True, browser_type="chromium"))


async def _ready(mgr: BrowserManager):
    try:
        await mgr.ensure_ready()
    except Exception as exc:  # no browser provisioned (bare CI)
        pytest.skip(f"no launchable chromium: {exc}")
    page = await mgr.get_page()
    return page


class _Boom:
    type = "navigate"
    url = "https://example.invalid/"

    def __init__(self, message: str, *, timeout: bool = False):
        self._message = message
        self._timeout = timeout

    async def execute(self, page):
        if self._timeout:
            raise PlaywrightTimeout(self._message)
        raise PlaywrightError(self._message)


# ---------------------------------------------------------------------------------- #139 / #138


@pytest.mark.asyncio
async def test_a_failing_step_keeps_earlier_reports_and_the_batch_keeps_going():
    mgr = _mgr()
    try:
        page = await _ready(mgr)
        await page.set_content("<h1>hi</h1>")
        out = await _run_actions_browser(
            mgr,
            [
                ScreenshotAction(),
                EvaluateJsAction(script="throw new Error('boom')"),
                ScreenshotAction(),
            ],
            None, None, None, "default",
        )
        assert "Step 1" in out  # earlier result survived (#139)
        assert "Step 2" in out and "ERROR" in out and "boom" in out  # failing step reports, not raises
        assert "Step 3" in out  # batch kept going after the failure (#138)
        assert "Final state" in out  # tail summary still built, not lost with the exception
    finally:
        await mgr.close()


# ------------------------------------------------------------------------------------------ #140


@pytest.mark.asyncio
async def test_zero_match_selector_embeds_closest_candidates_not_a_separate_call():
    mgr = _mgr()
    try:
        page = await _ready(mgr)
        await page.set_content('<button id="save">Save changes</button>')
        with pytest.raises(ValueError) as exc:
            await _click_selector(page, "#does-not-exist")
        msg = str(exc.value)
        assert "0 matched" in msg
        assert "Closest candidates" in msg
        assert "Save changes" in msg  # the actual candidate, embedded — not a pointer to go look
    finally:
        await mgr.close()


# ------------------------------------------------------------------------------------------ #147


@pytest.mark.asyncio
async def test_wait_for_timeout_attaches_the_final_page_state():
    mgr = _mgr()
    try:
        page = await _ready(mgr)
        await page.set_content("<title>Checkout</title><body>Cart is empty</body>")
        with pytest.raises(ValueError) as exc:
            await _execute_browser_action(
                WaitForAction(text="never-appears-xyz", timeout=200), page
            )
        msg = str(exc.value)
        assert "Page state:" in msg
        assert "Cart is empty" in msg  # the actual page content, not a pointer to go check it
    finally:
        await mgr.close()


# ------------------------------------------------------------------------------------------ #149


@pytest.mark.parametrize(
    "message,timed_out,expect",
    [
        ("page.goto: net::ERR_NAME_NOT_RESOLVED at https://x/", False, "unreachable"),
        ("page.goto: net::ERR_CONNECTION_REFUSED at https://x/", False, "unreachable"),
        ("page.goto: net::ERR_CERT_AUTHORITY_INVALID at https://x/", False, "unreachable"),
        ("", True, "unreachable"),  # navigation timeout
    ],
)
def test_navigate_failure_classifies_target_unreachable(message, timed_out, expect):
    msg = _classify_navigate_failure("https://x/", message, timed_out=timed_out)
    assert expect in msg
    assert "not interact" in msg


def test_navigate_failure_classifies_interact_side_separately():
    msg = _classify_navigate_failure("https://x/", "some internal playwright glitch", timed_out=False)
    assert "interact's side" in msg
    assert "unreachable" not in msg


@pytest.mark.asyncio
async def test_navigate_error_path_uses_the_classifier_not_a_generic_valueerror():
    action = _Boom("page.goto: net::ERR_CONNECTION_REFUSED at https://example.invalid/")
    with pytest.raises(ValueError, match="unreachable"):
        await _execute_browser_action(action, page=None)


# ------------------------------------------------------------------------------------------ #162


def test_sleep_duration_ceiling_covers_a_slow_app_start():
    SleepAction(duration=180)  # would have been rejected under the old le=30
    with pytest.raises(ValueError):
        SleepAction(duration=301)
