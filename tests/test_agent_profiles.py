"""Per-agent model routing, without opening an escalation hole.

Alan asked: "why couldn't we mix? Can't we control the env that an agent (or sub-agent) spawns in
by activating / deactivating what the agent can do before called? Even for other providers?"

Yes — and the safe shape is the one he described: decide what an agent may do BEFORE the call,
rather than letting the caller hand over an environment. A raw `env` dict on an MCP tool is a
model-reachable path to `LD_PRELOAD`, `PATH`, and key exfiltration; this project already refuses
that shape once, where `agent_spawn` may not select an unrestricted permission mode.

So a profile is a NAME the operator defines, and it resolves to a fixed, allow-listed set of
variables. There is no arrangement of inputs that turns a profile into an arbitrary environment.
"""

import pytest

from interact.agents.profiles import (
    ALLOWED_ENV, PROFILE_PREFIX, overlay_for, profiles_from,
)


def test_a_profile_is_defined_by_the_operator_not_the_caller():
    env = {f"{PROFILE_PREFIX}CHEAP": "ollama/deepseek-v4-flash", "UNRELATED": "x"}
    assert profiles_from(env) == {"cheap": "ollama/deepseek-v4-flash"}


def test_a_profile_resolves_to_a_base_url_and_a_model():
    got = overlay_for("ollama/deepseek-v4-flash", env={"OLLAMA_API_BASE": "http://localhost:11434"})
    assert got["ANTHROPIC_BASE_URL"] == "http://localhost:11434"
    assert got["ANTHROPIC_MODEL"] == "deepseek-v4-flash", "the provider prefix is ours, not the CLI's"


def test_nothing_outside_the_allow_list_can_ever_be_set():
    """The whole point. Even a profile value crafted to look like an assignment cannot add a key."""
    got = overlay_for("ollama/x\nLD_PRELOAD=/tmp/evil.so", env={})
    assert set(got) <= ALLOWED_ENV
    assert "LD_PRELOAD" not in got
    for key in ("PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH", "NODE_OPTIONS"):
        assert key not in ALLOWED_ENV, f"{key} must never be settable through a profile"


@pytest.mark.parametrize("hostile", [
    "ollama/x@http://evil.example",
    "ollama/x http://evil.example",
    "ollama/../../etc/passwd",
    "ollama/x\nANTHROPIC_BASE_URL=http://evil.example",
])
def test_a_hostile_model_id_cannot_smuggle_an_endpoint(hostile):
    """A base URL comes from the OPERATOR's own environment, never from the model string.

    A malformed id is REFUSED rather than sanitised into something plausible: the failure mode of
    guessing is sending the operator's credentials to an endpoint nobody chose, and there is no
    version of that worth the convenience.
    """
    got = overlay_for(hostile, env={"OLLAMA_API_BASE": "http://localhost:11434"})
    assert "evil.example" not in str(got)
    assert got == {} or got["ANTHROPIC_BASE_URL"] == "http://localhost:11434"


def test_a_model_with_no_provider_prefix_routes_nowhere():
    """An unprefixed model is the vendor's own default — no base URL override, nothing to redirect."""
    assert overlay_for("opus", env={}) == {}


def test_an_unknown_profile_is_refused_rather_than_guessed():
    with pytest.raises(KeyError):
        profiles_from({})["nope"]


@pytest.mark.parametrize("value", ["", "   ", "/", "ollama/"])
def test_a_malformed_profile_value_yields_nothing(value):
    assert overlay_for(value, env={}) == {}


@pytest.mark.asyncio
async def test_the_spawn_tool_refuses_a_profile_nobody_defined(monkeypatch):
    """Silently ignoring an unknown profile is the dangerous version: the agent runs, looks fine,
    and quietly used the wrong model. Refuse, and say which profiles exist."""
    import interact.server as srv

    monkeypatch.delenv("INTERACT_PROFILE_CHEAP", raising=False)
    out = await srv.agent_spawn("do a thing", profile="does-not-exist")
    assert out.startswith("ERROR:"), out
    assert "does-not-exist" in out


@pytest.mark.asyncio
async def test_a_defined_profile_reaches_the_spawn(monkeypatch):
    """The producer/consumer seam: a profile that resolves must actually reach `run_agent`, not
    merely exist in a module nothing calls."""
    import interact.server as srv
    from interact.agents import run as run_mod

    monkeypatch.setenv("INTERACT_PROFILE_CHEAP", "ollama/deepseek-v4-flash")
    seen: dict = {}

    async def fake_run(provider, task, **kw):
        seen.update(kw)
        raise RuntimeError("stop here — the argument is what we are testing")

    monkeypatch.setattr(run_mod, "run_agent", fake_run, raising=False)
    monkeypatch.setattr(srv.tools_agents, "run_agent", fake_run, raising=False)
    await srv.agent_spawn("do a thing", profile="cheap")
    assert seen.get("profile") == "cheap", f"the profile never reached the spawn: {seen}"
