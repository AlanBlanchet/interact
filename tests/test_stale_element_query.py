"""#112 (second half): the reporter asked that the analysis path not be able to see text from
outside the frame it is describing — "anything that lets step text leak into 'what is on screen'
makes captions unfalsifiable".

There is a real instance of exactly that. `screenshot(target=<window>, element=N, query=...)`
crops the CURRENT frame at coordinates from a PREVIOUS detection and captions it with that older
widget's role and name, with no freshness check — while the sibling no-query branch right below it
already gates its refs on the frame's content signature (#19). So the model is handed a picture of
one thing labelled as another, which is the ideal setup for the confident wrong answer #112 is about.
"""

import pytest

from interact.desktop import DesktopElement


def test_refs_detected_on_another_frame_are_reported_stale():
    wid = 4242
    DesktopElement.merge_into(wid, [DesktopElement(index=0, x=1, y=2, w=3, h=4, role="button", name="Run")], "sigA")

    assert DesktopElement.stale_for(wid, "sigB") is True, "screen changed → refs describe a gone frame"
    assert DesktopElement.stale_for(wid, "sigA") is False, "same frame → refs still describe it"


def test_a_window_never_detected_is_not_stale():
    """Nothing detected yet is a different situation from a detection that went out of date."""
    assert DesktopElement.stale_for(987654, "sig") is False


@pytest.mark.asyncio
async def test_an_element_query_refuses_stale_refs_instead_of_captioning_the_wrong_crop(monkeypatch):
    import interact.server as srv

    wid = 5150

    class FakeWin:
        def __init__(self):
            self.wid, self.name, self.w, self.h = wid, "Code", 800, 600

        def capture(self):  # a frame that does NOT match the seeded detection
            from tests.test_blank_capture import _varied_png

            return _varied_png()

    DesktopElement.merge_into(
        wid, [DesktopElement(index=0, x=0, y=0, w=10, h=10, role="button", name="Old Button")], "sigOLD"
    )
    monkeypatch.setattr(srv.targets, "_resolve_target", lambda *a, **k: (FakeWin(), None, None))

    async def boom(*a, **k):
        raise AssertionError("captioned a crop using labels from a screen that is gone")

    monkeypatch.setattr(srv.vlm, "_media_response", boom)

    out = await srv.tools_vision.screenshot(target="Code", element=1, query="what is this?")
    assert "ERROR" in out and "get_interactive_elements" in out, out
