"""`agent` arrives from the MCP boundary and is handed to the provider, which turns it into a
filesystem path (`~/.claude/agents/<agent>.md`) that is now RECORDED on the run and offered by the
VS Code panel as a clickable "system prompt" link. Nothing validated it, so `agent="../../x"`
walked out of the definitions directory into a path a person would then click.

Exploitability is low — a caller holding this tool already has tool access, and the `.md` suffix
plus an existence check constrain where it can land — but the fix belongs at the edge, where the
untrusted value enters, not in the sink. The provider already knows which definitions exist.
"""

import pytest

from interact.agents.providers import provider_for


def test_a_traversing_agent_name_is_refused_before_it_becomes_a_path():
    prov = provider_for("claude")
    assert prov.valid_definition("../../../etc/passwd") is False
    assert prov.valid_definition("../secrets") is False
    assert prov.valid_definition("nested/name") is False
    assert prov.valid_definition("") is False


def test_a_real_definition_is_accepted(monkeypatch):
    prov = provider_for("claude")
    monkeypatch.setattr(type(prov), "agent_definitions", lambda self: ["code-reviewer", "tester"])
    assert prov.valid_definition("code-reviewer") is True
    assert prov.valid_definition("ghost") is False


@pytest.mark.asyncio
async def test_spawn_refuses_an_unknown_definition_and_says_which_exist(monkeypatch):
    import interact.server as srv
    from interact.agents.providers import ClaudeCodeProvider

    monkeypatch.setattr(ClaudeCodeProvider, "available", lambda self: True)
    monkeypatch.setattr(ClaudeCodeProvider, "agent_definitions", lambda self: ["tester", "researcher"])

    async def never(*a, **k):
        raise AssertionError("a process was started for an unvalidated definition name")

    monkeypatch.setattr(srv.tools_agents, "run_agent", never)

    out = await srv.tools_agents.agent_spawn("do a thing", agent="../../../etc/passwd")
    assert out.startswith("ERROR:")
    assert "tester" in out and "researcher" in out, "an agent cannot ask, so list what IS valid"
