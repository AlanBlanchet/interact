"""Delivering a message to a running agent.

Two surfaces send messages — the `agent_send` MCP tool (an agent addressing a teammate) and the
CLI (`interact agents send`, which is how the VS Code panel lets the OPERATOR join in). They must
agree on every refusal, so the checks live here once rather than being written twice and drifting.
"""

import pytest

from interact.agents import messaging
from interact.agents import registry as reg


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    yield


def _record(**over):
    return reg.register(
        run_id=over.get("run_id", "r1"), name=over.get("name", "reviewer"),
        provider=over.get("provider", "claude"), task="t", pid=1234,
    )


def test_an_unknown_run_id_says_how_to_find_the_real_ones():
    error = messaging.check_deliverable("nope")[1]
    assert error and "nope" in error and "agent_list" in error


def test_it_refuses_to_type_into_one_of_the_users_own_editor_sessions(monkeypatch):
    """A foreign run is a session the user is driving — interact watches it, never types in it."""
    _record()
    monkeypatch.setattr(reg, "list_runs", lambda **kw: [_Foreign()])
    error = messaging.check_deliverable("r1")[1]
    assert error and "must not type into it" in error


class _Foreign:
    run_id, name, provider, foreign, cwd = "r1", "my editor", "claude", True, "."


def test_a_provider_that_cannot_resume_is_refused_with_the_alternative(monkeypatch):
    """Without resume the message would arrive with no context, which is worse than refusing."""
    _record(provider="codex")

    class _NoResume:
        can_resume = False

    monkeypatch.setattr(messaging, "provider_for", lambda name: _NoResume())
    error = messaging.check_deliverable("r1")[1]
    assert error and "agent_spawn" in error


def test_a_deliverable_run_returns_no_error(monkeypatch):
    _record()

    class _Ok:
        can_resume = True

    monkeypatch.setattr(messaging, "provider_for", lambda name: _Ok())
    run, error = messaging.check_deliverable("r1")
    assert error is None and run.run_id == "r1"


def test_the_exchange_is_recorded_before_delivery(monkeypatch):
    """Recorded on BOTH sides — that is what the sequence view draws its arrows from, so a
    delivery that failed to record must not proceed and leave an invisible message."""
    _record()
    monkeypatch.setattr(reg, "record_message", lambda **kw: False)
    assert "could not record" in messaging.record_exchange("op", "r1", "hi")


# ── Run ids: what the tool PRINTS must be what it ACCEPTS ───────────────────────────────────
# `interact agents list` shows 8-character ids, and every command that takes one demanded the full
# uuid — so copying an id straight off the tool's own output failed with "no agent run". The panel
# passes full ids, but a human reading the list cannot.


def test_a_unique_prefix_resolves_to_the_full_id():
    _record(run_id="abcd1234-0000-0000-0000-000000000000")
    assert reg.resolve_run_id("abcd1234") == "abcd1234-0000-0000-0000-000000000000"


def test_an_exact_id_still_resolves_to_itself():
    _record(run_id="abcd1234-0000-0000-0000-000000000000")
    full = "abcd1234-0000-0000-0000-000000000000"
    assert reg.resolve_run_id(full) == full


def test_an_ambiguous_prefix_resolves_to_nothing_rather_than_guessing():
    """Picking one at random could stop or message the WRONG agent — refuse instead."""
    _record(run_id="abcd1111-0000-0000-0000-000000000000")
    _record(run_id="abcd2222-0000-0000-0000-000000000000")
    assert reg.resolve_run_id("abcd") is None


def test_an_unknown_prefix_resolves_to_nothing():
    assert reg.resolve_run_id("zzzz") is None


def test_delivery_accepts_the_id_the_list_printed(monkeypatch):
    _record(run_id="abcd1234-0000-0000-0000-000000000000")

    class _Ok:
        can_resume = True

    monkeypatch.setattr(messaging, "provider_for", lambda name: _Ok())
    run, error = messaging.check_deliverable("abcd1234")
    assert error is None and run.run_id.startswith("abcd1234")


# ── A message says WHO, and which way ───────────────────────────────────────────────────────
# The row read "reviewer → 2b7642ee: ..." where 2b7642ee is reviewer's OWN id — an arrow pointing
# at itself. It looks exactly like the agent-to-agent messaging the owner asked to SEE, while
# actually showing nothing of the kind. A message needs a direction and a name.


def test_a_message_the_agent_RECEIVED_points_inward_and_names_the_sender():
    from interact.agents.events import AgentEvent

    event = AgentEvent(kind="message", from_run="operator", to_run="r1", text="check the tests")
    assert event.summary(viewer="r1") == "← operator: check the tests"


def test_a_message_the_agent_SENT_points_outward_and_names_the_recipient(tmp_path, monkeypatch):
    from interact.agents.events import AgentEvent

    monkeypatch.setenv("HOME", str(tmp_path))
    reg.register(run_id="r2", name="perf", provider="claude", task="t", pid=None)
    event = AgentEvent(kind="message", from_run="r1", to_run="r2", text="numbers look fine")
    assert event.summary(viewer="r1") == "→ perf: numbers look fine"


def test_with_no_viewer_it_still_names_both_ends_rather_than_a_bare_hash(tmp_path, monkeypatch):
    from interact.agents.events import AgentEvent

    monkeypatch.setenv("HOME", str(tmp_path))
    reg.register(run_id="r1", name="reviewer", provider="claude", task="t", pid=None)
    reg.register(run_id="r2", name="perf", provider="claude", task="t", pid=None)
    event = AgentEvent(kind="message", from_run="r1", to_run="r2", text="hi")
    assert event.summary() == "reviewer → perf: hi"


def test_an_unknown_id_falls_back_to_its_short_form():
    from interact.agents.events import AgentEvent

    event = AgentEvent(kind="message", from_run="operator", to_run="deadbeef-1111", text="hi")
    assert event.summary(viewer="deadbeef-1111") == "← operator: hi"


# ── The conversation shows BOTH sides, in order ─────────────────────────────────────────────
# Messages live in their own file and were APPENDED to the end of the event list, and the mirror
# the VS Code panel reads was written WITHOUT them at all. So the chat showed the agent talking to
# nobody: you could not see what you had asked, and an agent-to-agent exchange was invisible in
# the very view built to show it.


def test_a_message_is_placed_where_it_was_sent_not_at_the_end(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    reg.register(run_id="r1", name="reviewer", provider="claude", task="t", pid=None)
    raw = reg.raw_events_path("r1")
    raw.parent.mkdir(parents=True, exist_ok=True)
    # One turn, then a message arrives, then the reply.
    raw.write_text(_assistant("first answer") + "\n")
    reg.record_message(from_run="operator", to_run="r1", text="now do the other thing")
    with raw.open("a") as f:
        f.write(_assistant("second answer") + "\n")

    kinds = [(e.kind, (e.text or "")[:20]) for e in reg.read_events("r1")]
    assert kinds == [
        ("text", "first answer"),
        ("message", "now do the other thi"),
        ("text", "second answer"),
    ]


def test_the_mirror_the_panel_reads_contains_the_messages(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    reg.register(run_id="r1", name="reviewer", provider="claude", task="t", pid=None)
    reg.raw_events_path("r1").parent.mkdir(parents=True, exist_ok=True)
    reg.raw_events_path("r1").write_text(_assistant("hi") + "\n")
    reg.record_message(from_run="operator", to_run="r1", text="hello")
    reg.read_events("r1")  # writes the mirror

    mirrored = reg.events_path("r1").read_text()
    assert '"message"' in mirrored, "the panel reads this file; a missing message is invisible"


def _assistant(text):
    import json

    return json.dumps({
        "type": "assistant", "session_id": "s",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}], "usage": {}},
    })


def test_a_message_with_no_anchor_goes_LAST_not_first(tmp_path, monkeypatch):
    """Messages recorded before the anchor existed carry none. We do not know where they belong,
    so they go at the end — `(index or 0)` silently read "unknown" as "the very beginning" and
    dropped every one of them above the run's own first turn."""
    monkeypatch.setenv("HOME", str(tmp_path))
    reg.register(run_id="r1", name="reviewer", provider="claude", task="t", pid=None)
    raw = reg.raw_events_path("r1")
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(_assistant("a turn") + "\n")
    from interact.agents.events import AgentEvent

    reg.messages_path("r1").write_text(
        AgentEvent(kind="message", text="unanchored", from_run="operator",
                   to_run="r1").model_dump_json() + "\n"
    )
    assert [e.kind for e in reg.read_events("r1")] == ["text", "message"]


def test_the_mirror_updates_when_the_CONTENT_changes_not_only_its_length(tmp_path, monkeypatch):
    """The mirror was rewritten only when the event COUNT changed, so a fix to how events are
    ordered or rendered never reached the panel — it kept serving the old shape forever, and the
    only way to notice was that the UI disagreed with the CLI."""
    monkeypatch.setenv("HOME", str(tmp_path))
    reg.register(run_id="r1", name="reviewer", provider="claude", task="t", pid=None)
    events_file = reg.events_path("r1")
    events_file.parent.mkdir(parents=True, exist_ok=True)
    from interact.agents.events import AgentEvent

    stale = [AgentEvent(kind="text", text="WRONG"), AgentEvent(kind="text", text="ORDER")]
    events_file.write_text("".join(e.model_dump_json() + "\n" for e in stale))

    fresh = [AgentEvent(kind="text", text="ORDER"), AgentEvent(kind="text", text="RIGHT")]
    reg._mirror_normalised("r1", fresh)  # same LENGTH, different content
    assert "RIGHT" in events_file.read_text()
