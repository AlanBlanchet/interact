"""A page that crashes (Playwright's "crash" event — renderer OOM/killed, a heavy evaluate_js is
a common trigger) must be REPORTED, not silently left as a dead about:blank tab the next call
acts on as if nothing happened (#127). Mock-only — no real Chromium needed for this logic."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from interact.browser import BrowserManager
from interact.config import Config


def _mgr() -> BrowserManager:
    return BrowserManager(Config())


def _fake_page(url: str = "https://example.com/heavy") -> MagicMock:
    page = MagicMock()
    page.url = url
    page.on = MagicMock()
    page.close = AsyncMock()
    page.is_closed.return_value = False
    return page


def test_attach_page_listeners_registers_a_crash_handler():
    mgr = _mgr()
    page = _fake_page()
    mgr._attach_page_listeners(page)
    events = [call.args[0] for call in page.on.call_args_list]
    assert "crash" in events, "the page must be listened for a Playwright crash, not just dialog/console"


def test_on_crash_records_a_reason_naming_the_page():
    mgr = _mgr()
    page = _fake_page(url="https://heavy.example/big-table")
    mgr._on_crash(page)
    reason = mgr._crashed_pages[id(page)]
    assert "crash" in reason.lower()
    assert "heavy.example" in reason


def test_on_crash_survives_unreadable_url():
    """The crashed page itself may refuse even a `.url` read — must not raise out of the handler."""
    mgr = _mgr()
    page = MagicMock()
    type(page).url = property(lambda self: (_ for _ in ()).throw(RuntimeError("gone")))
    mgr._on_crash(page)  # must not raise
    assert id(page) in mgr._crashed_pages


@pytest.mark.asyncio
async def test_get_page_raises_on_a_crashed_tab_instead_of_returning_it():
    """Before the fix, get_page returned the dead about:blank page with no signal anything had
    happened — the next evaluate_js/screenshot silently acted on a crashed tab (#127)."""
    mgr = _mgr()
    page = _fake_page()
    mgr._ensure_open_tab = AsyncMock()
    mgr._context = SimpleNamespace(pages=[page])

    mgr._on_crash(page)  # simulate Playwright firing the crash event on this page

    with pytest.raises(RuntimeError, match="crashed"):
        await mgr.get_page()


@pytest.mark.asyncio
async def test_get_page_unaffected_for_a_healthy_tab():
    mgr = _mgr()
    page = _fake_page()
    mgr._ensure_open_tab = AsyncMock()
    mgr._context = SimpleNamespace(pages=[page])

    assert await mgr.get_page() is page


@pytest.mark.asyncio
async def test_close_tab_clears_the_crash_record():
    """A crash record must not outlive the tab it describes — closing it and opening a fresh tab
    that happens to reuse the same freed id() must never inherit a stale crash."""
    mgr = _mgr()
    page = _fake_page()
    mgr._on_crash(page)
    assert id(page) in mgr._crashed_pages

    mgr._context = SimpleNamespace(pages=[page])
    mgr._active_tab = 0
    await mgr.close_tab(0)

    assert id(page) not in mgr._crashed_pages
    page.close.assert_awaited_once()
