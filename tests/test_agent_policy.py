"""One file that says how agents run here: profiles, toolsets, and which providers are on.

"we should be able to, from interact, chose if we activate the agents or not for a provider
(claude, codex, other...)... profiles, such that we can write the rules and apply them to
multiple models instead of having to write conditions for each agent... Same for tools, we don't
have toolsets yet and are having to write interact__xxx to select some of our MCP tools..."

All three are the same shape — a NAME standing for a rule you would otherwise repeat — so they
live in one file with one grammar rather than three conventions to remember.
"""

import json

import pytest

from interact.agents.policy import Policy, PolicyError


@pytest.fixture
def policy_file(tmp_path):
    path = tmp_path / "agents.json"
    path.write_text(json.dumps({
        "profiles": {
            "eyes": "cap.vlm and price.in < 10",
            "thrifty": "price.in < 1",
        },
        "agents": {
            "visual-critic": "@eyes",
            "ux-critic": "@eyes",
            "librarian": "aa.intelligence >= 30",
            "scraper": "claude-sonnet-5",
        },
        "toolsets": {
            "vision": ["screenshot", "review_ui", "measure_ui"],
            "browse": ["navigate", "@vision"],
        },
        "agent_tools": {"visual-critic": ["@browse", "get_page_state"]},
        "providers": {"claude": True, "codex": False},
    }))
    return path


def test_a_profile_is_written_once_and_worn_by_many(policy_file):
    """The ask in one line: "write the rules and apply them to multiple models".

    A profile is referenced with `@`, exactly as a toolset references another toolset — one
    sigil for "a name I defined above", so an unknown one is an error rather than being
    mistaken for a model id nobody has heard of.
    """
    p = Policy.load(policy_file)
    assert p.criterion_for("visual-critic") == "cap.vlm and price.in < 10"
    assert p.criterion_for("ux-critic") == p.criterion_for("visual-critic")


def test_an_agent_may_still_speak_for_itself(policy_file):
    """A profile is a convenience, never a cage: an inline criterion and a plain model id both
    still work, so one odd agent needs no profile invented for it."""
    p = Policy.load(policy_file)
    assert p.criterion_for("librarian") == "aa.intelligence >= 30"
    assert p.criterion_for("scraper") == "claude-sonnet-5"
    assert p.criterion_for("nobody-mentioned") is None


def test_a_profile_that_does_not_exist_is_caught_when_the_file_is_read(policy_file):
    """Not at 3am when that agent happens to spawn."""
    policy_file.write_text(json.dumps({"agents": {"a": "@ghost-profile"}}))
    with pytest.raises(PolicyError) as e:
        Policy.load(policy_file)
    assert "ghost-profile" in str(e.value)


def test_toolsets_expand_so_nobody_types_the_prefix_twice(policy_file):
    """"we don't have toolsets yet and are having to write interact__xxx" — a toolset is named
    once and expands to the server-prefixed tool names the vendor CLI wants."""
    p = Policy.load(policy_file)
    assert p.tools_for("visual-critic") == [
        "mcp__interact__navigate", "mcp__interact__screenshot",
        "mcp__interact__review_ui", "mcp__interact__measure_ui",
        "mcp__interact__get_page_state",
    ]


def test_a_toolset_may_include_another(policy_file):
    """"browse" wears "vision" — sets compose, or every set repeats its neighbours."""
    p = Policy.load(policy_file)
    assert "mcp__interact__screenshot" in p.expand_toolset("browse")


def test_a_toolset_cycle_is_refused_rather_than_hanging(policy_file):
    policy_file.write_text(json.dumps({"toolsets": {"a": ["@b"], "b": ["@a"]}}))
    with pytest.raises(PolicyError) as e:
        Policy.load(policy_file)
    assert "cycle" in str(e.value).lower()


def test_providers_can_be_switched_off_from_interact(policy_file):
    """"chose if we activate the agents or not for a provider (claude, codex, other...)"."""
    p = Policy.load(policy_file)
    assert p.provider_active("claude") is True
    assert p.provider_active("codex") is False
    # Anything not mentioned is ON: a provider you installed is a provider you meant to use.
    assert p.provider_active("gemini") is True


def test_a_missing_file_is_an_empty_policy_not_a_crash(tmp_path):
    p = Policy.load(tmp_path / "nothing.json")
    assert p.criterion_for("anyone") is None
    assert p.tools_for("anyone") == []
    assert p.provider_active("claude") is True


def test_switching_a_provider_off_and_on_round_trips(policy_file):
    """The setting is written back, so the extension's toggle and the CLI agree."""
    p = Policy.load(policy_file)
    p.set_provider_active("codex", True, path=policy_file)
    assert Policy.load(policy_file).provider_active("codex") is True
    # and the rest of the file survives the write
    assert Policy.load(policy_file).criterion_for("visual-critic") == "cap.vlm and price.in < 10"


def test_the_policy_reaches_the_spawn(policy_file, monkeypatch):
    """The seam that makes all three asks real: at spawn, an agent's profile decides its model,
    its toolset becomes the vendor's allow-list, and a switched-off provider refuses."""
    import interact.agents.run as run_mod
    from interact.agents.policy import Policy

    monkeypatch.setattr(run_mod, "load_policy", lambda: Policy.load(policy_file))

    # A profile decides the model without the agent naming one.
    assert run_mod.model_for_agent("visual-critic") == "cap.vlm and price.in < 10"
    assert run_mod.model_for_agent("nobody-mentioned") is None

    # A toolset becomes the vendor's allow-list, fully prefixed.
    tools = run_mod.tools_for_agent("visual-critic")
    assert "mcp__interact__screenshot" in tools and "mcp__interact__navigate" in tools

    # A provider switched off refuses to spawn at all, and says why.
    with pytest.raises(RuntimeError) as e:
        run_mod.check_provider_active("codex")
    assert "codex" in str(e.value) and "agents.json" in str(e.value)
    run_mod.check_provider_active("claude")  # active: no raise


def test_the_allow_list_reaches_the_vendor_command():
    """A toolset is only real if the vendor CLI is actually told about it."""
    from interact.agents.providers import provider_for

    claude = provider_for("claude")
    argv = claude.command("t", cwd=".", model=None, mcp_config=None, run_id="r",
                          allowed_tools=["mcp__interact__screenshot", "mcp__interact__navigate"])
    assert "--allowedTools" in argv
    assert argv[argv.index("--allowedTools") + 1] == "mcp__interact__screenshot,mcp__interact__navigate"
    # No toolset configured: no flag at all, so an unrestricted agent stays unrestricted.
    assert "--allowedTools" not in claude.command(
        "t", cwd=".", model=None, mcp_config=None, run_id="r")


# ── the CLI surface: "from interact", not from a JSON file ─────────────────────────────────────

@pytest.fixture
def cli_policy(policy_file, monkeypatch):
    """Point every policy read/write at the fixture file."""
    import interact.agents.policy as pol
    monkeypatch.setattr(pol, "policy_path", lambda: policy_file)
    return policy_file


def test_variables_lists_every_comparison_with_its_source(capsys):
    """The discovery surface: you cannot write `aa.mmmu > 0.7` if nothing tells you it exists."""
    from interact.cli.app import agents_variables

    agents_variables()
    out = capsys.readouterr().out
    assert "aa.intelligence" in out and "gui.screenspot" in out and "price.in" in out
    assert "cap.vlm" in out
    assert "Artificial Analysis" in out, "each variable says who measured it"


def test_policy_shows_what_each_agent_resolves_to(cli_policy, capsys):
    from interact.cli.app import agents_policy

    agents_policy()
    out = capsys.readouterr().out
    assert "visual-critic" in out and "@eyes" in out and "cap.vlm and price.in < 10" in out
    assert "vision" in out and "mcp__interact__screenshot" in out
    assert "codex" in out and "off" in out
    # The resolution shown is the one the SPAWN will make — per switched-on vendor CLI, from the
    # pool that CLI can run — not the catalog's cheapest, which the claude binary cannot run.
    line = next(l for l in out.splitlines() if l.strip().startswith("visual-critic"))
    assert "claude ⇒" in line and "gemini" not in line, line
    assert "codex ⇒" not in line, "a switched-off provider is not consulted"


def test_providers_toggle_from_the_cli(cli_policy, capsys):
    """"chose if we activate the agents or not for a provider" — one command, and it persists."""
    from interact.agents.policy import Policy
    from interact.cli.app import agents_providers

    agents_providers()                      # list
    out = capsys.readouterr().out
    assert "claude" in out and "on" in out and "codex" in out and "off" in out

    agents_providers("codex", "on")
    assert Policy.load(cli_policy).provider_active("codex") is True
    agents_providers("claude", "off")
    assert Policy.load(cli_policy).provider_active("claude") is False

    with pytest.raises(SystemExit):
        agents_providers("codex", "sideways")   # not on/off: refused, not guessed


# ── one file, for the panel and the spawn alike ────────────────────────────────────────────────

def test_the_policy_lives_beside_config_env_not_under_the_debug_dir(monkeypatch):
    """On a box that relocates its dumps (INTERACT_DEBUG_DIR), the policy must not move with
    them: the CLI found `<repo>/out/agents.json` while the panel wrote `~/.interact/agents.json`
    — one fact, two files, and a choice that never bit."""
    from interact.agents.policy import policy_path
    from interact.config import UserConfig

    monkeypatch.setenv("INTERACT_DEBUG_DIR", "/tmp/somewhere/else/out")
    assert policy_path() == UserConfig.PATH.parent / "agents.json"


def test_a_profile_may_be_named_wherever_a_model_is(policy_file, monkeypatch):
    """`--model @eyes` on the CLI, `@eyes` chosen in the panel: a profile is a NAME for a model
    rule, so it works everywhere a model id does — resolved to a real model before the vendor
    CLI sees it, and an unknown one refused by name."""
    import interact.agents.run as run_mod
    from interact.agents.policy import Policy

    monkeypatch.setattr(run_mod, "load_policy", lambda: Policy.load(policy_file))
    _, via_profile = run_mod.resolve_model("@eyes", {}, available_only=False)
    _, via_rule = run_mod.resolve_model("cap.vlm and price.in < 10", {}, available_only=False)
    assert via_profile is not None and not via_profile.startswith("@")
    assert via_profile == via_rule, "a profile resolves to exactly what its rule resolves to"
    with pytest.raises(Exception) as e:
        run_mod.resolve_model("@ghost", {}, available_only=False)
    assert "ghost" in str(e.value) and "eyes" in str(e.value), "name the typo AND what exists"


def test_a_broken_policy_is_never_overwritten_by_a_toggle(tmp_path):
    """The file holds profiles and toolsets somebody typed. One missing comma must not let a
    provider switch flatten it to `{"providers": {...}}` — refuse, and name the file to fix."""
    path = tmp_path / "agents.json"
    path.write_text("{ not json at all")
    with pytest.raises(PolicyError) as e:
        Policy().set_provider_active("codex", False, path)
    assert str(path) in str(e.value)
    assert path.read_text() == "{ not json at all", "their broken file is theirs to fix"


def test_the_cli_says_one_line_when_nothing_clears_a_criterion(monkeypatch, capsys):
    """`interact agents spawn --model "aa.intelligence > 999"` printed a Python traceback where
    every other interact failure prints one actionable ERROR line — and the model was resolved
    AFTER the vendor argv had been built, so the binary would have been handed the raw text."""
    import interact.agents.providers as providers
    from interact.cli.app import agents_spawn

    class _Vendor:
        name = "claude"
        native_providers = frozenset({"anthropic"})

        def available(self):
            return True

        def can_run(self, model, env):
            return model.provider in self.native_providers

        def model_id_for(self, model):
            return model.id

        def command(self, *a, **k):
            raise AssertionError("nothing clears the bar — the vendor CLI must never be reached")

    monkeypatch.setattr(providers, "provider_for", lambda name: _Vendor())
    with pytest.raises(SystemExit) as stop:
        agents_spawn("say hi", model="aa.intelligence > 999")
    assert stop.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("ERROR:") and "999" in err and "Traceback" not in err
