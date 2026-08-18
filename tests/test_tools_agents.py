"""The agent-mesh MCP tools — the surface a spawned agent uses to build a team.

An agent cannot ask a follow-up question, so every failure here has to be self-explaining: an
uninstalled provider says which ones ARE installed, an unknown run id says how to find the real
ones. These tests pin that, because an error an agent can't act on stalls a whole team.
"""

import pytest

import interact.server as srv
from interact.agents import registry as reg
from interact.agents.events import AgentEvent


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    yield


@pytest.mark.asyncio
async def test_an_unknown_provider_lists_the_real_ones():
    out = await srv.agent_spawn("do it", provider="gpt5-cli")
    assert out.startswith("ERROR") and "claude" in out


@pytest.mark.asyncio
async def test_an_uninstalled_provider_says_what_is_installed(monkeypatch):
    from interact.agents.providers import CodexProvider

    monkeypatch.setattr(CodexProvider, "available", lambda self: False)
    out = await srv.agent_spawn("do it", provider="codex")
    assert out.startswith("ERROR") and "not installed" in out


@pytest.mark.asyncio
async def test_an_empty_team_still_says_what_is_possible():
    out = await srv.agent_list()
    assert "No agent runs" in out and "Providers available" in out


@pytest.mark.asyncio
async def test_the_listing_shows_status_cost_and_the_tree(monkeypatch):
    reg.register(run_id="p-1", pid=1, provider="claude", name="lead", task="t", cwd="/tmp")
    reg.register(run_id="c-1", pid=2, provider="codex", name="helper", task="t", cwd="/tmp",
                 parent_run_id="p-1")
    reg.append_event("c-1", AgentEvent(kind="done", cost_usd=0.125))
    monkeypatch.setattr(reg, "_alive", lambda pid: True)
    monkeypatch.setattr(reg, "_discover_foreign", lambda: [])

    out = await srv.agent_list()
    assert "lead" in out and "helper" in out
    assert "0.1250" in out          # per-agent cost is real, not a placeholder
    assert "Team tree" in out and "spawned by" in out
    assert "API-equivalent" in out  # never presented as fresh spend


@pytest.mark.asyncio
async def test_foreign_sessions_are_marked_as_not_ours(monkeypatch):
    monkeypatch.setattr(reg, "_discover_foreign",
                        lambda: [{"sessionId": "abcd1234", "name": "their-window",
                                  "cwd": "/x", "kind": "interactive"}])
    out = await srv.agent_list(include_foreign=True)
    assert "their-window" in out and "not started by interact" in out


@pytest.mark.asyncio
async def test_events_for_an_unknown_run_say_how_to_find_the_real_ones():
    out = await srv.agent_events("nope")
    assert out.startswith("ERROR") and "agent_list" in out


@pytest.mark.asyncio
async def test_events_are_rendered_oldest_first(monkeypatch):
    reg.register(run_id="r", pid=1, provider="claude", name="w", task="t", cwd="/tmp")
    reg.append_event("r", AgentEvent(kind="tool", tool="Bash"))
    reg.append_event("r", AgentEvent(kind="text", text="finished up"))
    out = await srv.agent_events("r")
    assert out.index("using Bash") < out.index("finished up")


@pytest.mark.asyncio
async def test_stopping_an_unknown_run_is_an_actionable_error():
    out = await srv.agent_stop("nope")
    assert out.startswith("ERROR") and "agent_list" in out


@pytest.mark.asyncio
async def test_providers_report_availability_and_the_unverified_caveat():
    out = await srv.agent_providers()
    assert "claude" in out and "codex" in out
    assert "unverified" in out.lower(), "an untested adapter must not look as solid as a tested one"


# ── Agents are named after their agent FILE ─────────────────────────────────────────────────
# "the agents should have proper names right ? The name of the agent file ? Right ?" — the
# provider could already resolve one (`--agent <name>` reads ~/.claude/agents/<name>.md) and
# run_agent took the parameter, but the spawn TOOL never exposed it, so no caller could ask for
# one and every run fell back to being called after its provider.


@pytest.mark.asyncio
async def test_an_agent_can_be_spawned_by_its_definition_name(monkeypatch):
    seen = {}

    async def _fake_run(provider, task, **kw):
        seen.update(kw)

        class _H:
            run_id, name, pid = "r1", kw.get("name") or "?", 1

        return _H()

    monkeypatch.setattr("interact.server.tools_agents.run_agent", _fake_run)
    monkeypatch.setattr("interact.agents.providers.ClaudeCodeProvider.available", lambda self: True)
    await srv.agent_spawn("review it", agent="code-reviewer")
    assert seen["agent"] == "code-reviewer", "the definition must reach the CLI"


@pytest.mark.asyncio
async def test_the_run_is_NAMED_after_the_definition_not_the_provider(monkeypatch):
    """Without this the panel lists three runs all called 'claude' — the complaint itself."""
    seen = {}

    async def _fake_run(provider, task, **kw):
        seen.update(kw)

        class _H:
            run_id, name, pid = "r1", kw.get("name") or "?", 1

        return _H()

    monkeypatch.setattr("interact.server.tools_agents.run_agent", _fake_run)
    monkeypatch.setattr("interact.agents.providers.ClaudeCodeProvider.available", lambda self: True)
    await srv.agent_spawn("review it", agent="code-reviewer")
    assert seen["name"] == "code-reviewer"


@pytest.mark.asyncio
async def test_an_explicit_name_still_wins_over_the_definition(monkeypatch):
    seen = {}

    async def _fake_run(provider, task, **kw):
        seen.update(kw)

        class _H:
            run_id, name, pid = "r1", "x", 1

        return _H()

    monkeypatch.setattr("interact.server.tools_agents.run_agent", _fake_run)
    monkeypatch.setattr("interact.agents.providers.ClaudeCodeProvider.available", lambda self: True)
    await srv.agent_spawn("do it", agent="code-reviewer", name="second-opinion")
    assert seen["name"] == "second-opinion"
