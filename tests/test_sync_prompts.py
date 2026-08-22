"""Tests for scripts/sync_prompts.py — the per-developer prompts overlay materializer."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(module: str):
    spec = importlib.util.spec_from_file_location(module, _SCRIPTS / f"{module}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def sync_mod(tmp_path, monkeypatch):
    """Load sync_prompts with its REPO_ROOT pointed at a scratch tree."""
    mod = _load("sync_prompts")
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(mod, "_MANIFEST", tmp_path / "repo" / ".github" / "agents" / ".sync-prompts.json")
    return mod


def _write(d: Path, *names: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / n).write_text(f"# {n}\n")


def test_flat_prompts_dir_routes_each_layer_to_its_overlay(sync_mod, tmp_path):
    src = tmp_path / "user-prompts"
    _write(src, "librarian.agent.md", "alan.instructions.md", "x.prompt.md", "release.skill.md", "note.md")
    rc = sync_mod.sync(src, into=None, ext=".md", mode="copy", dry=False)
    assert rc == 0
    root = sync_mod.REPO_ROOT
    assert (root / ".github/agents/librarian.agent.md").is_file()
    assert (root / ".github/instructions/alan.instructions.md").is_file()
    assert (root / ".github/prompts/x.prompt.md").is_file()
    assert (root / ".github/skills/release/SKILL.md").is_file()
    assert not (root / ".github/agents/note.md").exists()  # no recognizable layer → skipped


def test_uniform_source_materializes_every_file_to_one_overlay(sync_mod, tmp_path):
    src = tmp_path / "agents"
    _write(src, "advocate.md", "tester.md")
    rc = sync_mod.sync(src, into="agents", ext=".md", mode="copy", dry=False)
    assert rc == 0
    assert (sync_mod.REPO_ROOT / ".github/agents/advocate.agent.md").is_file()
    assert (sync_mod.REPO_ROOT / ".github/agents/tester.agent.md").is_file()


def test_skill_source_becomes_skill_md_under_named_folder(sync_mod, tmp_path):
    src = tmp_path / "skills" / "coding"
    _write(src, "SKILL.md")
    rc = sync_mod.sync(src, into="skills", ext=".md", mode="copy", dry=False)
    assert rc == 0
    assert (sync_mod.REPO_ROOT / ".github/skills/SKILL/SKILL.md").is_file()


def test_dry_run_writes_nothing(sync_mod, tmp_path):
    src = tmp_path / "p"
    _write(src, "librarian.agent.md")
    rc = sync_mod.sync(src, into=None, ext=".md", mode="copy", dry=True)
    assert rc == 0
    assert not (sync_mod.REPO_ROOT / ".github").exists()


def test_sync_writes_a_manifest_for_re_materialization(sync_mod, tmp_path):
    src = tmp_path / "p"
    _write(src, "librarian.agent.md")
    sync_mod.sync(src, into=None, ext=".md", mode="copy", dry=False)
    manifest = json.loads(sync_mod._MANIFEST.read_text())
    assert manifest["source"] == str(src)
    assert manifest["files"] == [".github/agents/librarian.agent.md"]


def test_resync_prunes_entries_with_no_source_counterpart(sync_mod, tmp_path):
    src = tmp_path / "p"
    _write(src, "a.agent.md", "b.agent.md")
    sync_mod.sync(src, into=None, ext=".md", mode="copy", dry=False)
    (src / "b.agent.md").unlink()  # upstream deleted it
    sync_mod.sync(src, into=None, ext=".md", mode="copy", dry=False)
    agents = sync_mod.REPO_ROOT / ".github/agents"
    assert (agents / "a.agent.md").exists()
    assert not (agents / "b.agent.md").exists()


def test_missing_source_fails_loudly(sync_mod, tmp_path, capsys):
    rc = sync_mod.sync(tmp_path / "nope", into=None, ext=".md", mode="copy", dry=False)
    assert rc == 1
    assert "not a directory" in capsys.readouterr().err
