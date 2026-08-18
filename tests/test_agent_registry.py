"""The run registry: what is running, who started it, what it cost, what it's doing now.

Two properties matter more than the rest.

**Status is DERIVED, never trusted.** A record says "running"; the process may have been killed.
Reading liveness from the pid (the same check `server_registry` uses) means a crashed agent
reports as crashed instead of spinning forever in the UI — the difference between a supervisor
and a decoration.

**The registry is a FIXED path, not debug_dir-relative.** It is cross-process IPC: the CLI
writes, the extension reads, another shell stops a run. If one process had INTERACT_DEBUG_DIR set
and another didn't they would look in different places — exactly the metering bug 0ef5fa4 fixed,
reintroduced at the feature level. `server_registry._runtime_dir` is pinned for the same reason.
"""

import json

import pytest

from interact.agents import registry as reg


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Path.home() reads this on Windows
    monkeypatch.setenv("INTERACT_DEBUG_DIR", str(tmp_path / "somewhere-else"))
    yield


def _record(**kw):
    base = dict(run_id="r1", pid=1, provider="claude", name="tester", task="do it", cwd="/tmp")
    return reg.register(**{**base, **kw})


def test_the_registry_ignores_the_debug_dir_override(tmp_path):
    # It must be findable by a process that never saw INTERACT_DEBUG_DIR.
    assert "somewhere-else" not in str(reg.agents_dir())
    assert reg.agents_dir() == tmp_path / ".interact" / "out" / "agents"


def test_a_registered_run_is_listed():
    _record()
    runs = reg.list_runs()
    assert [r.run_id for r in runs] == ["r1"]
    assert runs[0].name == "tester" and runs[0].provider == "claude"


def test_a_dead_pid_is_reported_as_crashed_not_running(monkeypatch):
    _record(pid=999999)
    monkeypatch.setattr(reg, "_alive", lambda pid: False)
    run = reg.list_runs()[0]
    assert run.status == "crashed", "a record claiming to run must not outlive its process"


def test_a_live_pid_stays_running(monkeypatch):
    _record()
    monkeypatch.setattr(reg, "_alive", lambda pid: True)
    assert reg.list_runs()[0].status == "running"


def test_a_finished_run_keeps_its_recorded_outcome(monkeypatch):
    _record()
    reg.finish("r1", exit_code=0)
    monkeypatch.setattr(reg, "_alive", lambda pid: False)  # long gone, but it finished cleanly
    run = reg.list_runs()[0]
    assert run.status == "done" and run.exit_code == 0


def test_a_nonzero_exit_is_failed(monkeypatch):
    _record()
    reg.finish("r1", exit_code=2)
    monkeypatch.setattr(reg, "_alive", lambda pid: False)
    assert reg.list_runs()[0].status == "failed"


# ── the spawn tree: who launched whom, across providers ──────────────────────────────────────


def test_a_child_records_its_parent():
    _record(run_id="parent")
    _record(run_id="child", parent_run_id="parent", provider="codex")
    tree = {r.run_id: r.parent_run_id for r in reg.list_runs()}
    assert tree == {"parent": None, "child": "parent"}


def test_the_tree_spans_providers():
    # The whole point: a Claude agent starting a Codex agent is an ordinary record, not a
    # special case — they met on MCP.
    _record(run_id="p", provider="claude")
    _record(run_id="c", provider="codex", parent_run_id="p")
    kids = reg.children_of("p")
    assert [k.provider for k in kids] == ["codex"]


# ── events: what it is doing now, and what it cost ───────────────────────────────────────────


def test_the_last_event_is_what_it_is_doing_now():
    _record()
    reg.append_event("r1", reg.AgentEvent(kind="tool", tool="Bash"))
    reg.append_event("r1", reg.AgentEvent(kind="text", text="thinking about it"))
    assert reg.last_event("r1").text == "thinking about it"


def test_cost_totals_come_from_the_events():
    _record()
    reg.append_event("r1", reg.AgentEvent(kind="text", output_tokens=10))
    reg.append_event("r1", reg.AgentEvent(kind="done", cost_usd=0.25, output_tokens=4))
    run = reg.list_runs()[0]
    assert run.cost_usd == pytest.approx(0.25)


def test_a_run_with_no_events_reports_no_cost_not_zero():
    # Zero would read as "free"; unknown is the truth before anything has been reported.
    _record()
    assert reg.list_runs()[0].cost_usd is None


def test_events_survive_a_corrupt_line():
    _record()
    reg.append_event("r1", reg.AgentEvent(kind="text", text="one"))
    (reg.agents_dir() / "r1.jsonl").open("a").write("{ this is not json\n")
    reg.append_event("r1", reg.AgentEvent(kind="text", text="two"))
    assert reg.last_event("r1").text == "two"


# ── seeing agents we did NOT spawn ───────────────────────────────────────────────────────────


def test_foreign_sessions_are_listed_without_duplicating_our_own(monkeypatch):
    """`claude agents --json` sees the user's own interactive windows too — that is what makes
    this a view of the machine. But it also sees the runs WE spawned, so they must not appear
    twice: the vendor's sessionId and our run_id are deliberately the same string."""
    _record(run_id="43840bfe-mine")
    monkeypatch.setattr(reg, "_alive", lambda pid: True)
    monkeypatch.setattr(
        reg, "_discover_foreign",
        lambda: [
            {"sessionId": "43840bfe-mine", "cwd": "/tmp", "kind": "background", "name": "ours"},
            {"sessionId": "other-1", "cwd": "/home/x", "kind": "interactive", "name": "theirs"},
        ],
    )
    runs = reg.list_runs(include_foreign=True)
    ids = [r.run_id for r in runs]
    assert ids.count("43840bfe-mine") == 1, "our own run was listed twice"
    assert "other-1" in ids
    foreign = next(r for r in runs if r.run_id == "other-1")
    assert foreign.foreign is True and foreign.name == "theirs"


def test_foreign_runs_are_excluded_by_default(monkeypatch):
    monkeypatch.setattr(reg, "_discover_foreign", lambda: [{"sessionId": "x", "name": "n"}])
    assert reg.list_runs() == []


def test_stopping_records_the_outcome(monkeypatch):
    _record()
    killed = []
    monkeypatch.setattr(reg, "_terminate", lambda pid: killed.append(pid) or True)
    assert reg.stop("r1") is True
    monkeypatch.setattr(reg, "_alive", lambda pid: False)
    assert reg.list_runs()[0].status == "stopped"
    assert killed == [1]


def test_stopping_an_unknown_run_is_false_not_an_exception():
    assert reg.stop("nope") is False


def test_a_corrupt_record_does_not_break_the_listing():
    _record()
    (reg.agents_dir() / "broken.json").write_text("{ not json")
    assert [r.run_id for r in reg.list_runs()] == ["r1"]


def test_the_record_round_trips_through_json():
    _record(task="a task with \"quotes\" and ünicode")
    raw = json.loads((reg.agents_dir() / "r1.json").read_text())
    assert raw["task"] == 'a task with "quotes" and ünicode'


def test_the_row_keeps_the_last_MEANINGFUL_line(monkeypatch):
    """A real stream interleaves hook/system events that summarise to nothing. Taking the last
    event literally blanks the supervisor row mid-run, so the row keeps the last line that
    actually says something."""
    _record()
    reg.append_event("r1", reg.AgentEvent(kind="tool", tool="Bash"))
    reg.append_event("r1", reg.AgentEvent(kind="other", raw_type="system"))
    monkeypatch.setattr(reg, "_alive", lambda pid: True)
    assert reg.list_runs()[0].last == "using Bash"


def test_the_record_on_disk_carries_cost_and_activity(monkeypatch):
    """The VS Code panel reads these files directly and cannot replay a JSONL per row. If cost and
    the activity line lived only on Python's read path, a finished agent would render there as
    'running, —, blank' — which is exactly what it did before this was folded in."""
    _record()
    reg.append_event("r1", reg.AgentEvent(kind="tool", tool="Bash"))
    reg.append_event("r1", reg.AgentEvent(kind="done", cost_usd=0.61))
    reg.finish("r1", exit_code=0)

    raw = json.loads((reg.agents_dir() / "r1.json").read_text())
    assert raw["cost_usd"] == pytest.approx(0.61)
    assert raw["last"] == "done"
    assert raw["status"] == "done", "a finished run must not still claim to be running on disk"


def test_costs_accumulate_across_events():
    _record()
    reg.append_event("r1", reg.AgentEvent(kind="done", cost_usd=0.10))
    reg.append_event("r1", reg.AgentEvent(kind="done", cost_usd=0.05))
    assert reg.list_runs()[0].cost_usd == pytest.approx(0.15)


def test_a_completed_run_is_not_reported_crashed_when_nobody_watched(monkeypatch):
    """If the supervising process dies, no exit code is recorded and the pid is gone — but the
    child's own stream says it finished. The transcript outranks our bookkeeping, otherwise a
    successful run is libelled as crashed."""
    _record(pid=999999)
    reg.append_event("r1", reg.AgentEvent(kind="done", cost_usd=0.6))
    monkeypatch.setattr(reg, "_alive", lambda pid: False)
    assert reg.list_runs()[0].status == "done"


def test_a_run_that_reported_an_error_is_failed_not_crashed(monkeypatch):
    _record(pid=999999)
    reg.append_event("r1", reg.AgentEvent(kind="error", text="blew up"))
    monkeypatch.setattr(reg, "_alive", lambda pid: False)
    assert reg.list_runs()[0].status == "failed"


def test_a_run_that_vanished_mid_stream_is_still_crashed(monkeypatch):
    """No terminal event and no process — that one really did die."""
    _record(pid=999999)
    reg.append_event("r1", reg.AgentEvent(kind="tool", tool="Bash"))
    monkeypatch.setattr(reg, "_alive", lambda pid: False)
    assert reg.list_runs()[0].status == "crashed"


def test_a_healed_status_is_written_back_to_disk(monkeypatch):
    """The panel reads the file, not Python's in-memory view, and only ever downgrades. A status
    healed in memory but left stale on disk shows up there as 'crashed' regardless."""
    _record(pid=999999)
    reg.append_event("r1", reg.AgentEvent(kind="done", cost_usd=0.6))
    monkeypatch.setattr(reg, "_alive", lambda pid: False)
    reg.list_runs()
    assert json.loads((reg.agents_dir() / "r1.json").read_text())["status"] == "done"


def test_an_ended_run_gets_an_observed_end_time(monkeypatch):
    """A dead process never calls finish(), so 'ended, but no end time' is the COMMON case, not an
    edge one — and a timeline cannot draw an interval without one. The last byte the child wrote
    is an honest observed end: the last moment we know it was alive."""
    _record(pid=999999)
    reg.raw_events_path("r1").write_text(
        '{"type":"result","subtype":"success","is_error":false,"total_cost_usd":0.2,'
        '"usage":{},"session_id":"s"}\n'
    )
    monkeypatch.setattr(reg, "_alive", lambda pid: False)
    run = reg.list_runs()[0]
    assert run.status == "done"
    assert run.finished_at is not None and run.finished_at >= run.started_at - 1


def test_a_running_run_is_never_given_an_end_time(monkeypatch):
    _record()
    reg.raw_events_path("r1").write_text("{}\n")
    monkeypatch.setattr(reg, "_alive", lambda pid: True)
    assert reg.list_runs()[0].finished_at is None


def test_the_raw_stream_is_mirrored_into_a_provider_agnostic_file():
    """The panel cannot parse a vendor dialect, and teaching it every provider's JSON would
    duplicate the adapters in TypeScript. Python translates once; the panel reads one shape."""
    _record()
    reg.raw_events_path("r1").write_text(
        '{"type":"system","subtype":"init","cwd":"/tmp","tools":[],"session_id":"s"}\n'
        '{"type":"result","subtype":"success","is_error":false,"total_cost_usd":0.3,'
        '"usage":{},"session_id":"s"}\n'
    )
    reg.read_events("r1")
    mirrored = [json.loads(l) for l in (reg.agents_dir() / "r1.jsonl").read_text().splitlines()]
    assert [m["kind"] for m in mirrored] == ["started", "done"]
    assert all("kind" in m and "text" in m for m in mirrored)  # the shape agents.ts expects


# ── the message ledger: who said what to whom ────────────────────────────────────────────────
# A sequence view (lanes per agent, time down, arrows between them) needs the EXCHANGE recorded,
# not just each side's monologue. So a message is written to BOTH transcripts — the sender's, so
# its own history shows what it asked for, and the recipient's, so the reply has context above it.


def test_a_message_lands_in_both_transcripts():
    _record(run_id="a", name="lead")
    _record(run_id="b", name="reviewer")
    reg.record_message(from_run="a", to_run="b", text="please review the diff")

    sent = [e for e in reg.read_events("a") if e.kind == "message"]
    got = [e for e in reg.read_events("b") if e.kind == "message"]
    assert sent and got, "an exchange invisible to one side is not an exchange"
    assert sent[0].to_run == "b" and got[0].from_run == "a"
    assert "review the diff" in got[0].text


def test_messages_are_listed_for_a_sequence_view():
    _record(run_id="a", name="lead")
    _record(run_id="b", name="reviewer")
    reg.record_message(from_run="a", to_run="b", text="one")
    reg.record_message(from_run="b", to_run="a", text="two")
    pairs = [(m.from_run, m.to_run, m.text) for m in reg.messages()]
    assert pairs == [("a", "b", "one"), ("b", "a", "two")], "order is the whole point of a sequence"


def test_a_message_to_an_unknown_run_is_refused():
    _record(run_id="a")
    assert reg.record_message(from_run="a", to_run="ghost", text="hi") is False


def test_a_message_survives_a_run_that_has_a_raw_vendor_stream():
    """The real-world case the tests above miss: once a run has its own vendor transcript, that
    stream is authoritative and the mirror is rewritten from it — so a message appended into the
    mirror would be silently clobbered. Messages live beside the stream, not inside it."""
    _record(run_id="a", name="lead")
    _record(run_id="b", name="reviewer")
    reg.raw_events_path("b").write_text(
        '{"type":"system","subtype":"init","cwd":"/tmp","tools":[],"session_id":"s"}\n'
    )
    reg.record_message(from_run="a", to_run="b", text="please review")
    reg.read_events("b")  # forces the mirror rewrite

    kinds = [e.kind for e in reg.read_events("b")]
    assert "message" in kinds, "the message was lost behind the vendor stream"
    assert "started" in kinds, "the vendor's own events must still be there"
