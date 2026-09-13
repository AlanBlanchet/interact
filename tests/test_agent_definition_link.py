"""Alan asked to see, for a running agent, "context, system prompt (a file link is enough),
basically everything". The registry has known where a definition's system prompt lives since the
`agent` field was added — its own docstring says "A link to it is what makes 'what IS this agent'
answerable from a panel" — but the path was only ever resolvable by calling Python, and the VS Code
panel reads the run records straight off disk. So nothing ever linked to it, and the ask went
undelivered while the field that exists to serve it sat there looking done.

Recording the path ON the run makes it reachable by every reader of a record, not only by a caller
that can import the registry.
"""

from pathlib import Path

import pytest

from interact.agents import registry
from interact.config import UserConfig


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "agents_dir", lambda: tmp_path / "agents")
    monkeypatch.setattr(UserConfig, "PATH", tmp_path / "config.env")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def test_a_run_that_IS_an_agent_records_where_its_system_prompt_lives(monkeypatch, tmp_path):
    definition = tmp_path / "visual-critic.md"
    definition.write_text("# visual critic\n")
    monkeypatch.setattr(
        registry.PROVIDERS["claude"], "definition_path", lambda agent: definition if agent == "visual-critic" else None
    )

    run = registry.register(
        run_id="r1", pid=1, provider="claude", name="visual-critic", agent="visual-critic"
    )

    assert run.definition_path == str(definition)
    assert registry._read_record("r1").definition_path == str(definition), "and it survives the round trip"


def test_a_plain_run_records_no_definition():
    run = registry.register(run_id="r2", pid=2, provider="claude", name="a task")
    assert run.definition_path is None


def test_an_agent_whose_definition_file_is_missing_records_nothing(monkeypatch):
    monkeypatch.setattr(registry.PROVIDERS["claude"], "definition_path", lambda agent: None)
    run = registry.register(run_id="r3", pid=3, provider="claude", name="x", agent="ghost")
    assert run.definition_path is None, "a link to a file that does not exist is worse than none"


def test_a_record_written_before_the_field_existed_is_backfilled(monkeypatch, tmp_path):
    """Otherwise the client has to keep its own copy of where a provider stores definitions —
    which is the vendor hard-coding this change exists to remove. Records already on disk are
    repaired on read instead, so the guess has nobody left to serve."""
    definition = tmp_path / "researcher.md"
    definition.write_text("# researcher\n")
    monkeypatch.setattr(registry.PROVIDERS["claude"], "definition_path", lambda agent: definition)

    run = registry.register(run_id="old", pid=1, provider="claude", name="researcher", agent="researcher")
    # Rewrite it the way an older interact would have: with no definition_path at all.
    stored = registry._record_path("old")
    stored.write_text(run.model_dump_json(exclude={"definition_path"}))

    assert registry._read_record("old").definition_path == str(definition)
    assert "definition_path" not in stored.read_text(), "reading history does not rewrite its provenance"


def test_server_mode_preserves_retired_history_without_catalog_lookup(monkeypatch, tmp_path):
    registry.CatalogConnection.path().write_text('{}')
    def unexpected_lookup(agent):
        raise AssertionError('history must not resolve roles against a live catalog')
    monkeypatch.setattr(registry.PROVIDERS['claude'], 'definition_path', unexpected_lookup)
    run = registry.AgentRun(run_id='old-retired', provider='claude', name='retired', agent='retired')
    directory = registry.agents_dir()
    directory.mkdir()
    (directory / 'old-retired.json').write_text(run.model_dump_json(exclude={'definition_path'}))
    (directory / 'old-retired.json').chmod(0o600)
    assert registry._read_record('old-retired').definition_path is None
    assert registry.resolve_run_id('old-retired') == 'old-retired'


def test_backfill_does_not_touch_a_plain_run(monkeypatch, tmp_path):
    monkeypatch.setattr(registry.PROVIDERS["claude"], "definition_path", lambda agent: tmp_path / "x.md")
    registry.register(run_id="plain", pid=1, provider="claude", name="a task")
    before = registry._record_path("plain").read_text()
    assert registry._read_record("plain").definition_path is None
    assert registry._record_path("plain").read_text() == before, "no pointless rewrite"
