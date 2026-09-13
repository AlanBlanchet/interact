"""One ranked candidate list across every provider, walked in order until one can start.

"We rank based on all providers, we get the first one from the criteria, and if not available
we get the next one." Availability is a fact about THIS machine before anything runs — CLI on
PATH, provider switched on, logged in, the requested mode and attachments understood. A denial
or a failure once the child could act is the run's outcome, never a reason to try the next.
"""

import asyncio
import importlib
import sys

import pytest

from interact.agents import registry as reg
from interact.agents.policy import Policy
from interact.agents.providers import PROVIDERS, AgentProvider, ClaudeCodeProvider, PermissionMode, UnsupportedToolPolicy
from interact.agents.run import ModelUnavailable, rank_candidates, run_agent
from interact.models import Model, ModelCapability
import interact.server.tools_agents as tools_agents
from interact.cli import app_commands as cli
from test_model_criteria import catalog_of

CRITERION = "cap.vlm and price.in >= 0"


class _Cli(AgentProvider):
    """A provider whose availability facts are set by the test, running a real subprocess."""

    verified = True
    installed = True
    logged_in = True
    script = (
        'import json\n'
        'print(json.dumps({"type":"system","subtype":"init","session_id":"SID"}), flush=True)\n'
        'print(json.dumps({"type":"result","subtype":"success","is_error":False,'
        '"usage":{"output_tokens":1},"session_id":"SID"}), flush=True)\n'
    )
    probes = 0

    def available(self):
        return self.installed

    async def authenticated(self, env, *, timeout=10):
        type(self).probes += 1
        return self.logged_in

    def command(self, task, *, cwd, model, mcp_config, run_id, agent=None,
                permission_mode=None, allowed_tools=None, reasoning=None, image_paths=()):
        return [sys.executable, "-c", self.script]

    def parse(self, line):
        return ClaudeCodeProvider().parse(line)


class _Alpha(_Cli):
    name = "alpha"
    binary = "alpha-cli"
    native_providers = frozenset({"vendor-a"})


class _Beta(_Cli):
    name = "beta"
    binary = "beta-cli"
    native_providers = frozenset({"vendor-b"})


class _Crashing(_Alpha):
    def command(self, *a, **k):
        return [sys.executable, "-c", "import sys; sys.exit(3)"]


def _row(provider, id, score, price):
    return Model(provider=provider, id=id, capabilities={ModelCapability.VLM},
                 intelligence_score=score, input_cost_per_million=price, output_cost_per_million=price)


@pytest.fixture
def team(monkeypatch, tmp_path):
    """Two CLIs, each running its own vendor; the cheapest clearing model sits with `beta`."""
    monkeypatch.setenv("HOME", str(tmp_path))
    alpha, beta = _Alpha(), _Beta()
    for cls in (_Alpha, _Beta):
        cls.installed = True
        cls.logged_in = True
        cls.probes = 0
    monkeypatch.setattr("interact.agents.providers.PROVIDERS", {"alpha": alpha, "beta": beta})
    monkeypatch.setattr("interact.agents.run.PROVIDERS", {"alpha": alpha, "beta": beta})
    monkeypatch.setattr(reg, "PROVIDERS", {"alpha": alpha, "beta": beta})
    monkeypatch.setattr("interact.agents.run.load_policy", lambda: Policy(
        agents={"tester": CRITERION}, reasoning={"tester": "medium"},
    ))
    with catalog_of(
        _row("vendor-b", "b-strong", 90.0, 0.2),
        _row("vendor-a", "a-mid", 60.0, 1.0),
        _row("vendor-a", "a-weak", 20.0, 2.0),
        _row("vendor-c", "unreachable", 99.0, 0.1),
    ):
        yield alpha, beta


def _ids(candidates):
    return [(c.provider, c.model, c.rank) for c in candidates]


def test_the_list_is_ranked_across_providers_and_deterministic(team):
    alpha, beta = team
    ranked = rank_candidates(CRITERION, {}, providers=[alpha, beta])
    assert _ids(ranked) == [("beta", "b-strong", 0), ("alpha", "a-mid", 1), ("alpha", "a-weak", 2)]
    assert [c.catalog_id for c in ranked] == ["vendor-b/b-strong", "vendor-a/a-mid", "vendor-a/a-weak"]
    assert rank_candidates(CRITERION, {}, providers=[beta, alpha]) == ranked


def test_an_explicit_provider_is_a_filter_on_the_same_list(team):
    alpha, _ = team
    assert _ids(rank_candidates(CRITERION, {}, providers=[alpha])) == [("alpha", "a-mid", 1), ("alpha", "a-weak", 2)]


def test_nothing_runnable_names_every_pool(team):
    with pytest.raises(ModelUnavailable, match="alpha, beta"):
        rank_candidates("price.in > 100", {}, providers=list(team))


def test_plain_model_unavailable_for_selected_provider_names_pool(team):
    alpha, beta = team
    with pytest.raises(ModelUnavailable, match="alpha.*b-strong"):
        rank_candidates("b-strong", {}, providers=[alpha])


@pytest.mark.asyncio
async def test_failed_auth_probe_has_its_own_skip_reason(team, tmp_path):
    alpha, beta = team
    beta.logged_in = None
    run = await run_agent(None, "t", agent="tester", cwd=str(tmp_path), mesh=False)
    await asyncio.wait_for(run.wait(), 30)
    record = reg.get_run(run.run_id)
    assert record.provider == "alpha"
    assert [item.reason for item in record.skipped] == ["auth_check_failed"]


@pytest.mark.asyncio
async def test_the_first_candidate_runs_when_available(team, tmp_path):
    run = await run_agent(None, "t", agent="tester", cwd=str(tmp_path), mesh=False)
    await asyncio.wait_for(run.wait(), 30)
    saved = reg.get_run(run.run_id)
    assert (saved.provider, saved.model, saved.reasoning) == ("beta", "b-strong", "medium")
    assert saved.skipped == () and [c.model for c in saved.candidates] == ["b-strong", "a-mid", "a-weak"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fact,reason", [("installed", "cli_missing"), ("logged_in", "unauthenticated")])
async def test_an_unavailable_first_candidate_falls_through_to_the_next(team, tmp_path, fact, reason):
    _, beta = team
    setattr(_Beta, fact, False)
    run = await run_agent(None, "t", agent="tester", cwd=str(tmp_path), mesh=False)
    await asyncio.wait_for(run.wait(), 30)
    saved = reg.get_run(run.run_id)
    assert (saved.provider, saved.model) == ("alpha", "a-mid")
    assert [(s.candidate.provider, s.reason) for s in saved.skipped] == [("beta", reason)]


@pytest.mark.asyncio
async def test_a_switched_off_provider_is_skipped_with_its_reason(team, tmp_path, monkeypatch):
    monkeypatch.setattr("interact.agents.run.load_policy", lambda: Policy(
        agents={"tester": CRITERION}, reasoning={"tester": "medium"}, providers={"beta": False},
    ))
    run = await run_agent(None, "t", agent="tester", cwd=str(tmp_path), mesh=False)
    await asyncio.wait_for(run.wait(), 30)
    saved = reg.get_run(run.run_id)
    assert saved.provider == "alpha" and [s.reason for s in saved.skipped] == ["provider_off"]


@pytest.mark.asyncio
async def test_every_candidate_unavailable_is_one_clear_failure(team, tmp_path):
    _Beta.installed = False
    _Alpha.logged_in = False
    with pytest.raises(ModelUnavailable) as caught:
        await run_agent(None, "t", agent="tester", cwd=str(tmp_path), mesh=False)
    text = str(caught.value)
    assert "beta/b-strong: cli_missing" in text and "alpha/a-mid: unauthenticated" in text
    assert "alpha/a-weak: unauthenticated" in text


@pytest.mark.asyncio
async def test_an_explicit_provider_filters_the_same_auth_checked_path(team, tmp_path):
    alpha, beta = team
    _Beta.installed = False
    with pytest.raises(RuntimeError, match="not installed"):
        await run_agent(beta, "t", agent="tester", cwd=str(tmp_path), mesh=False)
    run = await run_agent(alpha, "t", agent="tester", cwd=str(tmp_path), mesh=False)
    await asyncio.wait_for(run.wait(), 30)
    saved = reg.get_run(run.run_id)
    assert saved.provider == "alpha" and saved.skipped == ()
    assert [c.provider for c in saved.candidates] == ["alpha", "alpha"]
    assert _Alpha.probes == 1 and _Beta.probes == 0


@pytest.mark.asyncio
async def test_explicit_provider_logged_out_is_refused_without_running_another(team, tmp_path):
    alpha, _ = team
    _Alpha.logged_in = False
    with pytest.raises(ModelUnavailable, match="unauthenticated"):
        await run_agent(alpha, "t", agent="tester", cwd=str(tmp_path), mesh=False)
    assert _Alpha.probes == 1 and _Beta.probes == 0


@pytest.mark.asyncio
async def test_unenforceable_role_tools_skip_candidate_without_weakening_role(team, tmp_path, monkeypatch):
    def reject(self, allowed_tools, denied_tools):
        raise UnsupportedToolPolicy("cannot enforce")
    monkeypatch.setattr(_Beta, "validate_tool_policy", reject)
    run = await run_agent(None, "t", agent="tester", cwd=str(tmp_path), mesh=False)
    await asyncio.wait_for(run.wait(), 30)
    saved = reg.get_run(run.run_id)
    assert saved.provider == "alpha"
    assert [item.reason for item in saved.skipped] == ["tool_policy_unsupported"]


@pytest.mark.asyncio
async def test_a_failure_after_launch_is_the_runs_outcome_not_a_retry(team, tmp_path, monkeypatch):
    crashing = _Crashing()
    monkeypatch.setitem(PROVIDERS, "alpha", crashing)
    monkeypatch.setattr("interact.agents.run.PROVIDERS", {"alpha": crashing})
    monkeypatch.setitem(reg.PROVIDERS, "alpha", crashing)
    spawned = []
    original = asyncio.create_subprocess_exec

    async def counting(*argv, **kwargs):
        spawned.append(argv)
        return await original(*argv, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", counting)
    run = await run_agent(None, "t", agent="tester", cwd=str(tmp_path), mesh=False)
    await asyncio.wait_for(run.wait(), 30)
    saved = reg.get_run(run.run_id)
    assert saved.status == "failed" and saved.provider == "alpha" and saved.skipped == ()
    assert len(spawned) == 1


@pytest.mark.asyncio
async def test_a_permission_mode_the_candidate_cannot_honour_skips_it(team, tmp_path, monkeypatch):
    monkeypatch.setattr(_Alpha, "permission_modes", lambda self: [PermissionMode("careful", "Careful", "asks")])
    run = await run_agent(None, "t", agent="tester", cwd=str(tmp_path), mesh=False, permission_mode="careful")
    await asyncio.wait_for(run.wait(), 30)
    saved = reg.get_run(run.run_id)
    assert saved.provider == "alpha" and [s.reason for s in saved.skipped] == ["permission_mode_unsupported"]


@pytest.mark.asyncio
async def test_ranked_launch_preserves_workspace_permissions_for_the_chosen_provider(team, tmp_path, monkeypatch):
    monkeypatch.setattr(_Beta, "permission_modes", lambda self: [PermissionMode("careful", "Careful", "asks")])
    run = await run_agent(None, "t", agent="tester", cwd=str(tmp_path), mesh=False, provider_modes={"beta": "careful"})
    await asyncio.wait_for(run.wait(), 30)
    saved = reg.get_run(run.run_id)
    assert saved.provider == "beta" and saved.permission_mode == "careful"


def test_a_historical_record_loads_with_no_candidates():
    run = reg.AgentRun(run_id="old", provider="claude", name="old")
    assert run.candidates == () and run.skipped == ()


def _capture(seen):
    async def capture(provider, task, **kwargs):
        seen.append(provider)
        raise RuntimeError("stop here")
    return capture


@pytest.mark.asyncio
async def test_mcp_spawn_defaults_to_the_ranked_choice(monkeypatch):

    seen = []
    monkeypatch.setattr(tools_agents, "run_agent", _capture(seen))
    out = await tools_agents.agent_spawn("do it", session_id="fixture-conversation")
    assert out.startswith("ERROR") and "stop here" in out
    assert seen == [None]


def test_cli_spawn_defaults_to_the_ranked_choice(monkeypatch):
    # `interact.cli.app` is both a module and the re-exported App object; the command reads the
    # runner off the MODULE, so import it explicitly rather than by attribute access.
    commands = cli
    cli_module = importlib.import_module("interact.cli.app")
    seen = []
    monkeypatch.setattr(cli_module, "_run_agent_for_cli", _capture(seen), raising=False)
    with pytest.raises(SystemExit):
        commands.agents_spawn("do it", agent="tester", session_id="fixture-conversation")
    assert seen == [None]
