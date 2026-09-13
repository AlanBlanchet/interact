import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import threading

import pytest

from interact.cli import prompts as prompt_commands
from interact.config import UserConfig


@pytest.fixture(autouse=True)
def unconfigured_prompt_home(tmp_path, monkeypatch):
    """Local-Git tests must not inherit the owner's configured server connection."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(UserConfig, "PATH", tmp_path / "home" / ".interact" / "config.env")


def _prompt_cli(data_home: Path, *arguments: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update({"XDG_DATA_HOME": str(data_home), "UV_OFFLINE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    return subprocess.run(
        ["uv", "run", "interact", "prompts", *arguments],
        input=stdin, text=True, capture_output=True, timeout=30, env=environment,
    )


def test_prompt_editor_cli_catalog_read_and_cas_conflict_preserve_disk_and_buffer(tmp_path: Path) -> None:
    source = tmp_path / "interact" / "prompts"
    (source / "agents").mkdir(parents=True)
    prompt = source / "agents" / "review.md"
    prompt.write_text("first")
    (source / "outside.md").write_text("outside")
    (source / "agents" / "link.md").symlink_to(source / "outside.md")

    catalog = _prompt_cli(tmp_path, "catalog")
    assert catalog.returncode == 0
    assert json.loads(catalog.stdout) == {"ok": True, "files": ["agents/review.md", "outside.md"]}
    read = _prompt_cli(tmp_path, "read", "agents/review.md")
    payload = json.loads(read.stdout)
    assert payload["content"] == "first"
    prompt.write_text("other client")
    conflict = _prompt_cli(tmp_path, "write", "agents/review.md", payload["digest"], stdin="my buffer")
    assert conflict.returncode == 2
    assert json.loads(conflict.stdout)["error"].startswith("prompt source changed")
    assert prompt.read_text() == "other client"


def test_prompt_editor_rejects_a_symlinked_parent_outside_the_source(tmp_path: Path) -> None:
    source = tmp_path / "interact" / "prompts"
    outside = tmp_path / "outside"
    source.mkdir(parents=True)
    outside.mkdir()
    (outside / "escaped.md").write_text("private")
    (source / "linked").symlink_to(outside, target_is_directory=True)

    for command in (("read", "linked/escaped.md"),
                    ("write", "linked/escaped.md", hashlib.sha256(b"private").hexdigest())):
        result = _prompt_cli(tmp_path, *command, stdin="replacement")
        assert result.returncode == 2
    assert (outside / "escaped.md").read_text() == "private"


def test_prompt_editor_releases_its_lock_when_post_lock_validation_fails(
    tmp_path: Path, monkeypatch,
) -> None:
    source = tmp_path / "interact" / "prompts"
    source.mkdir(parents=True)
    target = source / "instructions.md"
    target.write_text("old")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(prompt_commands.os, "rename", lambda *args, **kwargs: (_ for _ in ()).throw(
        OSError("path changed after lock")
    ))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"new")))
    with pytest.raises(SystemExit) as raised:
        prompt_commands.write("instructions.md", hashlib.sha256(b"old").hexdigest())
    assert raised.value.code == 2
    assert not (source / ".instructions.md.interact.lock").exists()


def test_prompt_editor_cli_writes_exact_stdin_after_matching_digest(tmp_path: Path) -> None:
    source = tmp_path / "interact" / "prompts"
    source.mkdir(parents=True)
    prompt = source / "instructions.md"
    prompt.write_text("old")
    expected = hashlib.sha256(b"old").hexdigest()
    written = _prompt_cli(tmp_path, "write", "instructions.md", expected, stdin="new content")
    assert written.returncode == 0, written.stderr
    assert prompt.read_text() == "new content"
    assert json.loads(written.stdout)["digest"] == hashlib.sha256(b"new content").hexdigest()


def test_two_overlapping_prompt_writes_have_one_winner_and_one_typed_conflict(tmp_path: Path) -> None:
    source = tmp_path / "interact" / "prompts"
    source.mkdir(parents=True)
    prompt = source / "instructions.md"
    prompt.write_text("old")
    expected = hashlib.sha256(b"old").hexdigest()
    environment = os.environ.copy()
    environment.update({"XDG_DATA_HOME": str(tmp_path), "UV_OFFLINE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    processes = [subprocess.Popen(
        ["uv", "run", "interact", "prompts", "write", "instructions.md", expected],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment,
    ) for _ in range(2)]
    results = [process.communicate(content, timeout=30) + (process.returncode,)
               for process, content in zip(processes, ("first", "second"), strict=True)]
    assert sorted(result[2] for result in results) == [0, 2]
    loser = next(result for result in results if result[2] == 2)
    assert json.loads(loser[0])["code"] == "conflict"
    assert prompt.read_text() in {"first", "second"}
    assert not list(source.glob(".*.interact-*"))


def test_contenders_never_remove_the_active_editor_lock(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "interact" / "prompts"
    source.mkdir(parents=True)
    prompt = source / "instructions.md"
    prompt.write_text("old")
    expected = hashlib.sha256(b"old").hexdigest()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"owner")))
    entered, release = threading.Event(), threading.Event()
    original_fsync = prompt_commands.os.fsync

    def paused_fsync(descriptor: int) -> None:
        entered.set()
        assert release.wait(10)
        original_fsync(descriptor)

    monkeypatch.setattr(prompt_commands.os, "fsync", paused_fsync)
    owner = threading.Thread(target=prompt_commands.write, args=("instructions.md", expected))
    owner.start()
    assert entered.wait(10)
    lock = source / ".instructions.md.interact.lock"
    identity = (lock.stat().st_ino, lock.read_bytes())
    try:
        contenders = [_prompt_cli(tmp_path, "write", "instructions.md", expected, stdin=value)
                      for value in ("second", "third")]
        assert all(result.returncode == 2 and json.loads(result.stdout)["code"] == "conflict"
                   for result in contenders)
        assert lock.exists() and (lock.stat().st_ino, lock.read_bytes()) == identity
    finally:
        release.set()
        owner.join(10)
    assert not owner.is_alive()
    assert prompt.read_text() == "owner"
    assert not lock.exists()


def test_visible_prompt_actions_cross_the_canonical_git_and_install_boundaries(tmp_path: Path) -> None:
    source = tmp_path / "data" / "interact" / "prompts"
    shutil.copytree(Path("tests/fixtures/prompt_source"), source)
    (source / "hooks" / "hook.sh").chmod(0o755)
    for command in (["init", "--initial-branch=main"], ["add", "."],
                    ["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial"]):
        subprocess.run(["git", "-C", str(source), *command], check=True, capture_output=True)
    environment = os.environ.copy()
    environment.update({
        "XDG_DATA_HOME": str(tmp_path / "data"), "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "INTERACT_PROMPT_CONSUMER_ROOT": str(tmp_path / "consumers"),
        "INTERACT_PROMPT_VSCODE_ROOT": str(tmp_path / "vscode"), "UV_OFFLINE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_AUTHOR_NAME": "Fixture Author", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture Author", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_ASKPASS": str(tmp_path / "must-not-run-askpass"),
        "SSH_ASKPASS": str(tmp_path / "must-not-run-ssh-askpass"),
        "BROWSER": str(tmp_path / "must-not-run-browser"),
    })
    def action(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["uv", "run", "interact", "prompts", *args], text=True,
                              capture_output=True, timeout=60, env=environment)
    assert action("status").returncode == 0
    assert action("log").returncode == 0
    (source / "instructions.md").write_text("changed\n")
    committed = action("commit", "--message", "dated prompt edit")
    assert committed.returncode == 0, committed.stderr
    assert "dated prompt edit" in action("log").stdout
    assert action("compile").returncode == 0
    assert action("install").returncode == 0
    (source / "instructions.md").write_text("dirty\n")
    before = (source / "instructions.md").read_bytes()
    for args in (("pull",), ("sync",), ("install",),
                 ("publish", "https://unavailable.invalid", str(tmp_path / "token"))):
        failed = action(*args)
        assert failed.returncode != 0, args
        assert (source / "instructions.md").read_bytes() == before
