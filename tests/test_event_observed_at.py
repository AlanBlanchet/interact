"""Events carried no time at all, so nothing downstream could tell working from stopped.

`AgentEvent` had kind/text/tool/from_run/raw_index and an explicit note that "the vendor writes no
timestamps". The panel's own reader promised "when, and what" and delivered only what. The visible
consequence: idleness had to be derived from the run's START time, so an agent that had been
working for two minutes was stamped HELD and drawn asleep — and the harder it worked the deader
the building looked.

interact cannot know when the agent acted, but it OBSERVES the stream, so it knows when it first
saw a line. That is the honest clock for a watched workplace, and it is the one being stamped.
"""

import json

import pytest

from interact.agents import registry
from interact.agents.events import AgentEvent


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "agents_dir", lambda: tmp_path)


def _mirrored(run_id: str) -> list[dict]:
    text = registry.events_path(run_id).read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_an_event_is_stamped_when_interact_first_sees_it(monkeypatch):
    monkeypatch.setattr(registry.time, "time", lambda: 1000.0)
    registry._mirror_normalised("r", [AgentEvent(kind="text", text="one")])

    assert _mirrored("r")[0]["at"] == 1000.0


def test_an_event_keeps_the_time_it_was_FIRST_seen(monkeypatch):
    """The mirror is rewritten wholesale from a re-parse on every pass. Stamping the clock of the
    moment would move every event's time forward each time, which is the opposite of a timestamp."""
    monkeypatch.setattr(registry.time, "time", lambda: 1000.0)
    registry._mirror_normalised("r", [AgentEvent(kind="text", text="one")])

    monkeypatch.setattr(registry.time, "time", lambda: 2500.0)
    registry._mirror_normalised("r", [
        AgentEvent(kind="text", text="one"),
        AgentEvent(kind="tool", tool="Read", tool_input="a.py"),
    ])

    out = _mirrored("r")
    assert out[0]["at"] == 1000.0, "an event already seen was re-stamped with a later clock"
    assert out[1]["at"] == 2500.0, "a newly observed event takes the clock of the moment"


def test_re_mirroring_an_unchanged_stream_rewrites_nothing(monkeypatch):
    """Carrying the stamps forward is also what keeps a settled run free: if every pass re-stamped,
    the payload would differ every time and the panel would re-read a finished run forever."""
    monkeypatch.setattr(registry.time, "time", lambda: 1000.0)
    events = [AgentEvent(kind="text", text="one")]
    registry._mirror_normalised("r", events)
    before = registry.events_path("r").stat().st_mtime_ns

    monkeypatch.setattr(registry.time, "time", lambda: 9999.0)
    registry._mirror_normalised("r", events)

    assert registry.events_path("r").stat().st_mtime_ns == before
