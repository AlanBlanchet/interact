"""CLI surfaces tell ONE story about model selection: `status`/`providers`/`doctor` all print the
RESOLVED model per role (not an opaque 'auto'), plus the sovereign quality tier — and `version`/`-v`
report the build. A grep of availability isn't the answer; resolution (frontier-first, first-available)
is. The shared helper is exercised here once; the three commands just call it."""

import pytest

from interact import cli


@pytest.fixture
def _only_zai(monkeypatch):
    # ONLY the z.ai GLM reachable → resolution is deterministic without real keys.
    monkeypatch.setattr("interact.models.Model.is_available", lambda self: self.id == "zai/glm-4.5v")


def test_resolved_models_helper_names_every_task_with_its_role_knob(_only_zai, capsys):
    cli._print_resolved_models()
    out = capsys.readouterr().out
    # the view is TASK-centric — each thing a user does is named...
    for task in ("screenshot", "get_interactive_elements", "transcribe", "review_ui", "measure_ui"):
        assert task in out
    # ...with the config knob (role) in brackets so it's clear what to pin
    for role in ("[image]", "[component]", "[video]", "[audio]"):
        assert role in out
    # review_ui/verify_ui resolve by STAKES to the sovereign GLM the z.ai key lights up at low/medium
    assert "zai/glm-4.5v" in out and "low/medium tier" in out


def test_resolved_models_helper_flags_a_missing_key(monkeypatch, capsys):
    monkeypatch.setattr("interact.models.Model.is_available", lambda self: False)  # nothing reachable
    cli._print_resolved_models()
    out = capsys.readouterr().out
    assert "⚠ key missing" in out          # a pick that will error is called out, not shown silently
    assert "fall back to frontier" in out   # low/medium honestly report the absence of a sovereign key


def test_providers_includes_the_resolved_selection(_only_zai, capsys):
    cli.providers()
    out = capsys.readouterr().out
    assert "Resolved selection" in out and "zai/glm-4.5v" in out


def test_version_command_prints_the_installed_version(capsys):
    from interact import installed_version

    cli.version()
    assert capsys.readouterr().out.strip() == installed_version()


def test_dash_v_alias_is_registered_alongside_double_dash_version():
    # users reach for `-v`; cyclopts wires only `--version` by default, so we add the alias
    assert "-v" in cli.app.version_flags and "--version" in cli.app.version_flags


# --- `agents modes`: the autonomy choices, machine-readably ---------------------------------


def test_modes_prints_one_tab_separated_row_per_mode(capsys):
    from interact.cli.app import agents_modes

    from interact.agents.providers import ClaudeCodeProvider

    agents_modes(provider="claude")
    rows = [r for r in capsys.readouterr().out.splitlines() if r]
    # Against the provider's own list, not a hardcoded 6 — a count copied from a collection in
    # hand is a second source of truth that only ever goes stale.
    assert len(rows) == len(ClaudeCodeProvider().permission_modes())
    for row in rows:
        ident, label, detail, unrestricted = row.split("\t")
        assert ident and label and detail
        assert unrestricted in ("yes", "no")


def test_the_unrestricted_mode_is_flagged_in_the_machine_output(capsys):
    """The panel has to mark it. A flag it must infer from wording would break the day the
    wording changes — the same failure that made `agents definitions` exist."""
    from interact.cli.app import agents_modes

    agents_modes(provider="claude")
    flagged = [r.split("\t")[0] for r in capsys.readouterr().out.splitlines()
               if r.endswith("\tyes")]
    assert flagged == ["bypassPermissions"]


def test_a_provider_with_no_verified_modes_prints_nothing(capsys):
    """Not a line of prose: a caller splitting on newlines would read it as a mode."""
    from interact.cli.app import agents_modes

    agents_modes(provider="codex")
    assert capsys.readouterr().out == ""


# --- `agents discovered`: the sessions interact did NOT start, machine-readably ---------------
#
# The VS Code panel reads the registry DIRECTLY off disk, and a foreign session has no record on
# disk — it is discovered at list time. So the panel could never show one, despite carrying an
# icon and a tooltip for them, and "i have agents in the sheets folder elsewhere, and i can't
# change and see how they work" was literally true: the panel had no way to learn they existed.


def test_discovered_prints_one_json_object_per_line(monkeypatch, capsys):
    import json

    from interact.agents import registry as reg
    from interact.cli.app import agents_discovered

    monkeypatch.setattr(reg, "_discover_foreign", lambda: [
        {"sessionId": "s-1", "name": "sheets-ab", "cwd": "/workspace/xp/sheets",
         "kind": "interactive", "pid": 4242},
    ])
    agents_discovered()
    rows = [json.loads(r) for r in capsys.readouterr().out.splitlines() if r.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == "s-1" and row["name"] == "sheets-ab"
    assert row["foreign"] is True and row["status"] == "foreign"
    assert row["cwd"] == "/workspace/xp/sheets"


def test_discovered_files_each_session_under_its_project(capsys, monkeypatch, tmp_path):
    """The whole point: the panel groups by project, so a session with no project is unreachable
    by folder however visible it is in a flat list."""
    import json

    from interact.agents import registry as reg
    from interact.cli.app import agents_discovered

    sheets = tmp_path / "xp" / "sheets"
    (sheets / ".git").mkdir(parents=True)
    monkeypatch.setattr(reg, "_discover_foreign", lambda: [
        {"sessionId": "s-1", "name": "sheets-ab", "cwd": str(sheets), "kind": "interactive"},
    ])
    agents_discovered()
    assert json.loads(capsys.readouterr().out.strip())["project"] == "sheets"


def test_discovered_prints_nothing_when_there_are_none(capsys, monkeypatch):
    """Not a line of prose — the caller parses each line as JSON."""
    from interact.agents import registry as reg
    from interact.cli.app import agents_discovered

    monkeypatch.setattr(reg, "_discover_foreign", lambda: [])
    agents_discovered()
    assert capsys.readouterr().out == ""


def test_a_broken_discovery_is_LOUD_rather_than_an_empty_answer(capsys, monkeypatch):
    """The first version of this test certified the swallow: it asserted stdout was empty and
    called that "surviving". But an empty stdout is what "you have no other sessions" looks like,
    so a real bug here would cache as a plausible answer and re-cache every refresh forever, with
    nothing anywhere saying why. Each provider already swallows its own failure — reaching this
    handler at all means something is actually wrong, which is exactly what must be said."""
    import pytest as _pytest

    from interact.agents import registry as reg
    from interact.cli.app import agents_discovered

    def boom():
        raise OSError("no such directory")

    monkeypatch.setattr(reg, "_discover_foreign", boom)
    with _pytest.raises(SystemExit) as exit_info:
        agents_discovered()
    assert exit_info.value.code != 0, "a failure must not exit 0"
    captured = capsys.readouterr()
    assert captured.out == "", "stdout is the data channel — it stays parseable or empty"
    assert "ERROR" in captured.err and "no such directory" in captured.err


def test_the_permission_flag_spelling_is_pinned_end_to_end(monkeypatch):
    """The panel builds `--permission-mode <id>` as a literal string (org.ts `spawnArgs`) and the
    CLI receives it as a cyclopts parameter named `permission_mode`. Nothing pinned the two
    together: rename either and the spawn silently falls back to the CLI's own default while the
    panel tells the user it chose "plan". For a SAFETY control, silently doing something other
    than what the UI reported is the worst available failure.
    """
    import importlib

    # `interact.cli` re-exports the cyclopts `app` object, and that attribute shadows the
    # submodule — the same trap test_agent_run.py already documents.
    cli = importlib.import_module("interact.cli.app")

    got = {}

    class _Handle:
        run_id = "r-1"

        async def wait(self):
            return 0

    async def _spawn(provider, task, **kwargs):
        got.update(kwargs)
        return _Handle()

    monkeypatch.setattr(cli, "_run_agent_for_cli", _spawn, raising=False)
    cli.agents_spawn("do a thing", permission_mode="plan")
    assert got.get("permission_mode") == "plan", (
        "the CLI did not receive the mode the panel sends — the flag spelling has drifted")


def test_an_unknown_mode_at_the_CLI_reads_like_every_other_error(monkeypatch, capsys):
    """`command()` validates, but it is an argv BUILDER four frames below the boundary — the MCP
    tool catches its ValueError and the CLI did not, so `--permission-mode typo` printed a
    traceback where every other interact failure prints one actionable line.
    """
    import importlib

    cli = importlib.import_module("interact.cli.app")

    with pytest.raises(SystemExit) as exit_info:
        cli.agents_spawn("t", permission_mode="definitely-not-a-mode")
    assert exit_info.value.code != 0
    said = capsys.readouterr()
    combined = said.out + said.err
    assert "ERROR" in combined, combined
    assert "definitely-not-a-mode" in combined
    # Names what IS accepted — an error that only says "no" costs another round trip.
    assert "plan" in combined


def test_agents_run_reports_a_bad_mode_too(monkeypatch, capsys):
    """`agents run` is the streaming sibling of `agents spawn` and validates the same value. Its
    handler referenced `sys` without importing it — so the one path meant to produce a clean line
    would have raised NameError instead. One report is one sample of a class."""
    import importlib

    cli = importlib.import_module("interact.cli.app")

    with pytest.raises(SystemExit) as exit_info:
        cli.agents_run("t", permission_mode="definitely-not-a-mode")
    assert exit_info.value.code != 0
    combined = "".join(capsys.readouterr())
    assert "ERROR" in combined and "definitely-not-a-mode" in combined, combined
