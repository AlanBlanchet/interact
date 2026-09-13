"""Public audit issues #122/#133/#135: exercise shared runtime boundaries without providers."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from interact.desktop import DesktopElement
from interact.formats import CoordFormat


@pytest.mark.parametrize('entry', [
    {'left': 100, 'top': 200, 'width': 300, 'height': 100},
    {'x': 100, 'y': 200, 'widht': 300, 'height': 100},
    {'x': 100, 'y': 200, 'ww': 300, 'h': 100},
])
def test_xywh_aliases_preserve_pixels_and_normalized_coordinates(entry):
    parsed = DesktopElement.parse_vlm(json.dumps([entry]))
    assert parsed is not None
    assert (parsed[0].x, parsed[0].y, parsed[0].w, parsed[0].h) == (100, 200, 300, 100)
    scaled = CoordFormat(normalized=True).parse(json.dumps([entry]), 800, 600)
    assert scaled is not None
    assert (scaled[0].x, scaled[0].y, scaled[0].w, scaled[0].h) == (80, 120, 240, 60)


def test_xywh_unrelated_or_invalid_geometry_is_not_guessed():
    for entry in ({'color': [1, 2, 3, 4]}, {'x': 1, 'y': 2, 'width': 'bad', 'height': 4}):
        assert DesktopElement.parse_vlm(json.dumps([entry])) is None
        assert CoordFormat().parse(json.dumps([entry]), 800, 600) is None


@pytest.mark.asyncio
async def test_desktop_waits_before_capture_after_input_and_before_final_state(monkeypatch):
    import interact.server as srv
    from interact.actions import ScreenshotAction, KeyPressAction
    from interact.actions import dispatch

    events = []
    async def sleep(seconds):
        events.append(('wait', seconds))
    async def capture(*args, **kwargs):
        events.append(('capture', None))
        return b'png', 'captured'
    async def key(value):
        events.append(('key', value))
    win = SimpleNamespace(wid=1, name='fixture', w=800, h=600, capture=lambda: b'png', press_key=key)
    monkeypatch.setattr(dispatch.asyncio, 'sleep', sleep)
    monkeypatch.setattr(srv, '_capture_desktop', capture)
    monkeypatch.setattr(srv, '_desktop_label', lambda win: 'fixture')
    await dispatch._run_actions_desktop(win, [ScreenshotAction(wait='1s'), KeyPressAction(key='a', wait='2s')], 'final', wait='3s')
    assert events == [('wait', 1), ('capture', None), ('wait', .1), ('key', 'a'), ('wait', 2), ('wait', .1), ('wait', 3), ('capture', None)]


@pytest.mark.asyncio
async def test_desktop_selector_wait_refuses_before_sending_input(monkeypatch):
    import interact.server as srv
    from interact.actions import KeyPressAction
    from interact.actions import dispatch

    win = SimpleNamespace(wid=1, name='fixture', w=800, h=600, capture=lambda: b'png', press_key=AsyncMock())
    monkeypatch.setattr(srv, '_desktop_label', lambda win: 'fixture')
    result = await dispatch._run_actions_desktop(win, [KeyPressAction(key='a', wait='#ready')], None)
    assert 'duration' in result
    win.press_key.assert_not_called()


@pytest.mark.asyncio
async def test_browser_recording_keeps_requested_fps_until_stop(monkeypatch):
    from interact.browser import BrowserManager
    from interact.config import Config
    from interact.server import tools_desktop
    from interact.vision.types import RecordingResult, RecordingCapture, MediaAnalysis

    mgr = BrowserManager(Config())
    monkeypatch.setattr(mgr, 'ensure_ready', AsyncMock())
    monkeypatch.setattr(mgr, '_rebuild_context', AsyncMock(return_value=('about:blank', None)))
    captured = []
    async def response(video, **kwargs):
        captured.append(kwargs['fps'])
        return RecordingResult(
            capture=RecordingCapture(status='captured', requested_fps=kwargs['fps'],
                                     timestamp_basis='derived_cadence', observation='indeterminate'),
            analysis=MediaAnalysis(status='not_requested', eligible=None,
                                   attempted=False, input_kind='none'),
        )
    monkeypatch.setattr(tools_desktop, '_record_response', response)
    monkeypatch.setattr(tools_desktop.targets, '_resolve_target', lambda *args: (None, mgr, None))
    started = await tools_desktop.record(start=True, session='fixture', fps=30)
    assert started.structuredContent['capture']['requested_fps'] == 30
    from pathlib import Path
    Path(mgr._recording_dir.name, 'clip.webm').write_bytes(b'fixture video')
    stopped = await tools_desktop.record(start=False, session='fixture')
    assert stopped.structuredContent['capture']['requested_fps'] == 30
    assert captured == [30]
    assert mgr.recording_requested_fps is None


@pytest.mark.parametrize('entry', [
    {'x': 1, 'y': 2, 'w': 'inf', 'h': 3},
    {'x': 1, 'y': 2, 'widht': 30, 'ww': 40, 'h': 3},
])
def test_xywh_nonfinite_and_ambiguous_typos_are_refused(entry):
    assert DesktopElement.parse_vlm(json.dumps([entry])) is None
    assert CoordFormat().parse(json.dumps([entry]), 800, 600) is None


def test_normalized_object_fallback_scales_aliases():
    source = json.dumps({'left': 100, 'top': 200, 'width': 300, 'height': 100})
    parsed = CoordFormat(normalized=True).parse(source, 800, 600)
    assert parsed is not None
    assert (parsed[0].x, parsed[0].y, parsed[0].w, parsed[0].h) == (80, 120, 240, 60)


@pytest.mark.asyncio
async def test_record_metadata_reads_encoded_fps_not_requested_sampling(tmp_path):
    import shutil
    import subprocess
    from interact.server.tools_desktop import _record_metadata

    executable = shutil.which('ffmpeg')
    if executable is None or shutil.which('ffprobe') is None:
        pytest.skip('ffmpeg/ffprobe unavailable')
    clip = tmp_path / 'clip.webm'
    subprocess.run([executable, '-v', 'error', '-f', 'lavfi', '-i',
                    'testsrc=size=32x32:rate=25:duration=1', '-c:v', 'libvpx', str(clip)],
                   check=True, timeout=10)
    rate, duration = await _record_metadata(clip.read_bytes())
    assert rate == 25
    assert duration == pytest.approx(1)


@pytest.mark.asyncio
@pytest.mark.parametrize('payload, expected', [
    ({'streams': [{'avg_frame_rate': '25/1'}], 'format': {'duration': '2.5'}}, (25, 2.5)),
    ({'streams': [{'avg_frame_rate': '0/0'}], 'format': {}}, (None, None)),
    ({'streams': [{'avg_frame_rate': 'NaN'}], 'format': {'duration': 'inf'}}, (None, None)),
    ({'streams': 'invalid shape'}, (None, None)),
])
async def test_record_metadata_validates_probe_boundary(monkeypatch, payload, expected):
    from interact.server import tools_desktop

    process = AsyncMock(return_value=(0, json.dumps(payload).encode(), b''))
    monkeypatch.setattr(tools_desktop, 'run_isolated_process', process)
    assert await tools_desktop._record_metadata(b'fixture clip') == expected
    assert process.call_args.kwargs['timeout'] <= 10


@pytest.mark.asyncio
async def test_record_metadata_failure_does_not_invent_an_effective_rate(monkeypatch):
    from interact.server import tools_desktop

    monkeypatch.setattr(tools_desktop, 'run_isolated_process', AsyncMock(side_effect=TimeoutError))
    assert await tools_desktop._record_metadata(b'fixture clip') == (None, None)


@pytest.mark.asyncio
async def test_failed_browser_recording_drops_requested_fps(monkeypatch):
    from interact.browser import BrowserManager
    from interact.config import Config

    mgr = BrowserManager(Config())
    monkeypatch.setattr(mgr, 'ensure_ready', AsyncMock())
    monkeypatch.setattr(mgr, '_rebuild_context', AsyncMock(side_effect=RuntimeError('fixture failure')))
    with pytest.raises(RuntimeError, match='fixture failure'):
        await mgr.start_recording(fps=30)
    assert mgr.recording_requested_fps is None
    assert not mgr.is_recording


@pytest.mark.asyncio
@pytest.mark.parametrize('fps', [0, -1])
async def test_record_refuses_invalid_fps_before_target_lookup(monkeypatch, fps):
    from interact.server import tools_desktop
    from unittest.mock import Mock

    lookup = Mock(side_effect=AssertionError('must reject before target lookup'))
    monkeypatch.setattr(tools_desktop.targets, '_resolve_target', lookup)
    with pytest.raises(ValueError, match='positive'):
        await tools_desktop.record(fps=fps)
    lookup.assert_not_called()


@pytest.mark.asyncio
async def test_desktop_screenshot_wait_elapses_before_each_capture(monkeypatch):
    import time
    import interact.server as srv
    from interact.actions import ScreenshotAction
    from interact.actions import dispatch

    captured = []
    async def capture(*args, **kwargs):
        captured.append(time.monotonic())
        return b'fixture', 'captured'
    win = SimpleNamespace(wid=1, name='fixture', w=800, h=600, capture=lambda: b'fixture')
    monkeypatch.setattr(srv, '_capture_desktop', capture)
    monkeypatch.setattr(srv, '_desktop_label', lambda win: 'fixture')
    before = time.monotonic()
    await dispatch._run_actions_desktop(
        win, [ScreenshotAction(wait='50ms'), ScreenshotAction(wait='50ms')], None
    )
    assert captured[0] - before >= .045
    assert captured[1] - captured[0] >= .145  # step settle (100 ms) plus next requested wait


@pytest.mark.parametrize('aliases', [
    {'x': 10, 'left': 11},
    {'w': 30, 'width': 40},
    {'x': 10.1, 'left': 10.9},
    {'w': 30, 'widht': 40},
])
def test_conflicting_coordinate_aliases_are_not_actionable(aliases):
    entry = {'x': 10, 'y': 20, 'w': 30, 'h': 40, **aliases}
    source = json.dumps([entry])
    assert DesktopElement.parse_vlm(source) is None
    assert CoordFormat(normalized=True).parse(source, 800, 600) is None


def test_equivalent_coordinate_aliases_agree():
    entry = {'x': 10, 'left': '10', 'y': 20, 'top': 20, 'w': 30, 'width': 30, 'h': 40, 'height': 40}
    element = DesktopElement.from_vlm_dict(entry, 1)
    assert (element.x, element.y, element.w, element.h) == (10, 20, 30, 40)


def test_unrelated_near_spelling_is_not_a_coordinate():
    source = json.dumps([{'x': 10, 'y': 20, 'w': 30, 'weight': 40}])
    assert DesktopElement.parse_vlm(source) is None
    assert CoordFormat().parse(source, 800, 600) is None
