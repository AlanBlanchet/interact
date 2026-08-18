"""Playwright's own wording reaches the agent verbatim, and some of it explains nothing.

"Execution context was destroyed, most likely because of a navigation" is accurate and useless:
it names a browser internal, not the thing the caller did wrong or the thing they should do next.
It turned up 12 times in real client logs, always from `evaluate_js` reading the page right as it
navigated. The strict-mode case beside it already gets this treatment (#29); this is the same
move for the other opaque one.
"""

import pytest
from playwright.async_api import Error as PlaywrightError

from interact.actions.dispatch import _execute_browser_action
from interact.actions.models import EvaluateJsAction


class _Boom:
    type = "evaluate_js"

    def __init__(self, message: str):
        self._message = message

    async def execute(self, page):
        raise PlaywrightError(self._message)


@pytest.mark.asyncio
async def test_a_navigation_mid_script_says_what_happened_and_what_to_do():
    action = _Boom("Page.evaluate: Execution context was destroyed, most likely because of a navigation.")

    with pytest.raises(ValueError) as exc:
        await _execute_browser_action(action, page=None)

    msg = str(exc.value)
    assert "navigated" in msg, msg
    assert "wait_for" in msg, "the recovery has to be named, not left to be guessed"


@pytest.mark.asyncio
async def test_an_ordinary_failure_is_still_passed_through_trimmed():
    action = _Boom("Page.evaluate: TypeError: x is not a function\n  at line 1\n  call log follows")

    with pytest.raises(ValueError, match="TypeError: x is not a function"):
        await _execute_browser_action(action, page=None)


@pytest.mark.asyncio
async def test_the_real_action_type_reaches_the_message(monkeypatch):
    """Not only the synthetic stand-in: the same path with the real model class."""

    async def boom(self, page):
        raise PlaywrightError("Execution context was destroyed, most likely because of a navigation.")

    monkeypatch.setattr(EvaluateJsAction, "execute", boom)
    with pytest.raises(ValueError, match="evaluate_js: the page navigated"):
        await _execute_browser_action(EvaluateJsAction(script="return 1"), page=None)
