"""Local-first prompt authoring commands backed by Git."""

import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
from typing import Annotated

from cyclopts import App, Parameter

from interact.prompt_projection import compile_prompt_projection, install_prompt_projection
from interact.prompt_publisher import publish_projection
from interact.prompt_secret import read_prompt_token

prompts_app = App(name="prompts", help="Author and synchronize prompts through local Git.")


def _data_home() -> Path:
    configured = os.environ.get("XDG_DATA_HOME")
    return Path(configured) if configured else Path.home() / ".local" / "share"


def _repository() -> Path:
    return _data_home() / "interact" / "prompts"


def _cache_home() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME")
    return Path(configured) if configured else Path.home() / ".cache"


def _state_home() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    return Path(configured) if configured else Path.home() / ".local" / "state"


def _projection(repository: Path) -> Path:
    commit_id = _run("rev-parse", "HEAD", repository=repository, output=False).stdout.strip()
    return _cache_home() / "interact" / "prompts" / commit_id


def _compile(repository: Path) -> Path:
    _require_clean(repository)
    projection = _projection(repository)
    if not projection.exists():
        compile_prompt_projection(repository, "HEAD", projection, Path.home())
    return projection


def _install(repository: Path) -> Path:
    projection = _compile(repository)
    vscode_root = Path(os.environ.get(
        "INTERACT_PROMPT_VSCODE_ROOT", Path.home() / ".config" / "Code" / "User" / "prompts"
    ))
    state = _state_home() / "interact" / "prompts" / "installed.json"
    adoption = state.parent / "bootstrap-adoption.json"
    install_prompt_projection(projection, Path.home(), vscode_root, state, adoption)
    return projection


def _run(
    *arguments: str,
    repository: Path | None = None,
    output: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = ["git"]
    if repository is not None:
        command.extend(("-C", str(repository)))
    command.extend(arguments)
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if output and result.stdout:
        print(result.stdout, end="")
    if result.returncode:
        message = result.stderr.strip() or f"git exited {result.returncode}"
        print(f"ERROR: {message}", file=sys.stderr)
        raise SystemExit(result.returncode)
    return result


def _require_clean(repository: Path) -> None:
    status = _run(
        "status", "--porcelain=v1", "-z", repository=repository, output=False
    ).stdout
    if status:
        print("ERROR: prompt worktree has uncommitted changes or conflicts", file=sys.stderr)
        raise SystemExit(2)


@prompts_app.command
def clone(remote: str) -> None:
    """Clone REMOTE into the local prompt authoring worktree."""
    repository = _repository()
    if repository.exists():
        print(f"ERROR: prompt worktree already exists: {repository}", file=sys.stderr)
        raise SystemExit(2)
    repository.parent.mkdir(parents=True, exist_ok=True)
    _run("clone", "--", remote, str(repository))


@prompts_app.command
def status() -> None:
    """Show the exact Git state of the local prompt worktree."""
    _run("status", "--short", "--branch", repository=_repository())


@prompts_app.command
def diff() -> None:
    """Show staged and unstaged prompt changes."""
    _run("diff", "--no-ext-diff", "HEAD", "--", repository=_repository())


@prompts_app.command
def commit(message: Annotated[str, Parameter(name=["--message", "-m"])]) -> None:
    """Commit all authored prompt changes with MESSAGE."""
    repository = _repository()
    conflicts = _run("diff", "--name-only", "--diff-filter=U", repository=repository).stdout
    if conflicts:
        print("ERROR: resolve every conflict before committing", file=sys.stderr)
        raise SystemExit(2)
    _run("add", "-A", "--", ".", repository=repository)
    _run("commit", "-m", message, repository=repository)


@prompts_app.command
def log() -> None:
    """Show immutable prompt revisions with author dates and ancestry."""
    _run(
        "log", "--date=iso-strict", "--decorate", "--graph",
        "--pretty=format:%H%x09%aI%x09%P%x09%s", repository=_repository(),
    )


@prompts_app.command
def pull() -> None:
    """Merge from the configured remote without discarding local work."""
    repository = _repository()
    _require_clean(repository)
    _run("pull", "--no-rebase", "--no-edit", repository=repository)


@prompts_app.command
def push() -> None:
    """Push local prompt commits using ordinary Git conflict protection."""
    repository = _repository()
    upstream = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "--abbrev-ref", "@{upstream}"],
        capture_output=True, text=True, timeout=30,
    )
    if upstream.returncode:
        _run("push", "--set-upstream", "origin", "HEAD", repository=repository)
        return
    _run("push", repository=repository)


@prompts_app.command
def resolve(*paths: str) -> None:
    """Stage only named conflicted prompt source PATHS after manual resolution."""
    repository = _repository()
    if not paths:
        print("ERROR: name at least one conflicted source path", file=sys.stderr)
        raise SystemExit(2)
    conflicted = set(
        _run(
            "diff", "--name-only", "--diff-filter=U", "-z",
            repository=repository, output=False,
        )
        .stdout.rstrip("\0").split("\0")
    )
    for value in paths:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value not in conflicted:
            print(f"ERROR: not an allowlisted conflicted source path: {value}", file=sys.stderr)
            raise SystemExit(2)
        if (repository / path).is_symlink():
            print(f"ERROR: conflicted source must not be a symlink: {value}", file=sys.stderr)
            raise SystemExit(2)
    _run("add", "--", *paths, repository=repository)


@prompts_app.command
def compile() -> None:
    """Compile the clean exact HEAD into the local projection cache."""
    print(_compile(_repository()))


@prompts_app.command
def install() -> None:
    """Atomically install the exact compiled projection into managed consumers."""
    print(_install(_repository()))


@prompts_app.command
def publish(endpoint: str, token_file: Path) -> None:
    """Publish the clean, pushed exact HEAD to an authenticated prompt service."""
    repository = _repository()
    _require_clean(repository)
    head = _run("rev-parse", "HEAD", repository=repository, output=False).stdout.strip()
    upstream = _run(
        "rev-parse", "@{upstream}", repository=repository, output=False
    ).stdout.strip()
    if head != upstream:
        print("ERROR: prompt HEAD is not exactly pushed to its upstream", file=sys.stderr)
        raise SystemExit(2)
    token = read_prompt_token(token_file)
    publish_projection(_compile(repository), endpoint, token)
    print(head)


@prompts_app.command
def sync() -> None:
    """Pull, compile, and install locally without external publication."""
    repository = _repository()
    _require_clean(repository)
    _run("pull", "--no-rebase", "--no-edit", repository=repository)
    print(_install(repository))
