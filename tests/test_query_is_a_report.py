"""A query answer is a REPORT from the agent's eyes, never an act (#119).

The caller's query went to the model verbatim, with nothing but "Annotated page with N elements"
around it, so "close the dialog" read as an instruction and came back as "Closed." — the agent
then believed something had happened. Every query answer crosses one seam; the framing lives there.
"""

import pytest

import interact.server as srv
from interact.vision.core import VLMResult


@pytest.mark.asyncio
async def test_the_model_is_told_it_can_only_look(monkeypatch):
    seen: dict = {}

    async def capture(data, context, query, *a, **k):
        seen.update(context=context, query=query)
        return VLMResult(text="Element [2] is the dialog's close button, top right, enabled.", model="fake", elapsed=0.1)

    monkeypatch.setattr(srv.vlm, "_vlm", capture)
    out = await srv.vlm._media_response(b"png", "Annotated page with 2 elements:\n[1] OK\n[2] Close", query="close the dialog")
    assert out.text and "close button" in out.text
    assert "only LOOK" in seen["context"] and "never as an action you took" in seen["context"]
    assert "[2] Close" in seen["context"], "the element list must still reach the model"
    assert seen["query"] == "close the dialog", "the caller's words are not rewritten, only framed"
