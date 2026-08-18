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
