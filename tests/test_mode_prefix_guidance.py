"""#114: `key_press ctrl+shift+p` opens VS Code's command palette pre-filled with ">", and the
mode lives in that character. `type_text` defaults to clear_first, so typing the command name
alone replaces the ">" too — the palette silently switches to file search and answers "No matching
results", which reads exactly like a mistyped command name. Two different commands hit it and it
cost the caller four round-trips before they worked out the cause.

Deliberately not inferred away: preserving a leading character that "looks like" a mode would mean
this tool carrying one editor's prefix alphabet, and would refuse to clear a field whose content
genuinely begins with it. So the fix is that the tool SAYS so — which is only true while the text
actually reaches the schema an agent reads, hence this test rather than a comment.
"""

import json

import pytest


@pytest.mark.asyncio
async def test_the_mode_prefix_trap_is_in_the_schema_agents_read():
    from interact.server import mcp

    tools = await mcp.list_tools()
    run_actions = next(t for t in tools if t.name == "run_actions")
    schema = json.dumps(run_actions.inputSchema)

    assert "command palette" in schema, "the concrete case an agent will hit is not described"
    assert "clear_first=false" in schema, "the escape hatch is not named"


@pytest.mark.asyncio
async def test_clear_first_still_means_replace_the_whole_field():
    """The documented behaviour, asserted — so a later 'helpful' tweak that starts preserving a
    prefix has to change this test on purpose rather than by accident."""
    from unittest.mock import AsyncMock, MagicMock

    from interact.actions import TypeTextAction

    page = MagicMock()
    page.keyboard.press = AsyncMock()
    page.keyboard.type = AsyncMock()

    await TypeTextAction(text="Interact: Show Team").execute(page)

    page.keyboard.press.assert_awaited_once_with("ControlOrMeta+a")
    page.keyboard.type.assert_awaited_once_with("Interact: Show Team")


@pytest.mark.asyncio
async def test_clear_first_off_appends_instead():
    from unittest.mock import AsyncMock, MagicMock

    from interact.actions import TypeTextAction

    page = MagicMock()
    page.keyboard.press = AsyncMock()
    page.keyboard.type = AsyncMock()

    await TypeTextAction(text="Show Team", clear_first=False).execute(page)

    page.keyboard.press.assert_not_awaited()  # the ">" the shortcut inserted survives
    page.keyboard.type.assert_awaited_once_with("Show Team")
