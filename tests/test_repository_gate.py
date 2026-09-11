"""Staged-content secret scan: every finding class, the redaction, and the commit hook."""
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

REPO_ROOT = Path(__file__).parents[1]
GATE = REPO_ROOT / "scripts" / "repository_gate.py"
PRE_COMMIT = REPO_ROOT / ".githooks" / "pre-commit"


@pytest.fixture
def git_repo():
    root = REPO_ROOT / "out" / "tests" / "workflow-gates" / uuid4().hex
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "gate@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Repository Gate Test"], cwd=root, check=True)
    (root / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "add", "seed.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=root, check=True)
    yield root
    shutil.rmtree(root)


def run_gate(root: Path, *args: str):
    return subprocess.run(
        [sys.executable, str(GATE), *args],
        cwd=root,
        text=True,
        capture_output=True,
        env={"PATH": os.environ["PATH"]},
        check=False,
    )


def stage(root: Path, path: str, content: bytes):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    subprocess.run(["git", "add", "--", path], cwd=root, check=True)

@pytest.mark.parametrize(
    ("content", "finding_class"),
    [
        (b"token = 'ghp_" + b"abcdefghijklmnopqrstuvwxyz123456'\n", "credential-prefix"),
        (b"token = 'sk-" + b"a" * 40 + b"'\n", "credential-prefix"),
        (b"token = 'sk-ant-api03-" + b"a" * 80 + b"'\n", "credential-prefix"),
        (b"token = 'sk-proj-" + b"a" * 80 + b"'\n", "credential-prefix"),
        (b"Authorization: Bearer " + b"abcdefghijklmnopqrstuvwxyz123456\n", "authorization"),
        (b"password = '" + b"correct-horse-battery-staple'\n", "credential-assignment"),
        (b"-----BEGIN PRI" + b"VATE KEY-----\n", "private-key"),
        (b"endpoint=https" + b"://person:password@example.invalid/x\n", "credential-uri"),
        (b"path=/ho" + b"me/alice/private/project\n", "personal-path"),
    ],
)
def test_staged_secret_blocks_without_disclosure(git_repo: Path, content: bytes, finding_class: str):
    stage(git_repo, "candidate.txt", content)

    result = run_gate(git_repo, "scan-staged")

    combined = result.stdout + result.stderr
    assert result.returncode == 1
    assert finding_class in combined
    assert content.decode().strip() not in combined


@pytest.mark.parametrize("case", ["unstaged", "deletion"])
def test_scanner_ignores_content_outside_added_index_lines(git_repo: Path, case: str):
    path = git_repo / "candidate.txt"
    path.write_text("safe\n")
    subprocess.run(["git", "add", "candidate.txt"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "candidate"], cwd=git_repo, check=True)
    if case == "unstaged":
        path.write_text("token = 'ghp_" + "abcdefghijklmnopqrstuvwxyz123456'\n")
    else:
        path.unlink()
        subprocess.run(["git", "add", "candidate.txt"], cwd=git_repo, check=True)

    result = run_gate(git_repo, "scan-staged")

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("path", "content"),
    [
        ("clean.txt", b"ordinary documentation\n"),
        ("instructions.md", b"task-name-with-underscores-replaced-by-hyphens\n"),
        ("path with spaces.txt", b"ordinary documentation\n"),
        ("binary.bin", b"\x00ordinary-binary-content\xff"),
    ],
)
def test_scanner_accepts_clean_space_and_binary_files(git_repo: Path, path: str, content: bytes):
    stage(git_repo, path, content)

    result = run_gate(git_repo, "scan-staged")

    assert result.returncode == 0, result.stderr


def test_binary_secret_blocks_without_disclosure(git_repo: Path):
    secret = b"ghp_" + b"abcdefghijklmnopqrstuvwxyz123456"
    stage(git_repo, "candidate.bin", b"\x00prefix\xff" + secret + b"\x00suffix")

    result = run_gate(git_repo, "scan-staged")

    assert result.returncode == 1
    assert '"candidate.bin":binary: credential-prefix' in result.stderr
    assert secret.decode() not in result.stdout + result.stderr


def test_secret_shaped_filename_is_redacted_when_content_blocks(git_repo: Path):
    filename_secret = "ghp_" + "abcdefghijklmnopqrstuvwxyz123456"
    stage(git_repo, filename_secret + ".txt", b"-----BEGIN PRI" + b"VATE KEY-----\n")

    result = run_gate(git_repo, "scan-staged")

    combined = result.stdout + result.stderr
    assert result.returncode == 1
    assert '"<redacted-path>":1: private-key' in combined
    assert filename_secret not in combined


def test_configured_confidential_term_in_filename_is_redacted(git_repo: Path):
    confidential = "private-project-name"
    terms = git_repo / ".git" / "confidential-terms"
    terms.write_text(confidential + "\n")
    terms.chmod(0o600)
    subprocess.run(
        ["git", "config", "--local", "interact.confidentialTermsFile", "confidential-terms"],
        cwd=git_repo,
        check=True,
    )
    stage(git_repo, confidential + ".txt", b"-----BEGIN PRI" + b"VATE KEY-----\n")

    result = run_gate(git_repo, "scan-staged")

    combined = result.stdout + result.stderr
    assert result.returncode == 1
    assert '"<redacted-path>":1: private-key' in combined
    assert confidential not in combined


@pytest.mark.parametrize("attribute_authority", ["committed", "worktree-only"])
def test_ascii_secret_scan_ignores_binary_git_attributes(git_repo: Path, attribute_authority: str):
    attributes = git_repo / ".gitattributes"
    attributes.write_text("*.secret binary\n")
    if attribute_authority == "committed":
        subprocess.run(["git", "add", ".gitattributes"], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-qm", "attributes"], cwd=git_repo, check=True)
    secret = b"ghp_" + b"abcdefghijklmnopqrstuvwxyz123456"
    stage(git_repo, "candidate.secret", b"token = '" + secret + b"'\n")

    result = run_gate(git_repo, "scan-staged")

    assert result.returncode == 1
    assert "credential-prefix" in result.stderr
    assert secret.decode() not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "separator",
    [b"\r", b"\v", b"\f", b"\x1c", b"\x1d", b"\x1e", b"\x85"],
    ids=["cr", "vt", "ff", "fs", "gs", "rs", "nel"],
)
def test_git_lf_line_mapping_scans_splitlines_only_separators(git_repo: Path, separator: bytes):
    secret = b"ghp_" + b"abcdefghijklmnopqrstuvwxyz123456"
    stage(git_repo, "candidate.txt", b"ordinary-prefix" + separator + secret + b"\n")

    result = run_gate(git_repo, "scan-staged")

    assert result.returncode == 1
    assert '"candidate.txt":1: credential-prefix' in result.stderr
    assert secret.decode() not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("content", "line"),
    [
        (b"ordinary-prefix\r\n", 2),
        (b"ordinary-prefix", 1),
    ],
    ids=["crlf", "final-no-newline"],
)
def test_git_lf_line_mapping_preserves_normal_and_final_lines(git_repo: Path, content: bytes, line: int):
    secret = b"ghp_" + b"abcdefghijklmnopqrstuvwxyz123456"
    payload = content + secret + (b"\n" if line == 2 else b"")
    stage(git_repo, "candidate.txt", payload)

    result = run_gate(git_repo, "scan-staged")

    assert result.returncode == 1
    assert f'"candidate.txt":{line}: credential-prefix' in result.stderr
    assert secret.decode() not in result.stdout + result.stderr


def test_oversized_blob_fails_closed_without_reading_content(git_repo: Path):
    stage(git_repo, "candidate.txt", b"ordinary-content\n" * 524289)

    result = run_gate(git_repo, "scan-staged")

    assert result.returncode == 1
    assert '"candidate.txt":binary: unscannable-oversize' in result.stderr
    assert "ordinary-content" not in result.stdout + result.stderr


def test_repeated_line_diff_completes_within_linear_time_bound(git_repo: Path):
    path = git_repo / "repeated.txt"
    lines = [b"repeat\n"] * 16384
    path.write_bytes(b"".join(lines))
    subprocess.run(["git", "add", "repeated.txt"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "repeated"], cwd=git_repo, check=True)
    secret = b"ghp_" + b"abcdefghijklmnopqrstuvwxyz123456"
    lines[len(lines) // 2] = secret + b"\n"
    path.write_bytes(b"".join(lines))
    subprocess.run(["git", "add", "repeated.txt"], cwd=git_repo, check=True)

    started = time.perf_counter()
    result = subprocess.run(
        [sys.executable, str(GATE), "scan-staged"],
        cwd=git_repo,
        text=True,
        capture_output=True,
        env={"PATH": os.environ["PATH"]},
        timeout=2,
        check=False,
    )
    elapsed = time.perf_counter() - started

    assert result.returncode == 1
    assert elapsed < 2
    assert secret.decode() not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "mutation", ["unchanged", "benign", "added", "modified", "changed_hostile"]
)
def test_scanner_handles_rename_destination(git_repo: Path, mutation: str):
    secret = "token = 'ghp_" + "abcdefghijklmnopqrstuvwxyz123456'"
    seed = git_repo / "seed.txt"
    seed.write_text(secret + "\nordinary\n")
    subprocess.run(["git", "add", "seed.txt"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "credential-like baseline"], cwd=git_repo, check=True)
    subprocess.run(["git", "mv", "seed.txt", "renamed file.txt"], cwd=git_repo, check=True)
    renamed = git_repo / "renamed file.txt"
    if mutation == "benign":
        renamed.write_text(secret + "\nordinary expanded\n")
        subprocess.run(["git", "add", "renamed file.txt"], cwd=git_repo, check=True)
    elif mutation == "added":
        renamed.write_text(renamed.read_text() + secret + "\n")
        subprocess.run(["git", "add", "renamed file.txt"], cwd=git_repo, check=True)
    elif mutation == "modified":
        renamed.write_text(secret + "\n" + secret + "\n")
        subprocess.run(["git", "add", "renamed file.txt"], cwd=git_repo, check=True)
    elif mutation == "changed_hostile":
        renamed.write_text("token = 'ghp_" + "123456abcdefghijklmnopqrstuvwxyz" + "'\nordinary\n")
        subprocess.run(["git", "add", "renamed file.txt"], cwd=git_repo, check=True)

    result = run_gate(git_repo, "scan-staged")

    if mutation in {"unchanged", "benign"}:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode == 1
        assert "credential-prefix" in result.stderr
        assert secret not in result.stdout + result.stderr


def test_scanner_suppresses_only_its_detector_declarations(git_repo: Path):
    scanner = GATE.read_bytes()
    stage(git_repo, "scripts/repository_gate.py", scanner)
    stage(git_repo, "tests/test_repository_gate.py", Path(__file__).read_bytes())
    clean_result = run_gate(git_repo, "scan-staged")
    assert clean_result.returncode == 0, clean_result.stderr

    stage(
        git_repo,
        "scripts/repository_gate.py",
        scanner + b"\nLEAKED_TOKEN = 'ghp_" + b"abcdefghijklmnopqrstuvwxyz123456'\n",
    )
    result = run_gate(git_repo, "scan-staged")

    assert result.returncode == 1
    assert "ghp_" + "abcdefghijklmnopqrstuvwxyz123456" not in result.stdout + result.stderr


def test_scanner_preserves_non_utf8_filename_bytes(git_repo: Path):
    root = os.fsencode(git_repo)
    filename = b"non-utf8-\xff.txt"
    descriptor = os.open(root + b"/" + filename, os.O_WRONLY | os.O_CREAT, 0o600)
    os.write(descriptor, b"ordinary documentation\n")
    os.close(descriptor)
    subprocess.run([b"git", b"add", b"--", filename], cwd=root, check=True)

    result = run_gate(git_repo, "scan-staged")

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("mode", [0o600, 0o644])
def test_confidential_term_file_is_private_and_redacted(git_repo: Path, mode: int):
    git_dir = git_repo / ".git"
    terms = git_dir / "confidential-terms"
    confidential = b"project-codename"
    terms.write_bytes(confidential + b"\n")
    terms.chmod(mode)
    subprocess.run(
        ["git", "config", "--local", "interact.confidentialTermsFile", "confidential-terms"],
        cwd=git_repo,
        check=True,
    )
    stage(git_repo, "candidate.txt", b"reference: " + confidential + b"\n")

    result = run_gate(git_repo, "scan-staged")

    assert result.returncode == 1
    assert confidential.decode() not in result.stdout + result.stderr
    expected = "confidential-term" if mode == 0o600 else "mode 0600"
    assert expected in result.stderr


def test_confidential_term_file_rejects_same_inode_mutation(git_repo: Path):
    terms = git_repo / ".git" / "confidential-terms"
    terms.write_bytes(b"unmatched-confidential-term\n" * 200000)
    terms.chmod(0o600)
    subprocess.run(
        ["git", "config", "--local", "interact.confidentialTermsFile", "confidential-terms"],
        cwd=git_repo,
        check=True,
    )
    stage(git_repo, "candidate.txt", b"ordinary content\n")
    running = threading.Event()
    running.set()

    def mutate_metadata():
        while running.is_set():
            os.utime(terms, None)

    writer = threading.Thread(target=mutate_metadata)
    writer.start()
    try:
        result = run_gate(git_repo, "scan-staged")
    finally:
        running.clear()
        writer.join()

    assert result.returncode == 1
    assert "changed during validation" in result.stderr


def test_scanner_fails_closed_when_git_is_unavailable(git_repo: Path):
    result = subprocess.run(
        [sys.executable, str(GATE), "scan-staged"],
        cwd=git_repo,
        text=True,
        capture_output=True,
        env={"PATH": ""},
        check=False,
    )

    assert result.returncode == 1
    assert result.stderr == "[repository-gate] FAIL: Git executable unavailable\n"


def test_hook_runs_the_gate_after_generation_and_before_compile():
    hook = PRE_COMMIT.read_text()

    gate_position = hook.index("repository_gate.py")
    assert "generate-types.sh" in hook[:gate_position]
    assert "npm run compile" in hook[gate_position:]
    assert 'uv run python "$gate_exec" hook' in hook
    assert "version mismatch" in hook
    gate_source = GATE.read_text()
    assert 'subparsers.add_parser("scan-staged")' in gate_source
    assert 'subparsers.add_parser("hook")' in gate_source


def test_hook_blocks_staged_secret_with_the_indexed_scanner(git_repo: Path):
    """The hook materializes the gate from the index, so a doctored worktree copy is inert."""
    scripts = git_repo / "scripts"
    scripts.mkdir()
    scanner = scripts / GATE.name
    scanner.write_bytes(GATE.read_bytes())
    scanner.chmod(0o755)
    subprocess.run(["git", "add", "scripts/repository_gate.py"], cwd=git_repo, check=True)
    scanner.write_text("raise SystemExit(0)\n")
    stage(git_repo, "candidate.txt", b"token = 'ghp_" + b"abcdefghijklmnopqrstuvwxyz123456'\n")

    result = subprocess.run(
        ["bash", str(PRE_COMMIT)],
        cwd=git_repo,
        text=True,
        capture_output=True,
        env={"PATH": os.environ["PATH"]},
        check=False,
    )

    assert result.returncode == 1
    assert "credential-prefix" in result.stderr
