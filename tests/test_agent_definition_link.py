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


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "agents_dir", lambda: tmp_path / "agents")


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
