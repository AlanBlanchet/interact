"""Provider adapters for the agent CLIs interact supervises.

Parsing is pinned against a REAL captured stream (`tests/fixtures/agents/claude_stream.jsonl`,
`claude -p --output-format stream-json`), not hand-written lines — a fabricated fixture drifts
from the vendor's actual output and the drift only shows up in front of a user.

The legal line these tests also encode: interact builds an argv and reads stdout. It never reads,
stores or forwards a credential — the CLI authenticates itself with the user's own login.
"""

import json
import subprocess
import tomllib
from pathlib import Path

import pytest

from interact.agents.events import AgentEvent
from interact.agents.providers import PROVIDERS, ClaudeCodeProvider, CodexProvider, provider_for


@pytest.mark.parametrize("resume", [False, True])
def test_claude_role_tools_and_denials_are_available_tool_restrictions_on_every_turn(resume):
    provider = ClaudeCodeProvider()
    options = dict(model="fixture-model", agent="visual-critic", agent_prompt="Pinned role instructions",
                   allowed_tools=["Read", "Bash", "mcp__interact__screenshot", "mcp__interact__report_issue"],
                   denied_tools=("mcp__interact__report_issue",))
    command = provider.resume_command("fixture-session", "Review", **options) if resume else provider.command(
        "Review", cwd="/tmp", mcp_config=None, run_id="fixture-run", **options)
    definition = json.loads(command[command.index("--agents") + 1])["visual-critic"]
    assert definition["prompt"] == "Pinned role instructions"
    assert definition["tools"] == options["allowed_tools"]
    assert command[command.index("--agent") + 1] == "visual-critic"
    assert command[command.index("--disallowedTools") + 1] == "mcp__interact__report_issue"
    assert "--allowedTools" not in command
    assert "--permission-mode" not in command


def test_denied_tool_names_cannot_inject_flags_or_unverified_patterns():
    provider = ClaudeCodeProvider()
    for tool in ("--permission-mode", "Bash(git *)", "mcp__*", "Read,Write", "Read\nWrite"):
        with pytest.raises(ValueError, match="tool"):
            provider.command("t", cwd="/tmp", model=None, mcp_config=None, run_id="x", denied_tools=(tool,))


@pytest.mark.parametrize("provider_type", [ClaudeCodeProvider, CodexProvider])
def test_role_definition_rejects_malformed_frontmatter_and_unsafe_names(provider_type, monkeypatch, tmp_path):
    provider = provider_type()
    path = tmp_path / "role.md"
    path.write_text("---\nname: fixture\n")
    monkeypatch.setattr(provider, "definition_path", lambda agent: path)
    with pytest.raises(ValueError, match="frontmatter"):
        provider.definition_prompt("fixture")
    with pytest.raises(ValueError, match="name"):
        provider.definition_prompt("../fixture")
    path.write_text("---\nname: fixture\n---\nRole instructions")
    assert provider.definition_prompt("fixture") == "Role instructions"
    path.write_text("Role instructions")
    assert provider.definition_prompt("fixture") == "Role instructions"


def test_codex_auth_status_requires_an_affirmative_login_message():
    provider = CodexProvider()
    assert provider.accepts_any_auth("", "Logged in using ChatGPT")
    assert provider.accepts_any_auth("Logged in using an API key", "")
    for status in ("logged in: false", "Not logged in", "Login failed", ""):
        assert not provider.accepts_any_auth(status, "")


def test_codex_command_uses_the_effort_resolved_by_the_launcher():
    command = CodexProvider().command(
        "Reply once", cwd="/tmp", model="fixture-model", mcp_config=None,
        run_id="fixture-run", reasoning="medium",
    )
    assert 'model_reasoning_effort="medium"' in command


def test_codex_command_honors_the_requested_write_scope():
    provider = CodexProvider()
    command = provider.command(
        "Edit the assigned file", cwd="/tmp", model="fixture-model", mcp_config=None,
        run_id="fixture-run", permission_mode="workspace-write",
    )
    assert command[command.index("--sandbox") + 1] == "workspace-write"
    with pytest.raises(ValueError, match="not a permission mode"):
        provider.command(
            "Edit the assigned file", cwd="/tmp", model="fixture-model", mcp_config=None,
            run_id="fixture-run", permission_mode="invented-mode",
        )


@pytest.mark.parametrize("resume", [False, True])
def test_codex_projects_mesh_without_changing_permissions(resume):
    provider = CodexProvider()
    config = json.dumps({"mcpServers": {"interact": {
        "command": '/fixture path/\U00010400/interact', "args": ["mcp", 'quoted"arg'],
        "env": {"INTERACT_PARENT_RUN_ID": "fixture-run"},
    }}})
    if resume:
        argv = provider.resume_command("thread", "continue", mcp_config=config)
    else:
        argv = provider.command("read", cwd=".", model=None, mcp_config=config, run_id="fixture-run")
    overrides = [argv[i + 1] for i, value in enumerate(argv) if value == "-c"]
    data = tomllib.loads("\n".join(overrides))
    assert data["mcp_servers"]["interact"] == json.loads(config)["mcpServers"]["interact"]
    assert set(data) == {"features", "mcp_servers"}


@pytest.mark.parametrize("resume", [False, True])
def test_codex_rejects_unsupported_tool_restrictions(resume):
    provider = CodexProvider()
    with pytest.raises(ValueError, match="cannot enforce.*tool restriction"):
        if resume:
            provider.resume_command("thread", "continue", allowed_tools=["Read"])
        else:
            provider.command("read", cwd=".", model=None, mcp_config=None,
                             run_id="fixture-run", allowed_tools=["Read"])


@pytest.mark.parametrize("rows,expected", [
    ([{"name": "interact", "enabled": True, "transport": {"command": "system-wrapper"}}], True),
    ([{"name": "interact", "enabled": False, "transport": {"url": "https://example.invalid/mcp"}}], True),
    ([{"name": "another-server"}], False),
    ([], False),
])
def test_codex_registration_uses_provider_effective_configuration(tmp_path, monkeypatch, rows, expected):
    provider = CodexProvider()
    monkeypatch.setattr(provider, "executable", lambda: "fixture-codex")
    calls = []

    def configured(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, json.dumps(rows), "")

    monkeypatch.setattr(subprocess, "run", configured)
    assert provider.has_mcp_server("interact", cwd=str(tmp_path)) is expected
    assert calls == [(["fixture-codex", "mcp", "list", "--json"], {
        "cwd": str(tmp_path), "capture_output": True, "text": True, "timeout": 10,
    })]


@pytest.mark.parametrize("failure", ["timeout", "os-error", "exit", "json", "shape"])
def test_codex_registration_discovery_fails_closed_without_echoing_output(tmp_path, monkeypatch, failure):
    provider = CodexProvider()
    monkeypatch.setattr(provider, "executable", lambda: "fixture-codex")

    def failed(argv, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 10, output="fixture-sensitive-value")
        if failure == "os-error":
            raise OSError("fixture-sensitive-value")
        output = '[{"missing_name":"fixture-sensitive-value"}]' if failure == "shape" else "fixture-sensitive-value"
        return subprocess.CompletedProcess(argv, 1 if failure == "exit" else 0, output, "fixture-sensitive-value")

    monkeypatch.setattr(subprocess, "run", failed)
    with pytest.raises(ValueError, match="^Cannot inspect Codex MCP configuration safely$"):
        provider.has_mcp_server("interact", cwd=str(tmp_path))


@pytest.mark.parametrize("field,value", [
    ("env", {"INTERACT_PARENT_RUN_ID": "fixture-run", "TOKEN": "fixture-sensitive-value"}),
    ("enabled", True), ("command", ""), ("args", [42]),
])
def test_codex_mesh_rejects_extra_fields_and_invalid_values_without_echoing_them(field, value):
    server = {"command": "fixture-interact", "args": ["mcp"],
              "env": {"INTERACT_PARENT_RUN_ID": "fixture-run"}, field: value}
    with pytest.raises(ValueError, match="^Invalid credential-free Codex mesh configuration$"):
        CodexProvider.mesh_arguments(json.dumps({"mcpServers": {"interact": server}}))


def test_codex_image_support_is_verified_from_installed_help(monkeypatch):
    provider = CodexProvider()
    monkeypatch.setattr(provider, "executable", lambda: "/usr/bin/codex")

    class _Help:
        returncode = 0
        stdout = "  -i, --image <FILE>...  Optional image(s)"

    monkeypatch.setattr("interact.agents.providers.subprocess.run", lambda *a, **k: _Help())
    assert provider.image_attachment_support() is True

    _Help.stdout = "  -m, --model <MODEL>"
    assert provider.image_attachment_support() is False


def test_codex_command_emits_one_image_flag_per_attachment(monkeypatch, tmp_path):
    provider = CodexProvider()
    monkeypatch.setattr(provider, "image_attachment_support", lambda: True)
    first = tmp_path / "first.png"
    second = tmp_path / "second.webp"
    command = provider.command(
        "Inspect", cwd="/tmp", model="fixture-model", mcp_config=None,
        run_id="fixture-run", image_paths=(first, second),
    )
    assert command[-3:] == ["--image", str(first), str(second)]


def test_unsupported_provider_refuses_image_attachments(tmp_path):
    image = tmp_path / "screen.png"
    image.write_bytes(b"png")
    with pytest.raises(ValueError, match="does not support image attachments"):
        ClaudeCodeProvider().command(
            "Inspect", cwd="/tmp", model="fixture-model", mcp_config=None,
            run_id="fixture-run", image_paths=(image,),
        )


def test_codex_failed_command_is_a_tool_result_not_a_terminal_agent_failure():
    event = CodexProvider().parse(json.dumps({
        "type": "item.completed", "item": {
            "id": "item_6", "type": "command_execution", "command": "pytest",
            "aggregated_output": "1 failed", "exit_code": 1, "status": "completed",
        },
    }))
    assert event is not None
    assert event.kind == "tool_result" and event.status == "failed"
    assert event.tool_id == "item_6" and event.text == "1 failed"


def test_codex_command_start_exposes_the_actual_tool_and_command():
    event = CodexProvider().parse(json.dumps({
        "type": "item.started", "item": {
            "id": "item_6", "type": "command_execution", "command": "pytest",
            "status": "in_progress",
        },
    }))
    assert event is not None
    assert event.kind == "tool" and event.tool == "Shell"
    assert event.tool_id == "item_6" and event.tool_input == "pytest"


def test_codex_delivery_commands_use_the_vendor_thread_id():
    provider = CodexProvider()
    assert provider.queue_command("vendor-thread", "ping") == [
        "codex", "queue", "--thread", "vendor-thread", "--message", "ping",
    ]
    resumed = provider.resume_command(
        "vendor-thread", "ping", model="fresh-model", reasoning="high",
        permission_mode="workspace-write",
    )
    assert resumed[:5] == ["codex", "exec", "resume", "vendor-thread", "ping"]
    assert "--json" in resumed and "--model" in resumed
    assert 'model_reasoning_effort="high"' in resumed
    assert "--sandbox" not in resumed
    assert 'sandbox_mode="workspace-write"' in resumed


def test_codex_resume_injects_the_named_role_definition(monkeypatch, tmp_path):
    root = tmp_path / "interact" / "prompts" / "agents"
    root.mkdir(parents=True)
    (root / "tester.md").write_text(
        "---\nname: tester\n---\nAGENT_ROLE: tester\nDo the assigned check.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    resumed = CodexProvider().resume_command("vendor-thread", "continue", agent="tester")

    assert resumed[4].startswith("AGENT_ROLE: tester\n")
    assert "Do the assigned check." in resumed[4]
    assert "Delegated task:\ncontinue" in resumed[4]


def test_codex_thread_start_keeps_vendor_session_identity():
    event = CodexProvider().parse(json.dumps({
        "type": "thread.started", "thread_id": "vendor-thread",
    }))
    assert event is not None and event.session_id == "vendor-thread"

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
    assert done.input_tokens == 106591, "terminal accounting includes cached prompt tokens"


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
    assert CodexProvider().can_resume is True
    assert CodexProvider().can_queue is True
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


def test_codex_lists_installed_role_definitions(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    provider = CodexProvider()
    assert provider.agent_definitions() == []
    root = tmp_path / "interact/prompts/agents"
    root.mkdir(parents=True)
    (root / "tester.md").write_text("Verify the assigned change.")
    assert provider.agent_definitions() == ["tester"]
    assert provider.definition_path("tester") == root / "tester.md"


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


# ── A machine-readable list of definitions ──────────────────────────────────────────────────
# The panel's "start an agent" picker was scraping the human-readable `agents providers` output by
# splitting on "agents:" and commas — a display change would silently empty the picker.


def test_definitions_command_prints_one_name_per_line(capsys, tmp_path, monkeypatch):
    import importlib

    monkeypatch.setenv("HOME", str(tmp_path))
    home = tmp_path / ".claude" / "agents"
    home.mkdir(parents=True)
    for name in ("code-reviewer", "researcher"):
        (home / f"{name}.md").write_text("---\n---\n")
    cli = importlib.import_module("interact.cli.app")
    cli.agents_definitions()
    assert capsys.readouterr().out.split() == ["code-reviewer", "researcher"]


def test_definitions_command_is_silent_when_there_are_none(capsys, tmp_path, monkeypatch):
    """Empty output, not a message: the caller is a parser, and prose would become a fake agent."""
    import importlib

    monkeypatch.setenv("HOME", str(tmp_path))
    cli = importlib.import_module("interact.cli.app")
    cli.agents_definitions()
    assert capsys.readouterr().out.strip() == ""


# --- How much autonomy an agent is given ----------------------------------------------------
#
# Supervising a team means deciding what each member may do on its own. The panel could spawn
# agents but had no way to say "this one may not write" or "let this one plan first, don't touch
# anything" — every run got whatever the vendor defaults to. The modes below are read off the
# INSTALLED binary's own `--help`, never recalled: `claude --permission-mode` accepts
# acceptEdits/auto/bypassPermissions/manual/dontAsk/plan, which is not the set an older memory of
# the docs would produce.


def test_codex_offers_the_verified_bounded_sandbox_scopes():
    modes = CodexProvider().permission_modes()
    assert {mode.id for mode in modes} == {"read-only", "workspace-write"}
    assert all(mode.label and mode.detail and not mode.unrestricted for mode in modes)


def test_claude_offers_the_modes_its_binary_actually_accepts():
    modes = {m.id for m in ClaudeCodeProvider().permission_modes()}
    assert modes == {"acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan"}


def test_every_offered_mode_says_what_it_lets_the_agent_do():
    for mode in ClaudeCodeProvider().permission_modes():
        assert mode.label and mode.detail, f"{mode.id} is offered with no explanation"


def test_the_dangerous_mode_is_marked_as_such():
    """bypassPermissions is the one that can act without asking. It is offered — refusing to
    expose it would just push people to the terminal — but never as an unremarkable choice."""
    modes = {m.id: m for m in ClaudeCodeProvider().permission_modes()}
    assert modes["bypassPermissions"].unrestricted is True
    assert not any(m.unrestricted for i, m in modes.items() if i != "bypassPermissions")


def test_a_chosen_mode_reaches_the_argv():
    argv = ClaudeCodeProvider().command(
        "t", cwd="/tmp", model=None, mcp_config=None, run_id="r", permission_mode="plan")
    assert "--permission-mode" in argv
    assert argv[argv.index("--permission-mode") + 1] == "plan"


def test_no_mode_means_no_flag():
    """The vendor's own default must stay reachable; passing a mode nobody asked for would
    override a setting the person configured in their own CLI."""
    argv = ClaudeCodeProvider().command(
        "t", cwd="/tmp", model=None, mcp_config=None, run_id="r")
    assert "--permission-mode" not in argv


def test_an_unknown_mode_is_refused_at_the_edge():
    """The value arrives from a tool caller and lands on a command line. An unknown one is a
    typo or an injection attempt, not a mode the CLI will helpfully ignore."""
    with pytest.raises(ValueError, match="permission mode"):
        ClaudeCodeProvider().command(
            "t", cwd="/tmp", model=None, mcp_config=None, run_id="r",
            permission_mode="--dangerously-skip-everything")


def test_a_tool_call_and_its_result_share_the_vendor_tool_id():
    """The transcript view opens a call's FULL input/output from the raw stream on click.

    The summarised event is clipped (300/2000 chars) by design; the raw line holds everything,
    and the vendor's tool_use id is the ONE stable key that pairs a call with its result across
    both files. Without it the viewer falls back to prefix-matching, which breaks the moment two
    identical commands run."""
    call = _parse({"type": "assistant", "session_id": "s", "message": {"content": [
        {"type": "tool_use", "id": "toolu_42", "name": "Bash", "input": {"command": "ls"}}]}})
    assert call.tool_id == "toolu_42"
    answer = _parse({"type": "user", "session_id": "s", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "toolu_42", "content": "a\nb"}]}})
    assert answer.tool_id == "toolu_42", "the result must carry the id that names its question"


def test_codex_initial_and_resumed_delegates_cannot_bypass_shared_role_policy():
    provider = CodexProvider()
    commands = (
        provider.command("Read", cwd="/tmp", model="fixture-model", mcp_config=None, run_id="fixture"),
        provider.resume_command("fixture-session", "Continue", model="fixture-model"),
    )
    for command in commands:
        assert "features.multi_agent=false" in command
        assert "features.multi_agent_v2=false" in command
