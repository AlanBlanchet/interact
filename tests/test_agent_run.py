"""Spawning and supervising a run end to end, against a REAL subprocess.

The fake provider emits the same JSON dialect the captured Claude stream uses, so this exercises
the whole path — spawn, stream, normalise, persist, reap — without spending a token or depending
on a vendor binary being installed.
"""

import asyncio
import json
import sys

import pytest

from interact.agents import registry as reg
from interact.agents.events import AgentEvent
from interact.agents.providers import AgentProvider
from interact.agents.run import mesh_config, run_agent


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    # A run's raw stream is parsed by the provider named on its record, looked up in the global
    # registry — so a test double has to be registered exactly like a real provider is.
    from interact.agents.providers import PROVIDERS

    monkeypatch.setitem(PROVIDERS, "fake", _FakeProvider())
    monkeypatch.setitem(PROVIDERS, "crash", _CrashingProvider())
    yield


class _FakeProvider(AgentProvider):
    """Emits two events then exits — the shape of a real stream, none of the cost."""

    name = "fake"
    binary = sys.executable
    script = (
        'import json,sys\n'
        'print(json.dumps({"type":"system","subtype":"init","cwd":"/tmp","tools":[],'
        '"session_id":"SID"}), flush=True)\n'
        'print(json.dumps({"type":"result","subtype":"success","is_error":False,'
        '"total_cost_usd":0.5,"usage":{"output_tokens":7},"session_id":"SID"}), flush=True)\n'
    )

    def available(self):
        return True

    def command(self, task, *, cwd, model, mcp_config, run_id, agent=None):
        return [sys.executable, "-c", self.script]

    def parse(self, line):
        from interact.agents.providers import ClaudeCodeProvider
        return ClaudeCodeProvider().parse(line)


class _CrashingProvider(_FakeProvider):
    name = "crash"

    def command(self, task, *, cwd, model, mcp_config, run_id, agent=None):
        return [sys.executable, "-c", "import sys; sys.exit(3)"]


@pytest.mark.asyncio
async def test_a_run_streams_its_events_and_records_its_cost(tmp_path):
    run = await run_agent(_FakeProvider(), "do a thing", name="worker", cwd=str(tmp_path))
    await asyncio.wait_for(run.wait(), timeout=30)

    events = reg.read_events(run.run_id)
    assert [e.kind for e in events] == ["started", "done"]
    listed = [r for r in reg.list_runs() if r.run_id == run.run_id][0]
    assert listed.status == "done" and listed.exit_code == 0
    assert listed.cost_usd == pytest.approx(0.5)
    assert listed.last == "done"


@pytest.mark.asyncio
async def test_a_failing_run_is_recorded_as_failed(tmp_path):
    run = await run_agent(_CrashingProvider(), "boom", name="w", cwd=str(tmp_path))
    await asyncio.wait_for(run.wait(), timeout=30)
    assert [r for r in reg.list_runs() if r.run_id == run.run_id][0].status == "failed"


@pytest.mark.asyncio
async def test_the_run_appears_in_the_registry_while_still_alive(tmp_path):
    """The supervisor must see a run BEFORE it finishes — otherwise there is nothing to watch."""
    slow = _FakeProvider()
    slow.command = lambda *a, **k: [sys.executable, "-c", "import time; time.sleep(5)"]
    run = await run_agent(slow, "slow", name="w", cwd=str(tmp_path))
    try:
        listed = [r for r in reg.list_runs() if r.run_id == run.run_id]
        assert listed and listed[0].status == "running"
    finally:
        reg.stop(run.run_id)


@pytest.mark.asyncio
async def test_a_child_is_attributed_to_its_parent(tmp_path):
    parent = await run_agent(_FakeProvider(), "p", name="parent", cwd=str(tmp_path))
    child = await run_agent(_FakeProvider(), "c", name="child", cwd=str(tmp_path),
                            parent_run_id=parent.run_id)
    await asyncio.wait_for(parent.wait(), timeout=30)
    await asyncio.wait_for(child.wait(), timeout=30)
    assert [c.run_id for c in reg.children_of(parent.run_id)] == [child.run_id]


# ── the mesh config: how a spawned agent reaches back into interact ──────────────────────────


def test_the_mesh_config_declares_interact_as_an_mcp_server():
    import json

    cfg = json.loads(mesh_config(run_id="r1"))
    assert "interact" in cfg["mcpServers"]
    entry = cfg["mcpServers"]["interact"]
    assert entry["command"] and isinstance(entry["args"], list)


def test_the_mesh_config_tags_the_child_so_its_own_spawns_are_attributed():
    import json

    cfg = json.loads(mesh_config(run_id="r1"))
    env = cfg["mcpServers"]["interact"]["env"]
    # Without this the tree is flat and "who started this agent" is unanswerable.
    assert env["INTERACT_PARENT_RUN_ID"] == "r1"


def test_the_mesh_config_carries_no_credential():
    cfg = mesh_config(run_id="r1").lower()
    for banned in ("api_key", "apikey", "token", "oauth", "secret"):
        assert banned not in cfg, f"{banned!r} must never be handed to a spawned agent"


@pytest.mark.asyncio
async def test_events_survive_the_spawning_loop_ending(tmp_path):
    """The defect this replaced: the event stream ran on the CALLER's event loop, so a caller that
    spawned and returned lost every event — and the run then looked HEALTHY (status done, exit 0,
    no cost, no activity), which is worse than looking crashed. The child writes its own stream to
    disk now, so nothing is lost when the supervising coroutine goes away."""
    run = await run_agent(_FakeProvider(), "t", name="w", cwd=str(tmp_path))
    run.pump.cancel()  # the caller went away mid-run
    await asyncio.wait_for(run.process.wait(), timeout=30)

    events = reg.read_events(run.run_id)
    assert [e.kind for e in events] == ["started", "done"], "the stream did not survive"
    listed = [r for r in reg.list_runs() if r.run_id == run.run_id][0]
    assert listed.cost_usd == pytest.approx(0.5), "cost was lost with the supervising task"
    assert listed.last == "done"


# ── Seeing a response as it arrives ─────────────────────────────────────────────────────────
# The child writes only the RAW vendor stream; the normalised copy the VS Code panel reads is
# produced on demand. So while an agent was actually working, the panel saw nothing at all — a
# live run showed "waiting" from start to finish, and "view responses as they come in" was
# impossible by construction.


@pytest.mark.asyncio
async def test_the_normalised_stream_is_kept_current_while_a_run_is_alive(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from interact.agents import registry as reg
    from interact.agents.run import _mirror_while_alive

    reg.register(run_id="r1", name="a", provider="claude", task="t", pid=None)
    raw = reg.raw_events_path("r1")
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(json.dumps({
        "type": "assistant", "session_id": "s",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "first"}]},
    }) + "\n")

    alive = {"value": True}
    task = asyncio.create_task(_mirror_while_alive("r1", lambda: alive["value"], interval=0.02))
    await asyncio.sleep(0.1)
    assert "first" in reg.events_path("r1").read_text(), "the panel reads this file"

    with raw.open("a") as f:
        f.write(json.dumps({
            "type": "assistant", "session_id": "s",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "second"}]},
        }) + "\n")
    await asyncio.sleep(0.1)
    assert "second" in reg.events_path("r1").read_text(), "a later turn must appear without a poke"

    alive["value"] = False
    await asyncio.wait_for(task, timeout=2)


@pytest.mark.asyncio
async def test_the_pump_stops_when_the_run_does(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from interact.agents import registry as reg
    from interact.agents.run import _mirror_while_alive

    reg.register(run_id="r1", name="a", provider="claude", task="t", pid=None)
    task = asyncio.create_task(_mirror_while_alive("r1", lambda: False, interval=0.01))
    await asyncio.wait_for(task, timeout=2)  # must not spin forever on a finished run


@pytest.mark.asyncio
async def test_a_broken_read_never_kills_the_pump(tmp_path, monkeypatch):
    """It runs beside a live agent; a transient read failure must not take the stream down."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from interact.agents import registry as reg
    from interact.agents.run import _mirror_while_alive

    calls = {"n": 0}

    def _boom(run_id):
        calls["n"] += 1
        raise OSError("transient")

    monkeypatch.setattr(reg, "read_events", _boom)
    alive = {"value": True}
    task = asyncio.create_task(_mirror_while_alive("r1", lambda: alive["value"], interval=0.01))
    await asyncio.sleep(0.08)
    alive["value"] = False
    await asyncio.wait_for(task, timeout=2)
    assert calls["n"] > 1, "it kept going after the failure"
