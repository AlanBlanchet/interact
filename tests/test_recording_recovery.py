"""A recording that fails to START must not leave the session unable to record ever again.

Found in real client logs, not in the suite: three `record(start=True)` calls died with
`Page.goto: Timeout exceeded`, and the next one came back "Already recording — call
stop_recording first". `start_recording` sets `_recording_dir` BEFORE re-navigating the fresh
context, so a slow page bricks recording for the rest of that session.

The re-navigation is also the wrong thing to fail on. By the time it runs the recording context
already exists and is capturing; losing the whole recording because the page was slow to come
back trades something valuable for something cosmetic.
"""

import pytest

from interact.browser import BrowserManager
from interact.config import Config


class _Page:
    url = "http://127.0.0.1:3000/slow"

    def __init__(self, goto_fails: bool):
        self._goto_fails = goto_fails

    async def goto(self, url):
        if self._goto_fails:
            raise TimeoutError("Page.goto: Timeout 30000ms exceeded.")


class _Context:
    def __init__(self, page):
        self.pages = [page]

    async def cookies(self):
        return []

    async def close(self):
        pass

    async def add_cookies(self, c):
        pass


def _mgr(goto_fails: bool, new_context_fails: bool = False) -> BrowserManager:
    mgr = BrowserManager(Config(headless=True, browser_type="chromium"))
    page = _Page(goto_fails)
    mgr._context = _Context(page)

    async def ready():
        return None

    async def new_context(*a, **k):
        if new_context_fails:
            raise RuntimeError("browser died")
        mgr._context = _Context(page)

    mgr.ensure_ready = ready
    mgr._new_context = new_context
    mgr.reapply_media = ready
    return mgr


@pytest.mark.asyncio
async def test_a_slow_page_does_not_lose_the_recording():
    mgr = _mgr(goto_fails=True)

    url, trouble = await mgr.start_recording()  # already capturing; a slow reload is not fatal

    assert mgr.is_recording, "the recording was thrown away because the page was slow"
    assert trouble and "could not return to" in trouble, (
        "the caller was told nothing: a warning in the server's log is not the tool result the "
        f"agent reads — got {trouble!r}"
    )


@pytest.mark.asyncio
async def test_a_failed_start_leaves_the_session_able_to_try_again():
    mgr = _mgr(goto_fails=False, new_context_fails=True)

    with pytest.raises(RuntimeError, match="browser died"):
        await mgr.start_recording()

    assert not mgr.is_recording, (
        "a start that never completed still claims to be recording, so every later attempt is "
        "refused with 'Already recording' for the life of the session"
    )


@pytest.mark.asyncio
async def test_it_reports_where_the_page_actually_landed():
    """`record(start=True)` answers with "Current URL: …", and after a failed restore the page is
    NOT there — the difference between a caller that re-navigates and one that acts on a page it
    only thinks it is on.

    An earlier version of this test set the SAME page's url to about:blank, which made
    `start_recording` skip the restore entirely and pass against the unfixed code. The rebuild
    gives the session a FRESH page sitting at about:blank, which is what really happens, so the
    old code would answer with the URL it asked for and the new one answers with where it is.
    """
    mgr = _mgr(goto_fails=True)
    fresh = _Page(goto_fails=True)
    fresh.url = "about:blank"

    async def new_context(*a, **k):
        mgr._context = _Context(fresh)

    mgr._new_context = new_context

    assert (await mgr.start_recording())[0] == "about:blank"
