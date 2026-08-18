"""Provider adapters for the agent CLIs interact supervises.

Parsing is pinned against a REAL captured stream (`tests/fixtures/agents/claude_stream.jsonl`,
`claude -p --output-format stream-json`), not hand-written lines — a fabricated fixture drifts
from the vendor's actual output and the drift only shows up in front of a user.

The legal line these tests also encode: interact builds an argv and reads stdout. It never reads,
stores or forwards a credential — the CLI authenticates itself with the user's own login.
"""

import json
from pathlib import Path

import pytest

from interact.agents.events import AgentEvent
from interact.agents.providers import PROVIDERS, ClaudeCodeProvider, CodexProvider, provider_for

FIXTURE = Path(__file__).parent / "fixtures" / "agents" / "claude_stream.jsonl"


def _events() -> list[AgentEvent]:
    p = ClaudeCodeProvider()
    out = []
    for line in FIXTURE.read_text().splitlines():
        ev = p.parse(line)
        if ev is not None:
            out.append(ev)
    return out


# ── parsing a real stream ────────────────────────────────────────────────────────────────────


def test_the_real_stream_parses_end_to_end():
    evs = _events()
    kinds = [e.kind for e in evs]
    assert "started" in kinds, f"no init event recognised: {kinds}"
    assert "text" in kinds
    assert kinds[-1] == "done"


def test_the_assistant_text_is_extracted():
    said = [e.text for e in _events() if e.kind == "text"]
    assert any("OK" in t for t in said), said


def test_cost_and_tokens_come_off_the_result_event():
    done = [e for e in _events() if e.kind == "done"][-1]
    # Claude Code reports API-equivalent cost even on a subscription run — this is what makes
    # per-agent cost real rather than a guess.
    assert done.cost_usd is not None and done.cost_usd > 0
    assert done.output_tokens is not None


def test_every_event_carries_the_session_id():
    evs = _events()
    ids = {e.session_id for e in evs if e.session_id}
    assert len(ids) == 1, f"expected one session, got {ids}"


def test_a_rate_limit_event_is_surfaced_as_its_own_kind():
    # Running several agents on one account hits a POOLED limit; a run that dies on it must say
    # so rather than just going quiet.
    raw = [json.loads(l) for l in FIXTURE.read_text().splitlines()]
    if not any(r.get("type") == "rate_limit_event" for r in raw):
        pytest.skip("this capture has no rate-limit event")
    assert any(e.kind == "rate_limit" for e in _events())


def test_junk_lines_never_raise():
    p = ClaudeCodeProvider()
    assert p.parse("") is None
    assert p.parse("not json") is None
    assert p.parse('{"type":"totally-unknown"}') is not None  # kept as `other`, never dropped


# ── building the command ─────────────────────────────────────────────────────────────────────


def test_claude_command_asks_for_a_parseable_stream():
    argv = ClaudeCodeProvider().command("do a thing", cwd="/tmp", model="sonnet",
                                        mcp_config='{"mcpServers":{}}', run_id="11111111-2222-3333-4444-555555555555")
    assert argv[0] == "claude"
    assert "-p" in argv and "do a thing" in argv
    # stream-json REQUIRES --verbose; without it the CLI refuses and we'd get no events at all.
    assert "--output-format" in argv and "stream-json" in argv and "--verbose" in argv


def test_the_run_id_is_the_session_id():
    # Assigning the session id means our registry key and the vendor's own id are the SAME string,
    # so `claude --resume <run_id>` and our records line up with no mapping table.
    rid = "11111111-2222-3333-4444-555555555555"
    argv = ClaudeCodeProvider().command("t", cwd="/tmp", model=None, mcp_config=None, run_id=rid)
    assert argv[argv.index("--session-id") + 1] == rid


def test_the_mesh_config_is_passed_through():
    cfg = '{"mcpServers":{"interact":{"command":"interact"}}}'
    argv = ClaudeCodeProvider().command("t", cwd="/tmp", model=None, mcp_config=cfg, run_id="r")
    assert argv[argv.index("--mcp-config") + 1] == cfg


def test_no_credential_is_ever_placed_on_the_command_line():
    argv = ClaudeCodeProvider().command("t", cwd="/tmp", model="opus", mcp_config=None, run_id="r")
    joined = " ".join(argv).lower()
    for banned in ("api_key", "apikey", "token", "oauth", "bearer", "credential"):
        assert banned not in joined, f"{banned!r} must never appear — the CLI authenticates itself"


# ── the provider set ─────────────────────────────────────────────────────────────────────────


def test_providers_are_addressable_by_name():
    assert provider_for("claude") is not None
    assert isinstance(provider_for("claude"), ClaudeCodeProvider)
    assert "claude" in PROVIDERS


def test_an_unknown_provider_names_the_ones_that_exist():
    with pytest.raises(ValueError) as exc:
        provider_for("gpt5-cli")
    assert "claude" in str(exc.value)


def test_codex_is_declared_but_marked_unverified():
    # codex isn't installed here, so its flags could not be checked against a real binary. It must
    # say so rather than silently building a command that may be wrong.
    c = CodexProvider()
    assert c.verified is False
    assert "unverified" in (c.caveat or "").lower()


# ── what a CONVERSATION view needs (not just a status line) ──────────────────────────────────
# The tree's one-line summary was enough to answer "what is it doing"; showing the actual
# conversation needs the tool's INPUT, the tool's RESULT, and the model's thinking — all of which
# the stream carries and the first normalisation discarded.


def _parse(raw: dict):
    import json as _json
    return ClaudeCodeProvider().parse(_json.dumps(raw))


def test_a_tool_call_keeps_its_input():
    ev = _parse({"type": "assistant", "session_id": "s", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la", "description": "list"}}]}})
    assert ev.kind == "tool" and ev.tool == "Bash"
    assert "ls -la" in ev.tool_input, "the command is the whole point of showing a Bash call"


def test_a_tool_result_is_its_own_event():
    ev = _parse({"type": "user", "session_id": "s", "message": {"content": [
        {"type": "tool_result", "content": "file-a\nfile-b"}]}})
    assert ev.kind == "tool_result" and "file-a" in ev.text


def test_thinking_is_kept_but_marked_as_thinking():
    ev = _parse({"type": "assistant", "session_id": "s", "message": {"content": [
        {"type": "thinking", "thinking": "weighing the options"}]}})
    assert ev.kind == "thinking" and "weighing" in ev.text


def test_a_long_tool_result_is_truncated_not_dropped():
    ev = _parse({"type": "user", "session_id": "s", "message": {"content": [
        {"type": "tool_result", "content": "x" * 50_000}]}})
    assert 0 < len(ev.text) < 5000, "a huge result must not blow up the transcript file"


def test_a_named_agent_definition_is_passed_through():
    """Claude Code resolves `--agent <name>` against the agent files (~/.claude/agents/*.md), so a
    run can BE visual-critic rather than an anonymous 'claude'. That name is also what the panel
    should show, which is why the caller gets it back rather than inventing a label."""
    argv = ClaudeCodeProvider().command("t", cwd="/tmp", model=None, mcp_config=None,
                                        run_id="r", agent="visual-critic")
    assert argv[argv.index("--agent") + 1] == "visual-critic"


def test_no_agent_flag_when_none_is_named():
    argv = ClaudeCodeProvider().command("t", cwd="/tmp", model=None, mcp_config=None, run_id="r")
    assert "--agent" not in argv


# ── agents talking to each other ─────────────────────────────────────────────────────────────
# Delivery is not a bespoke protocol either: our run_id IS the vendor's session id, so resuming
# that session with a message continues the SAME conversation — the recipient keeps its context
# and its transcript grows in place, which is what makes the exchange visible afterwards.


def test_resume_continues_the_same_session_with_the_message():
    argv = ClaudeCodeProvider().resume_command("11111111-2222-3333-4444-555555555555", "ping")
    assert argv[0] == "claude"
    assert argv[argv.index("--resume") + 1] == "11111111-2222-3333-4444-555555555555"
    assert "ping" in argv
    # Still a parseable stream, or the reply would never reach the transcript.
    assert "--output-format" in argv and "stream-json" in argv and "--verbose" in argv


def test_a_provider_that_cannot_resume_says_so():
    assert CodexProvider().can_resume is False
    assert ClaudeCodeProvider().can_resume is True


# ── Housekeeping is not activity ────────────────────────────────────────────────────────────
# The activity view rendered more `other` rows than real ones: token accounting and hook
# lifecycle lines outnumbered what the agent actually DID, so the transparency the panel exists
# for was buried in noise. Bookkeeping the vendor emits about its own machinery is dropped;
# anything describing the agent's WORK is kept and named.


@pytest.mark.parametrize(
    "subtype",
    ["thinking_tokens", "hook_started", "hook_response"],
)
def test_vendor_housekeeping_is_dropped_not_shown_as_other(subtype):
    from interact.agents.providers import ClaudeCodeProvider

    event = ClaudeCodeProvider().parse(
        json.dumps({"type": "system", "subtype": subtype, "session_id": "s"})
    )
    assert event is None, f"{subtype} is bookkeeping about the harness, not agent activity"


def test_a_spawned_subagent_is_real_activity_and_is_kept():
    """An agent starting a Task IS the team behaviour the panel exists to show."""
    from interact.agents.providers import ClaudeCodeProvider

    event = ClaudeCodeProvider().parse(
        json.dumps({"type": "system", "subtype": "task_started", "session_id": "s"})
    )
    assert event is not None and event.kind != "other"


def test_an_unknown_system_subtype_is_still_kept_as_other():
    """A vendor adding a new event must not vanish — dropping is for the known-noisy only."""
    from interact.agents.providers import ClaudeCodeProvider

    event = ClaudeCodeProvider().parse(
        json.dumps({"type": "system", "subtype": "something_new", "session_id": "s"})
    )
    assert event is not None and event.kind == "other"


def test_the_incoming_prompt_is_named_not_lumped_as_other():
    """A `user` line carrying text is what was ASKED of the agent — the other half of the
    conversation. Left as `other` the activity view showed only the agent's replies."""
    from interact.agents.providers import ClaudeCodeProvider

    event = ClaudeCodeProvider().parse(json.dumps({
        "type": "user", "session_id": "s",
        "message": {"role": "user", "content": [{"type": "text", "text": "check the error paths"}]},
    }))
    assert event is not None and event.kind == "prompt"
    assert "check the error paths" in (event.text or "")


# ── Which agent definitions can be spawned here ─────────────────────────────────────────────
# `agent_spawn(agent=...)` resolves a definition by name, but nothing told a caller WHICH names
# exist — and an agent cannot ask a follow-up question, so an unlisted capability is an unusable
# one. The provider knows where its definitions live, so it is the provider that answers.


def test_a_provider_lists_the_agent_definitions_it_can_resolve(tmp_path, monkeypatch):
    from interact.agents.providers import ClaudeCodeProvider

    home = tmp_path / ".claude" / "agents"
    home.mkdir(parents=True)
    (home / "code-reviewer.md").write_text("---\nname: code-reviewer\n---\nreview things")
    (home / "visual-critic.md").write_text("---\nname: visual-critic\n---\nlook at things")
    (home / "notes.txt").write_text("not an agent")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert ClaudeCodeProvider().agent_definitions() == ["code-reviewer", "visual-critic"]


def test_no_definitions_directory_is_an_empty_list_not_an_error(tmp_path, monkeypatch):
    from interact.agents.providers import ClaudeCodeProvider

    monkeypatch.setenv("HOME", str(tmp_path))
    assert ClaudeCodeProvider().agent_definitions() == []


def test_a_provider_that_has_no_such_concept_lists_nothing():
    """Codex has no agent-definition files, so it must answer emptily rather than guess."""
    from interact.agents.providers import CodexProvider

    assert CodexProvider().agent_definitions() == []


# ── Context means CONTEXT ───────────────────────────────────────────────────────────────────
# Claude reports the prompt in three parts and `input_tokens` is only the UNCACHED remainder. A
# real run measured here: input_tokens=2, cache_creation_input_tokens=102218. Recording the first
# number and calling it context claims a 102k prompt was 2 tokens.


def test_the_cached_prompt_counts_as_context():
    from interact.agents.providers import ClaudeCodeProvider

    event = ClaudeCodeProvider().parse(json.dumps({
        "type": "assistant", "session_id": "s",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}],
                    "usage": {"input_tokens": 2, "cache_creation_input_tokens": 102218,
                              "cache_read_input_tokens": 500, "output_tokens": 40}},
    }))
    assert event.input_tokens == 102720, "the whole prompt the model saw, not the uncached scrap"
    assert event.output_tokens == 40


def test_a_usage_block_with_no_caching_is_unchanged():
    from interact.agents.providers import ClaudeCodeProvider

    event = ClaudeCodeProvider().parse(json.dumps({
        "type": "assistant", "session_id": "s",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}],
                    "usage": {"input_tokens": 300, "output_tokens": 40}},
    }))
    assert event.input_tokens == 300


def test_no_usage_at_all_reports_nothing_rather_than_zero():
    """Zero would render as a real measurement of an empty context."""
    from interact.agents.providers import ClaudeCodeProvider

    event = ClaudeCodeProvider().parse(json.dumps({
        "type": "assistant", "session_id": "s",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
    }))
    assert event.input_tokens is None
