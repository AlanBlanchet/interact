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
