"""#112: a `screenshot(query=...)` on a desktop window answered with the agent's own action text
("press ctrl+shift+p") wrapped in a full-frame bounding box, as if it had read it on screen.

The window had in fact CRASHED and the capture came back all black. Handed an empty image, the
model reconstructed something plausible from the prompt instead of reporting that there was
nothing to see — so the captioned path reported nothing-unusual while the app was dead. That is
the failure mode the reporter rightly called worse than an error: a well-formed, plausible,
completely wrong answer that reads as a real observation.

A blank frame is deterministically detectable, so it never needs a model's opinion. Detect it,
say so, and don't spend a VLM call inventing an answer about an empty image.
"""

import io

import pytest
from PIL import Image

from interact.vision.measure import blank_frame_reason


def _png(fill=(0, 0, 0), size=(320, 200), speckle: int = 0) -> bytes:
    img = Image.new("RGB", size, fill)
    for i in range(speckle):
        img.putpixel((i % size[0], (i * 7) % size[1]), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _varied_png(size=(320, 200)) -> bytes:
    img = Image.new("RGB", size)
    for x in range(size[0]):
        for y in range(size[1]):
            img.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_an_all_black_capture_is_reported_blank_with_its_colour():
    reason = blank_frame_reason(_png((0, 0, 0)))
    assert reason and "#000000" in reason, reason


def test_a_white_capture_is_blank_too():
    """A crashed GPU surface grabs black; a blank page grabs white. Both are "nothing to see"."""
    assert blank_frame_reason(_png((255, 255, 255)))


def test_a_few_stray_pixels_do_not_make_an_empty_frame_look_real():
    """A dead window often carries a cursor or a 1px border. Still nothing to caption."""
    assert blank_frame_reason(_png((0, 0, 0), speckle=40))


def test_a_real_screenful_is_not_blank():
    assert blank_frame_reason(_varied_png()) is None


@pytest.mark.asyncio
async def test_a_blank_capture_is_never_sent_to_the_vlm(monkeypatch):
    import interact.server as srv

    async def boom(*a, **k):  # spending a call to caption an empty image is the bug
        raise AssertionError("the VLM was asked to describe a blank frame")

    monkeypatch.setattr(srv.vlm, "_vlm", boom)
    out = await srv.vlm._media_response(_png((0, 0, 0)), "Desktop window: Code (1920x1080)", "what is on screen?")
    assert out and out.startswith("ERROR:"), out
    assert "blank" in out.lower()


@pytest.mark.asyncio
async def test_a_real_frame_still_reaches_the_vlm(monkeypatch):
    import interact.server as srv

    from interact.vision import VLMResult

    async def ok(*a, **k):
        return VLMResult(text="a toolbar and a sidebar", elapsed=0.1, model="test")

    monkeypatch.setattr(srv.vlm, "_vlm", ok)
    out = await srv.vlm._media_response(_varied_png(), "ctx", "what is on screen?")
    assert out and "toolbar" in out


# --- #113: the same emptiness has to be surfaced on the UNCAPTIONED path too ---
#
# A per-window capture of a CRASHED VS Code window returned an entirely black 1440x900 PNG with no
# comment. Black is indistinguishable from "still loading", so the reporter waited and retried —
# two capture rounds and ~30s — while `target="screen"` would have shown VS Code's own "window
# terminated unexpectedly" modal immediately. They asked for exactly one line in the tool result.


@pytest.mark.asyncio
async def test_a_black_window_capture_says_so_even_with_no_query(monkeypatch):
    import interact.server as srv

    class DeadWindow:
        wid, name, w, h = 33554476, "interact - Visual Studio Code", 1440, 900

        def capture(self):
            return _png((0, 0, 0), size=(240, 150))

    monkeypatch.setattr(srv.targets, "_resolve_target", lambda *a, **k: (DeadWindow(), None, None))

    out = await srv.tools_vision.screenshot(target="interact - Visual Studio Code")
    text = out[0] if isinstance(out, list) else out

    assert "#000000" in text, text
    assert 'target="screen"' in text, "the fallback that reveals the crash must be named"


@pytest.mark.asyncio
async def test_a_normal_window_capture_carries_no_such_note(monkeypatch):
    import interact.server as srv

    class LiveWindow:
        wid, name, w, h = 1, "Code", 240, 150

        def capture(self):
            return _varied_png(size=(240, 150))

    monkeypatch.setattr(srv.targets, "_resolve_target", lambda *a, **k: (LiveWindow(), None, None))

    out = await srv.tools_vision.screenshot(target="Code")
    text = out[0] if isinstance(out, list) else out
    assert "uniform" not in text.lower(), text


# --- the header fast path must not create a blind spot at small sizes ---
#
# Screening on encoded bytes-per-pixel is only valid while the PNG's fixed header is negligible
# against the pixel count. It is not, on a small crop: an 8x8 blank frame encodes at 1.08 b/px,
# twenty times the threshold, so the very check that makes this affordable on a 4K grab was
# skipping every small one. `screenshot(element=N, query=...)` crops single widgets — an icon, a
# button — which is exactly the size where a blank frame stopped being detected.


@pytest.mark.parametrize("size", [(8, 8), (16, 16), (24, 24), (32, 32), (48, 48), (120, 90)])
def test_a_blank_crop_is_detected_at_any_size(size):
    assert blank_frame_reason(_png((0, 0, 0), size=size)), f"{size[0]}x{size[1]} blank frame missed"


@pytest.mark.parametrize("size", [(16, 16), (64, 64), (200, 200)])
def test_a_small_busy_crop_is_still_not_blank(size):
    assert blank_frame_reason(_varied_png(size=size)) is None
