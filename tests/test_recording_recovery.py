"""A recording that fails to START must not leave the session unable to record ever again.

Found in real client logs, not in the suite: three `record(start=True)` calls died with
`Page.goto: Timeout exceeded`, and the next one came back "Already recording — call
stop_recording first". `start_recording` sets `_recording_dir` BEFORE re-navigating the fresh
context, so a slow page bricks recording for the rest of that session.

The re-navigation is also the wrong thing to fail on. By the time it runs the recording context
already exists and is capturing; losing the whole recording because the page was slow to come
back trades something valuable for something cosmetic.

The same context swap has a second way of being silently wrong (#123): it carried COOKIES only, so
a page's localStorage — an app's logged-in / onboarded state — was gone when the page came back.
The agent then recorded a fresh-origin render and read its first-visit banner as a "flash" bug.
"""

import pytest

from interact.browser import BrowserManager
from interact.config import Config

# What Playwright's storage_state() holds: the cookie jar AND each origin's localStorage.
_STATE = {
    "cookies": [],
    "origins": [
        {"origin": "http://127.0.0.1:3000", "localStorage": [{"name": "onboarded", "value": "1"}]}
    ],
}


class _Page:
    url = "http://127.0.0.1:3000/slow"

    def __init__(self, goto_fails: bool):
        self._goto_fails = goto_fails

    async def goto(self, url):
        if self._goto_fails:
            raise TimeoutError("Page.goto: Timeout 30000ms exceeded.")


class _Context:
    def __init__(self, page, built_with: dict | None = None):
        self.pages = [page]
        self.built_with = built_with or {}  # the kwargs _new_context was asked to build it with

    async def storage_state(self):
        return _STATE

    async def close(self):
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
        mgr._context = _Context(page, built_with=k)

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


async def _start(mgr: BrowserManager):
    await mgr.start_recording()


async def _stop(mgr: BrowserManager):
    await mgr.start_recording()
    await mgr.stop_recording()


async def _viewport_change(mgr: BrowserManager):
    await mgr._rebuild_context()  # what emulate_device does


@pytest.mark.asyncio
@pytest.mark.parametrize("swap", [_start, _stop, _viewport_change])
async def test_a_context_swap_carries_the_whole_storage_state(swap):
    """#123: every path that rebuilds the context re-added the old context's COOKIES and nothing
    else, so localStorage was wiped on record(start) AND again on record(stop) — while
    `document.cookie` survived, which is exactly what made the loss look like the page's own doing.
    Playwright's storage_state() carries both; the rebuilt context must be built from it."""
    mgr = _mgr(goto_fails=False)

    await swap(mgr)

    assert mgr._context.built_with.get("storage_state") == _STATE, (
        "the rebuilt context was not given the session's storage state — localStorage is gone"
    )
