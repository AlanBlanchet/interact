import os
from pathlib import Path
import subprocess
import sys

COMMANDS = (
    "clone", "status", "diff", "commit", "log", "pull", "push", "resolve", "compile",
    "install", "publish", "sync",
)


def _environment(data_home: Path) -> dict[str, str]:
    return {
        "GIT_AUTHOR_EMAIL": "prompts@example.invalid",
        "GIT_AUTHOR_NAME": "Prompt Author",
        "GIT_COMMITTER_EMAIL": "prompts@example.invalid",
        "GIT_COMMITTER_NAME": "Prompt Author",
        "LANG": "C.UTF-8",
        "PATH": os.environ["PATH"],
        "XDG_DATA_HOME": str(data_home),
        "HOME": str(data_home / "isolated-home"),
    }


def _interact(data_home: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(Path(sys.executable).with_name("interact")), "prompts", *arguments],
        capture_output=True,
        env=_environment(data_home),
        text=True,
        timeout=20,
    )


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        env=_environment(repository.parent),
        text=True,
        timeout=20,
    )


def test_prompts_help_exposes_the_complete_local_first_workflow(tmp_path):
    result = _interact(tmp_path / "data", "--help")

    assert result.returncode == 0, result.stderr
    for command in COMMANDS:
        assert command in result.stdout


def test_prompts_clone_creates_two_independent_worktrees_from_one_local_remote(tmp_path):
    remote = tmp_path / "prompts.git"
    initialized = subprocess.run(
        ["git", "init", "--bare", str(remote)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert initialized.returncode == 0, initialized.stderr

    for client in ("client-a", "client-b"):
        data_home = tmp_path / client
        cloned = _interact(data_home, "clone", str(remote))
        worktree = data_home / "interact" / "prompts"

        assert cloned.returncode == 0, cloned.stderr
        assert (worktree / ".git").is_dir()
        origin = subprocess.run(
            ["git", "-C", str(worktree), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert origin.returncode == 0, origin.stderr
        assert Path(origin.stdout.strip()).resolve() == remote.resolve()


def test_real_git_clients_converge_and_preserve_renames_deletes_and_history(tmp_path):
    remote = tmp_path / "prompts.git"
    initialized = subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(remote)],
        capture_output=True, text=True, timeout=20,
    )
    assert initialized.returncode == 0, initialized.stderr
    homes = [tmp_path / name for name in ("a", "b", "c")]
    assert _interact(homes[0], "clone", str(remote)).returncode == 0
    worktree_a = homes[0] / "interact" / "prompts"
    (worktree_a / "agents").mkdir()
    (worktree_a / "agents" / "librarian.md").write_text("first\n")
    (worktree_a / "agents" / "obsolete.md").write_text("remove me\n")
    committed = _interact(homes[0], "commit", "-m", "initial prompt")
    assert committed.returncode == 0, committed.stderr
    pushed = _interact(homes[0], "push")
    assert pushed.returncode == 0, pushed.stderr

    assert _interact(homes[1], "clone", str(remote)).returncode == 0
    worktree_b = homes[1] / "interact" / "prompts"
    (worktree_a / "agents" / "author.md").write_text("from a\n")
    assert _interact(homes[0], "commit", "-m", "independent a").returncode == 0
    assert _interact(homes[0], "push").returncode == 0
    (worktree_b / "agents" / "librarian.md").rename(worktree_b / "agents" / "prompt-librarian.md")
    (worktree_b / "agents" / "obsolete.md").unlink()
    (worktree_b / "agents" / "tester.md").write_text("test\n")
    assert _interact(homes[1], "commit", "-m", "rename and add").returncode == 0
    assert _interact(homes[1], "pull").returncode == 0
    assert _interact(homes[1], "push").returncode == 0

    (worktree_a / "agents" / "librarian.md").unlink()
    pulled = _interact(homes[0], "pull")
    assert pulled.returncode != 0
    assert (worktree_a / "agents" / "librarian.md").exists() is False
    assert (worktree_a / "agents" / "prompt-librarian.md").exists() is False
    _git(worktree_a, "restore", "agents/librarian.md")
    assert _interact(homes[0], "pull").returncode == 0

    assert _interact(homes[2], "clone", str(remote)).returncode == 0
    worktree_c = homes[2] / "interact" / "prompts"
    assert (worktree_c / "agents" / "prompt-librarian.md").read_bytes() == b"first\n"
    assert (worktree_c / "agents" / "tester.md").read_bytes() == b"test\n"
    assert (worktree_c / "agents" / "author.md").read_bytes() == b"from a\n"
    assert (worktree_c / "agents" / "obsolete.md").exists() is False
    assert _git(worktree_c, "rev-list", "--all").stdout == _git(worktree_a, "rev-list", "--all").stdout
    history = _interact(homes[2], "log")
    assert history.returncode == 0, history.stderr
    assert "initial prompt" in history.stdout and "rename and add" in history.stdout


def test_divergent_clients_surface_conflict_and_stage_only_explicit_resolution(tmp_path):
    remote = tmp_path / "prompts.git"
    assert subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(remote)],
        capture_output=True, text=True, timeout=20,
    ).returncode == 0
    home_a, home_b = tmp_path / "a", tmp_path / "b"
    assert _interact(home_a, "clone", str(remote)).returncode == 0
    worktree_a = home_a / "interact" / "prompts"
    (worktree_a / "shared.md").write_text("base\n")
    assert _interact(home_a, "commit", "-m", "base").returncode == 0
    assert _interact(home_a, "push").returncode == 0
    assert _interact(home_b, "clone", str(remote)).returncode == 0
    worktree_b = home_b / "interact" / "prompts"

    (worktree_a / "shared.md").write_text("from a\n")
    assert _interact(home_a, "commit", "-m", "a edit").returncode == 0
    assert _interact(home_a, "push").returncode == 0
    (worktree_b / "shared.md").write_text("from b\n")
    assert _interact(home_b, "commit", "-m", "b edit").returncode == 0
    conflicted = _interact(home_b, "pull")

    assert conflicted.returncode != 0
    assert "<<<<<<<" in (worktree_b / "shared.md").read_text()
    rejected = _interact(home_b, "resolve", "not-conflicted.md")
    assert rejected.returncode != 0
    (worktree_b / "shared.md").write_text("from a\nfrom b\n")
    resolved = _interact(home_b, "resolve", "shared.md")
    assert resolved.returncode == 0, resolved.stderr
    assert _git(worktree_b, "diff", "--name-only", "--diff-filter=U").stdout == ""


def test_remote_outage_preserves_local_commit_and_working_file(tmp_path):
    remote = tmp_path / "prompts.git"
    assert subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(remote)],
        capture_output=True, text=True, timeout=20,
    ).returncode == 0
    home = tmp_path / "client"
    assert _interact(home, "clone", str(remote)).returncode == 0
    worktree = home / "interact" / "prompts"
    authored = worktree / "offline.md"
    authored.write_text("available offline\n")
    assert _interact(home, "commit", "-m", "offline source").returncode == 0
    assert _interact(home, "push").returncode == 0
    head = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    remote.rename(tmp_path / "remote-unavailable")

    failed = _interact(home, "sync")

    assert failed.returncode != 0
    assert authored.read_text() == "available offline\n"
    assert _git(worktree, "rev-parse", "HEAD").stdout.strip() == head
    assert _interact(home, "status").returncode == 0
    assert _interact(home, "log").returncode == 0
