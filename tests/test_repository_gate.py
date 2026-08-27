import hashlib
import importlib.util
import json
import os
import re
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
ITERATION_ID = "20260827-workflow-gates-test"
HASH = "a" * 64
LEGACY_SUPERSEDED = '{"iteration_id":"20260827-workflow-gates","state":"SUPERSEDED","evidence":{"closed_commit":"723624d4a2a24a4c340d6667f06518fd983ca3c0","reason":"post-commit validation incorrectly compared the clean index with the historical candidate staged-diff hash"}}'


def load_gate_module():
    spec = importlib.util.spec_from_file_location("repository_gate_test_module", GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def test_scanner_handles_rename_destination(git_repo: Path):
    subprocess.run(["git", "mv", "seed.txt", "renamed file.txt"], cwd=git_repo, check=True)

    result = run_gate(git_repo, "scan-staged")

    assert result.returncode == 0, result.stderr


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


def event(state: str, evidence: dict[str, object]):
    return {"iteration_id": ITERATION_ID, "state": state, "evidence": evidence}


def write_ledger(root: Path, events: list[dict[str, object]]):
    directory = root / ".github" / "memory" / "iterations"
    directory.mkdir(parents=True, exist_ok=True)
    body = [f"# Iteration {ITERATION_ID}\n"]
    for item in events:
        body.append("```workflow-event\n" + json.dumps(item, sort_keys=True) + "\n```\n")
    ledger = directory / f"{ITERATION_ID}.md"
    ledger.write_text("\n".join(body))
    return ledger


def baseline_event():
    return event(
        "BASELINED",
        {
            "request": "verify workflow",
            "acceptance": ["gate enforced"],
            "branch": "main",
            "head": "0" * 40,
            "status": "",
            "unstaged_diff_sha256": HASH,
            "staged_diff_sha256": HASH,
            "untracked_checksums": {},
            "protected_paths": [],
            "overlap": "none",
        },
    )


def designed_event():
    return event(
        "DESIGNED",
        {
            "interpretation": "standalone repository gate",
            "non_goals": ["product source"],
            "owners": ["scripts/repository_gate.py"],
            "interfaces": ["scan-staged"],
            "invariants": ["redacted output"],
            "edge_cases": ["binary staged blob"],
            "trust_boundaries": ["Git output"],
            "tests": ["real Git integration"],
            "negative_controls": ["secret staged"],
            "cost": "local only",
            "visual_route": "not applicable",
            "compatibility": "clean cutover",
        },
    )


def red_event():
    return event(
        "RED",
        {
            "argv": ["pytest", "tests/test_repository_gate.py"],
            "cwd": ".",
            "environment": {"PATH": "redacted"},
            "includes": ["tests/test_repository_gate.py"],
            "excludes": [],
            "exit_code": 1,
            "failing_assertion": "gate command unavailable",
            "summary": "1 failed",
        },
    )


def implemented_event():
    return event("IMPLEMENTED", {"owned_paths": ["scripts/repository_gate.py"], "summary": "gate implemented"})


def candidate_event(root: Path):
    tree = subprocess.run(["git", "write-tree"], cwd=root, text=True, capture_output=True, check=True).stdout.strip()
    staged_diff = subprocess.run(
        ["git", "diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    acceptance_sha256 = hashlib.sha256(
        json.dumps(baseline_event()["evidence"]["acceptance"], separators=(",", ":")).encode()
    ).hexdigest()
    return event(
        "CANDIDATE_FROZEN",
        {
            "tree": tree,
            "staged_diff_sha256": hashlib.sha256(staged_diff).hexdigest(),
            "owned_paths": ["scripts/repository_gate.py"],
            "acceptance_sha256": acceptance_sha256,
        },
    )


def review_event(candidate: dict[str, object]):
    evidence = candidate["evidence"]
    assert isinstance(evidence, dict)
    return event(
        "REVIEWED",
        {
            "candidate_tree": evidence["tree"],
            "acceptance_sha256": evidence["acceptance_sha256"],
            "reviewers": [
                {
                    "schema_version": 1,
                    "reviewer": "reviewer",
                    "task": "functional_diff_review",
                    "candidate_tree": evidence["tree"],
                    "acceptance_sha256": evidence["acceptance_sha256"],
                    "inspected_paths": ["scripts/repository_gate.py"],
                    "findings": [],
                    "disposition": "approved",
                    "commands": [
                        {
                            "argv": ["pytest", "tests/test_repository_gate.py"],
                            "cwd": ".",
                            "environment": {"PATH": "redacted"},
                            "includes": ["tests/test_repository_gate.py"],
                            "excludes": [],
                            "exit_code": 0,
                            "summary": "passed",
                        }
                    ],
                }
            ],
        },
    )


def verified_event(candidate: dict[str, object]):
    evidence = candidate["evidence"]
    assert isinstance(evidence, dict)
    return event(
        "VERIFIED",
        {
            "candidate_tree": evidence["tree"],
            "acceptance_sha256": evidence["acceptance_sha256"],
            "commands": [
                {
                    "argv": ["pytest", "tests/test_repository_gate.py"],
                    "cwd": ".",
                    "environment": {"PATH": "redacted"},
                    "includes": ["tests/test_repository_gate.py"],
                    "excludes": [],
                    "exit_code": 0,
                    "summary": "20 passed",
                }
            ],
        },
    )


def valid_events(root: Path, terminal: str):
    events = [baseline_event()]
    if terminal == "BASELINED":
        return events
    events.append(designed_event())
    if terminal == "DESIGNED":
        return events
    events.append(red_event())
    if terminal == "RED":
        return events
    events.append(implemented_event())
    if terminal == "IMPLEMENTED":
        return events
    candidate = candidate_event(root)
    events.append(candidate)
    if terminal == "CANDIDATE_FROZEN":
        return events
    events.append(review_event(candidate))
    if terminal == "REVIEWED":
        return events
    events.append(verified_event(candidate))
    if terminal == "VERIFIED":
        return events
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True).stdout.strip()
    tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=root, text=True, capture_output=True, check=True).stdout.strip()
    events.append(event("COMMITTED", {"commit": head, "tree": tree, "candidate_tree": tree}))
    if terminal == "COMMITTED":
        return events
    for name in ("pm", "developer", "reviewer"):
        memory = root / ".github" / "memory" / f"{name}.md"
        memory.parent.mkdir(parents=True, exist_ok=True)
        memory.write_text(f"# memory\n\n- {ITERATION_ID}\n")
    events.append(
        event(
            "CLOSED",
            {
                "acceptance": {"gate enforced": "satisfied"},
                "blockers": [],
                "processes": [],
                "participants": ["pm", "developer", "reviewer"],
                "memory_markers": ["pm", "developer", "reviewer"],
            },
        )
    )
    return events


def close_recovery_epoch(
    root: Path,
    events: list[dict[str, object]],
    filename: str,
    participants: list[str],
):
    stage(root, filename, filename.encode() + b"\n")
    candidate = candidate_event(root)
    events.extend([candidate, review_event(candidate), verified_event(candidate)])
    return close_verified_epoch(root, events, filename, participants)


def close_verified_epoch(
    root: Path,
    events: list[dict[str, object]],
    message: str,
    participants: list[str],
):
    subprocess.run(["git", "commit", "-qm", message], cwd=root, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=root, text=True, capture_output=True, check=True
    ).stdout.strip()
    events.append(event("COMMITTED", {"commit": commit, "tree": tree, "candidate_tree": tree}))
    reviewer_names = {
        reviewer["reviewer"]
        for item in events
        if item["state"] == "REVIEWED"
        for reviewer in item["evidence"]["reviewers"]
    }
    effective_participants = sorted(set(participants) | reviewer_names)
    for participant in effective_participants:
        memory = root / ".github" / "memory" / f"{participant.replace('_', '-')}.md"
        memory.parent.mkdir(parents=True, exist_ok=True)
        memory.write_text(f"# memory\n\n- {ITERATION_ID}\n")
    events.append(
        event(
            "CLOSED",
            {
                "acceptance": {"gate enforced": "satisfied"},
                "blockers": [],
                "processes": [],
                "participants": list(effective_participants),
                "memory_markers": list(effective_participants),
            },
        )
    )
    return commit, tree


def supersede_closed_epoch(events: list[dict[str, object]], commit: str):
    events.extend(
        [
            event(
                "SUPERSEDED",
                {
                    "schema_version": 1,
                    "closed_commit": commit,
                    "contradicted_claim": "verification_evidence",
                    "recovery": "RED",
                },
            ),
            red_event(),
            implemented_event(),
        ]
    )


@pytest.mark.parametrize(
    "terminal",
    ["BASELINED", "DESIGNED", "RED", "IMPLEMENTED", "CANDIDATE_FROZEN", "REVIEWED", "VERIFIED", "COMMITTED", "CLOSED"],
)
def test_valid_minimal_ledger_at_each_state(git_repo: Path, terminal: str):
    ledger = write_ledger(git_repo, valid_events(git_repo, terminal))

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing-baseline", "baseline"),
        ("out-of-order", "order"),
        ("review-tree", "candidate"),
        ("verification-tree", "candidate"),
        ("missing-excludes", "excludes"),
        ("commit-tree", "tree"),
        ("memory-marker", "memory"),
    ],
)
def test_invalid_ledger_evidence_fails_closed(git_repo: Path, mutation: str, message: str):
    terminal = "CLOSED" if mutation in {"commit-tree", "memory-marker"} else "VERIFIED"
    events = valid_events(git_repo, terminal)
    if mutation == "missing-baseline":
        del events[0]["evidence"]["status"]
    elif mutation == "out-of-order":
        events[1], events[2] = events[2], events[1]
    elif mutation == "review-tree":
        events[4]["evidence"]["tree"] = "b" * 40
    elif mutation == "verification-tree":
        events[6]["evidence"]["candidate_tree"] = "b" * 40
    elif mutation == "missing-excludes":
        del events[6]["evidence"]["commands"][0]["excludes"]
    elif mutation == "commit-tree":
        events[7]["evidence"]["tree"] = "b" * 40
    else:
        (git_repo / ".github" / "memory" / "developer.md").write_text("# memory\n")
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert message in result.stderr.lower()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("red-zero", "exit_code"),
        ("red-empty-includes", "includes"),
        ("empty-reviewers", "reviewers"),
        ("empty-inspected-paths", "inspected_paths"),
        ("empty-review-commands", "commands"),
        ("review-command-failed", "exit_code"),
        ("review-candidate", "candidate"),
        ("missing-disposition", "disposition"),
        ("empty-verification", "commands"),
        ("verification-failed", "exit_code"),
        ("acceptance-mismatch", "acceptance"),
    ],
)
def test_ledger_requires_complete_success_evidence(git_repo: Path, mutation: str, message: str):
    terminal = "CLOSED" if mutation == "acceptance-mismatch" else "VERIFIED"
    events = valid_events(git_repo, terminal)
    if mutation == "red-zero":
        events[2]["evidence"]["exit_code"] = 0
    elif mutation == "red-empty-includes":
        events[2]["evidence"]["includes"] = []
    elif mutation == "empty-reviewers":
        events[5]["evidence"]["reviewers"] = []
    elif mutation == "empty-inspected-paths":
        events[5]["evidence"]["reviewers"][0]["inspected_paths"] = []
    elif mutation == "empty-review-commands":
        events[5]["evidence"]["reviewers"][0]["commands"] = []
    elif mutation == "review-command-failed":
        events[5]["evidence"]["reviewers"][0]["commands"][0]["exit_code"] = 1
    elif mutation == "review-candidate":
        events[5]["evidence"]["reviewers"][0]["candidate_tree"] = "b" * 40
    elif mutation == "missing-disposition":
        del events[5]["evidence"]["reviewers"][0]["disposition"]
    elif mutation == "empty-verification":
        events[6]["evidence"]["commands"] = []
    elif mutation == "verification-failed":
        events[6]["evidence"]["commands"][0]["exit_code"] = 1
    else:
        events[8]["evidence"]["acceptance"] = {"different item": "satisfied"}
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert message in result.stderr.lower()


@pytest.mark.parametrize(
    "suffix",
    [
        "arbitrary prose",
        "<!-- comment -->",
        "\x01control-content",
        "```workflow-event\n{}\n```",
    ],
    ids=["prose", "comment", "control", "another-fence"],
)
def test_closed_event_allows_only_trailing_whitespace(git_repo: Path, suffix: str):
    ledger = write_ledger(git_repo, valid_events(git_repo, "CLOSED"))
    ledger.write_text(ledger.read_text() + suffix)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert suffix not in result.stdout + result.stderr
    assert "closed" in result.stderr.lower()


def test_closed_event_accepts_trailing_whitespace(git_repo: Path):
    ledger = write_ledger(git_repo, valid_events(git_repo, "CLOSED"))
    ledger.write_text(ledger.read_text() + "\n\t \r\n")

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 0, result.stderr


def test_committed_event_must_match_current_head(git_repo: Path):
    events = valid_events(git_repo, "COMMITTED")
    candidate_tree = events[4]["evidence"]["tree"]
    stage(git_repo, "advanced.txt", b"advanced head\n")
    subprocess.run(["git", "commit", "-qm", "advance"], cwd=git_repo, check=True)
    subprocess.run(["git", "read-tree", candidate_tree], cwd=git_repo, check=True)
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert "current head" in result.stderr.lower()


@pytest.mark.parametrize("terminal", ["COMMITTED", "CLOSED"])
def test_post_commit_clean_index_uses_head_binding_not_candidate_diff_hash(
    git_repo: Path, terminal: str
):
    stage(git_repo, "candidate.txt", b"candidate content\n")
    events = valid_events(git_repo, "VERIFIED")
    subprocess.run(["git", "commit", "-qm", "candidate"], cwd=git_repo, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=git_repo, text=True, capture_output=True, check=True
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=git_repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    events.append(event("COMMITTED", {"commit": commit, "tree": tree, "candidate_tree": tree}))
    if terminal == "CLOSED":
        for name in ("pm", "developer", "reviewer"):
            memory = git_repo / ".github" / "memory" / f"{name}.md"
            memory.parent.mkdir(parents=True, exist_ok=True)
            memory.write_text(f"# memory\n\n- {ITERATION_ID}\n")
        events.append(
            event(
                "CLOSED",
                {
                    "acceptance": {"gate enforced": "satisfied"},
                    "blockers": [],
                    "processes": [],
                    "participants": ["pm", "developer", "reviewer"],
                    "memory_markers": ["pm", "developer", "reviewer"],
                },
            )
        )
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 0, result.stderr


def test_committed_state_rejects_dirty_staged_index(git_repo: Path):
    events = valid_events(git_repo, "COMMITTED")
    stage(git_repo, "unexpected.txt", b"unexpected staged change\n")
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert "index must be clean" in result.stderr.lower()


def test_two_recovery_epochs_bind_only_latest_commit_to_head(git_repo: Path):
    stage(git_repo, "epoch-a.txt", b"epoch a\n")
    events = valid_events(git_repo, "VERIFIED")
    commit_a, _ = close_verified_epoch(
        git_repo, events, "epoch a", ["pm", "developer", "reviewer_a"]
    )
    supersede_closed_epoch(events, commit_a)
    commit_b, _ = close_recovery_epoch(
        git_repo, events, "epoch-b.txt", ["pm", "developer", "reviewer_a", "reviewer_b"]
    )
    supersede_closed_epoch(events, commit_b)
    close_recovery_epoch(
        git_repo,
        events,
        "epoch-c.txt",
        ["pm", "developer", "reviewer_a", "reviewer_b", "reviewer_c"],
    )
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("tamper", ["commit", "tree"])
def test_superseded_historical_commit_remains_cryptographically_bound(
    git_repo: Path, tamper: str
):
    stage(git_repo, "epoch-a.txt", b"epoch a\n")
    events = valid_events(git_repo, "VERIFIED")
    commit_a, _ = close_verified_epoch(git_repo, events, "epoch a", ["pm", "developer"])
    supersede_closed_epoch(events, commit_a)
    commit_b, tree_b = close_recovery_epoch(
        git_repo, events, "epoch-b.txt", ["pm", "developer"]
    )
    historical = events[7]["evidence"]
    historical[tamper] = commit_b if tamper == "commit" else tree_b
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert "commit" in result.stderr.lower()


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("wrong_commit", "closed commit"),
        ("missing_evidence", "state order"),
        ("designed_without_review", "state order"),
    ],
)
def test_supersession_control_shapes_fail_closed(
    git_repo: Path, mutation: str, expected: str
):
    events = valid_events(git_repo, "CLOSED")
    commit = events[7]["evidence"]["commit"]
    control = event(
        "SUPERSEDED",
        {"schema_version": 1, "closed_commit": commit, "contradicted_claim": "acceptance_reconciliation", "recovery": "RED"},
    )
    events.append(control)
    if mutation == "wrong_commit":
        control["evidence"]["closed_commit"] = "0" * 40
        events.append(red_event())
    elif mutation == "missing_evidence":
        events.append(implemented_event())
    else:
        events.append(designed_event())
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert expected in result.stderr.lower()


def test_recovery_to_designed_requires_typed_review_finding(git_repo: Path):
    events = valid_events(git_repo, "CLOSED")
    committed = events[7]["evidence"]
    prior_review = json.loads(json.dumps(events[5]["evidence"]["reviewers"][0]))
    prior_review["disposition"] = "changes_requested"
    prior_review["findings"] = [
        {
            "claim": "acceptance_reconciliation",
            "detail": "interface acceptance was contradicted",
        }
    ]
    events.extend(
        [
            event(
                "SUPERSEDED",
                {
                    "schema_version": 1,
                    "closed_commit": committed["commit"],
                    "contradicted_claim": "acceptance_reconciliation",
                    "recovery": "DESIGNED",
                    "review": prior_review,
                },
            ),
            designed_event(),
            red_event(),
            implemented_event(),
        ]
    )
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 0, result.stderr


def test_closed_memory_markers_reconcile_participants_across_recovery_epochs(git_repo: Path):
    stage(git_repo, "epoch-a.txt", b"epoch a\n")
    events = valid_events(git_repo, "VERIFIED")
    commit, _ = close_verified_epoch(
        git_repo, events, "epoch a", ["pm", "developer", "reviewer_a"]
    )
    supersede_closed_epoch(events, commit)
    close_recovery_epoch(git_repo, events, "epoch-b.txt", ["pm", "developer"])
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert "memory marker" in result.stderr.lower()


def test_committed_clean_index_ignores_hostile_textconv(git_repo: Path):
    script = git_repo / "constant-textconv.sh"
    script.write_text("#!/bin/sh\nprintf 'unchanged\\n'\n")
    script.chmod(0o755)
    stage(git_repo, ".gitattributes", b"*.masked diff=hide\n")
    stage(git_repo, "tracked.masked", b"before\n")
    subprocess.run(["git", "add", "constant-textconv.sh"], cwd=git_repo, check=True)
    subprocess.run(["git", "config", "diff.hide.textconv", "./constant-textconv.sh"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "textconv fixture"], cwd=git_repo, check=True)
    events = valid_events(git_repo, "COMMITTED")
    stage(git_repo, "tracked.masked", b"after\n")
    visible = subprocess.run(
        ["git", "diff", "--cached", "--binary"], cwd=git_repo, capture_output=True, check=True
    )
    assert visible.stdout == b""
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert "index" in result.stderr.lower()


@pytest.mark.parametrize("terminal", ["COMMITTED", "CLOSED"])
def test_terminal_verification_never_executes_mutating_textconv(
    git_repo: Path, terminal: str
):
    script = git_repo / "mutating-textconv.sh"
    script.write_text("#!/bin/sh\ngit reset -q HEAD\nprintf 'unchanged\\n'\n")
    script.chmod(0o755)
    stage(git_repo, ".gitattributes", b"*.masked diff=mutating\n")
    stage(git_repo, "tracked.masked", b"before\n")
    subprocess.run(["git", "add", "mutating-textconv.sh"], cwd=git_repo, check=True)
    subprocess.run(["git", "config", "diff.mutating.textconv", "./mutating-textconv.sh"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "mutating textconv fixture"], cwd=git_repo, check=True)
    events = valid_events(git_repo, terminal)
    stage(git_repo, "tracked.masked", b"after\n")
    dirty_tree = subprocess.run(
        ["git", "write-tree"], cwd=git_repo, text=True, capture_output=True, check=True
    ).stdout.strip()
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))
    remaining_tree = subprocess.run(
        ["git", "write-tree"], cwd=git_repo, text=True, capture_output=True, check=True
    ).stdout.strip()

    assert result.returncode == 1
    assert remaining_tree == dirty_tree


def test_precommit_candidate_diff_disables_mutating_textconv(git_repo: Path):
    script = git_repo / "conditional-textconv.sh"
    script.write_text(
        "#!/bin/sh\nif test -e mutate-index; then git reset -q HEAD; fi\nprintf 'unchanged\\n'\n"
    )
    script.chmod(0o755)
    stage(git_repo, ".gitattributes", b"*.masked diff=conditional\n")
    stage(git_repo, "tracked.masked", b"before\n")
    subprocess.run(["git", "add", "conditional-textconv.sh"], cwd=git_repo, check=True)
    subprocess.run(["git", "config", "diff.conditional.textconv", "./conditional-textconv.sh"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "conditional textconv fixture"], cwd=git_repo, check=True)
    stage(git_repo, "tracked.masked", b"after\n")
    events = valid_events(git_repo, "CANDIDATE_FROZEN")
    expected_tree = events[-1]["evidence"]["tree"]
    (git_repo / "mutate-index").write_text("armed\n")
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))
    remaining_tree = subprocess.run(
        ["git", "write-tree"], cwd=git_repo, text=True, capture_output=True, check=True
    ).stdout.strip()

    assert result.returncode == 0, result.stderr
    assert remaining_tree == expected_tree


def test_historical_commit_rejects_symbolic_revision_instead_of_full_object_id(git_repo: Path):
    stage(git_repo, "epoch-a.txt", b"epoch a\n")
    events = valid_events(git_repo, "VERIFIED")
    commit_a, _ = close_verified_epoch(git_repo, events, "epoch a", ["pm", "developer"])
    supersede_closed_epoch(events, commit_a)
    close_recovery_epoch(git_repo, events, "epoch-b.txt", ["pm", "developer"])
    events[7]["evidence"]["commit"] = "HEAD~1"
    events[9]["evidence"]["closed_commit"] = "HEAD~1"
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert "commit" in result.stderr.lower()


@pytest.mark.parametrize(
    ("target", "field"),
    [("red", "failing_assertion"), ("red", "summary"), ("review", "summary"), ("review", "findings")],
)
def test_audit_narratives_must_be_nonempty(
    git_repo: Path, target: str, field: str
):
    events = valid_events(git_repo, "REVIEWED")
    if target == "red":
        events[2]["evidence"][field] = "   "
    elif field == "findings":
        events[5]["evidence"]["reviewers"][0][field] = ["   "]
    else:
        events[5]["evidence"]["reviewers"][0]["commands"][0][field] = "   "
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1


@pytest.mark.parametrize(
    ("event_index", "field", "list_entry"),
    [
        (0, "request", False),
        (0, "acceptance", True),
        (1, "interpretation", False),
        (1, "non_goals", True),
        (1, "owners", True),
        (1, "interfaces", True),
        (1, "invariants", True),
        (1, "edge_cases", True),
        (1, "trust_boundaries", True),
        (1, "tests", True),
        (1, "negative_controls", True),
        (1, "cost", False),
        (1, "visual_route", False),
        (1, "compatibility", False),
        (3, "summary", False),
        (5, "task", False),
    ],
)
def test_required_schema_narratives_reject_whitespace(
    git_repo: Path, event_index: int, field: str, list_entry: bool
):
    events = valid_events(git_repo, "REVIEWED")
    evidence = events[event_index]["evidence"]
    if event_index == 5:
        evidence = evidence["reviewers"][0]
    evidence[field] = ["   "] if list_entry else "   "
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1


@pytest.mark.parametrize(
    ("field", "claim", "expected_returncode"),
    [
        ("contradicted_claim", "gate enforced", 0),
        ("contradicted_claim", "commit_binding", 0),
        ("contradicted_claim", "x", 1),
        ("reason", "commit binding was wrong", 1),
    ],
)
def test_superseded_claim_schema_cutover(
    git_repo: Path, field: str, claim: str, expected_returncode: int
):
    events = valid_events(git_repo, "CLOSED")
    commit = events[7]["evidence"]["commit"]
    events.extend(
        [
            event(
                "SUPERSEDED",
                {"schema_version": 1, "closed_commit": commit, field: claim, "recovery": "RED"},
            ),
            red_event(),
        ]
    )
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == expected_returncode, result.stderr


@pytest.mark.parametrize(
    ("mutation", "accepted"),
    [
        ("exact", True),
        ("whitespace", False),
        ("key_order", False),
        ("ordinal", False),
        ("iteration", False),
        ("commit", False),
        ("second_legacy", False),
    ],
)
def test_immutable_v0_superseded_migration_tuple(
    git_repo: Path, mutation: str, accepted: bool
):
    module = load_gate_module()
    iteration_id = "20260827-workflow-gates"
    items = []
    for _ in range(28):
        item = baseline_event()
        item["iteration_id"] = iteration_id
        items.append(json.dumps(item, separators=(",", ":")))
    items.append(
        json.dumps(
            event(
                "COMMITTED",
                {
                    "commit": "723624d4a2a24a4c340d6667f06518fd983ca3c0",
                    "tree": "a" * 40,
                    "candidate_tree": "a" * 40,
                },
            ),
            separators=(",", ":"),
        ).replace(ITERATION_ID, iteration_id)
    )
    closed = event(
        "CLOSED",
        {
            "acceptance": {"gate enforced": "satisfied"},
            "blockers": [],
            "processes": [],
            "participants": ["pm", "developer"],
            "memory_markers": ["pm", "developer"],
        },
    )
    items.append(json.dumps(closed, separators=(",", ":")).replace(ITERATION_ID, iteration_id))
    legacy = LEGACY_SUPERSEDED
    if mutation == "whitespace":
        legacy += " "
    elif mutation == "key_order":
        legacy = legacy.replace('{"iteration_id":', '{"state":"SUPERSEDED","iteration_id":').replace(',"state":"SUPERSEDED"', "", 1)
    elif mutation == "iteration":
        legacy = legacy.replace(iteration_id, iteration_id + "-other")
    elif mutation == "commit":
        legacy = legacy.replace("723624d4", "823624d4")
    if mutation == "ordinal":
        items.insert(0, items.pop())
    else:
        items.append(legacy)
    if mutation == "second_legacy":
        items.append(legacy)
    path = git_repo / f"{iteration_id}.md"
    path.write_text("\n".join(f"```workflow-event\n{item}\n```" for item in items) + "\n")

    try:
        parsed = module.RepositoryGate(root=git_repo)._parse_events(path)
        outcome = parsed[-1].state == "SUPERSEDED"
    except module._GateError:
        outcome = False

    assert outcome is accepted


@pytest.mark.parametrize(
    ("findings", "expected_returncode"),
    [
        ([{"claim": "commit_binding", "detail": "tree binding contradicted"}], 0),
        ([{"claim": "verification_evidence", "detail": "wrong claim"}], 1),
        (["tree binding contradicted"], 1),
        ([], 1),
    ],
)
def test_v1_recovery_review_findings_bind_outer_claim(
    git_repo: Path, findings: list[object], expected_returncode: int
):
    events = valid_events(git_repo, "CLOSED")
    commit = events[7]["evidence"]["commit"]
    review = json.loads(json.dumps(events[5]["evidence"]["reviewers"][0]))
    review["disposition"] = "changes_requested"
    review["findings"] = findings
    events.extend(
        [
            event(
                "SUPERSEDED",
                {
                    "schema_version": 1,
                    "closed_commit": commit,
                    "contradicted_claim": "commit_binding",
                    "recovery": "DESIGNED",
                    "review": review,
                },
            ),
            designed_event(),
        ]
    )
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == expected_returncode, result.stderr


@pytest.mark.parametrize(
    ("disposition", "findings", "accepted"),
    [
        ("approved", [], True),
        ("approved", [{"claim": "commit_binding", "detail": "unexpected"}], False),
        ("changes_requested", [], False),
        (
            "changes_requested",
            [{"claim": "commit_binding", "detail": "tree binding contradicted"}],
            True,
        ),
        ("rejected", ["no findings"], False),
    ],
)
def test_v1_reviewer_schema_uses_structural_findings(
    disposition: str, findings: list[object], accepted: bool
):
    module = load_gate_module()
    candidate = candidate_event(REPO_ROOT)
    raw = review_event(candidate)["evidence"]["reviewers"][0]
    raw["schema_version"] = 1
    raw["disposition"] = disposition
    raw["findings"] = findings

    try:
        module._Reviewer.model_validate(raw)
        outcome = True
    except module.ValidationError:
        outcome = False

    assert outcome is accepted


@pytest.mark.parametrize(
    "mutation",
    ["exact", "byte", "key_order", "candidate_context", "extra_unversioned"],
)
def test_immutable_v0_approved_reviewer_migrations(git_repo: Path, mutation: str):
    module = load_gate_module()
    source = (REPO_ROOT / ".github" / "memory" / "iterations" / "20260827-workflow-gates.md").read_text()
    matches = list(re.finditer(r"^```workflow-event\s*$\n(.*?)\n^```\s*$", source, re.MULTILINE | re.DOTALL))
    reviewed = matches[26].group(1)
    marker = '"reviewers":['
    position = reviewed.index(marker) + len(marker)
    decoder = json.JSONDecoder()
    first, first_end = decoder.raw_decode(reviewed, position)
    second_start = first_end + 1
    _second, second_end = decoder.raw_decode(reviewed, second_start)
    first_raw = reviewed[position:first_end]
    second_raw = reviewed[second_start:second_end]
    if mutation == "byte":
        reviewed = reviewed.replace(first_raw, first_raw.replace('"security"', '"security "', 1), 1)
    elif mutation == "key_order":
        reordered = {"task": first["task"], **{key: value for key, value in first.items() if key != "task"}}
        reviewed = reviewed.replace(first_raw, json.dumps(reordered, separators=(",", ":")), 1)
    elif mutation == "extra_unversioned":
        reviewed = reviewed[:second_end] + "," + second_raw + reviewed[second_end:]
    source = source[: matches[26].start(1)] + reviewed + source[matches[26].end(1) :]
    if mutation == "candidate_context":
        source = source.replace(
            '"tree":"660f50f49f1bb16b9f918f9f280e6fa75e4eaa56"',
            '"tree":"760f50f49f1bb16b9f918f9f280e6fa75e4eaa56"',
            1,
        )
    path = git_repo / "20260827-workflow-gates.md"
    path.write_text(source)

    try:
        module.RepositoryGate(root=git_repo)._parse_events(path)
        outcome = True
    except module._GateError:
        outcome = False

    assert outcome is (mutation == "exact")


@pytest.mark.parametrize("identity_field", ["reviewer", "task", "participants", "memory_markers"])
def test_agent_id_is_canonical_at_schema_ingress(git_repo: Path, identity_field: str):
    events = valid_events(git_repo, "CLOSED")
    if identity_field in {"reviewer", "task"}:
        events[5]["evidence"]["reviewers"][0][identity_field] = "../escape"
    else:
        events[8]["evidence"][identity_field][0] = "../escape"
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert "escape" not in result.stderr


@pytest.mark.parametrize("review_source", ["REVIEWED", "SUPERSEDED"])
def test_final_memory_union_includes_each_review_source(git_repo: Path, review_source: str):
    stage(git_repo, "epoch-a.txt", b"epoch a\n")
    events = valid_events(git_repo, "VERIFIED")
    commit, _ = close_verified_epoch(git_repo, events, "epoch a", ["pm", "developer"])
    if review_source == "REVIEWED":
        events[-1]["evidence"]["participants"].remove("reviewer")
        events[-1]["evidence"]["memory_markers"].remove("reviewer")
    else:
        review = json.loads(json.dumps(events[5]["evidence"]["reviewers"][0]))
        review["reviewer"] = "recovery_reviewer"
        review["disposition"] = "changes_requested"
        review["findings"] = [
            {"claim": "commit_binding", "detail": "commit binding contradicted"}
        ]
        events.extend(
            [
                event(
                    "SUPERSEDED",
                    {
                        "schema_version": 1,
                        "closed_commit": commit,
                        "contradicted_claim": "commit_binding",
                        "recovery": "DESIGNED",
                        "review": review,
                    },
                ),
                designed_event(),
                red_event(),
                implemented_event(),
            ]
        )
        close_recovery_epoch(git_repo, events, "epoch-b.txt", ["pm", "developer", "reviewer"])
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert "memory marker" in result.stderr.lower()


@pytest.mark.parametrize("disposition", ["changes_requested", "rejected"])
def test_nonapproved_review_invalidates_candidate(git_repo: Path, disposition: str):
    events = valid_events(git_repo, "REVIEWED")
    events[5]["evidence"]["reviewers"][0]["disposition"] = disposition
    events[5]["evidence"]["reviewers"][0]["findings"] = [
        {"claim": "gate enforced", "detail": "candidate must change"}
    ]
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert "candidate is invalid and must be changed and re-frozen" in result.stderr.lower()


def test_mixed_review_dispositions_invalidate_candidate(git_repo: Path):
    events = valid_events(git_repo, "REVIEWED")
    second = json.loads(json.dumps(events[5]["evidence"]["reviewers"][0]))
    second["reviewer"] = "second_reviewer"
    second["disposition"] = "changes_requested"
    second["findings"] = [{"claim": "gate enforced", "detail": "candidate must change"}]
    events[5]["evidence"]["reviewers"].append(second)
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert "candidate is invalid and must be changed and re-frozen" in result.stderr.lower()


def test_unknown_review_disposition_fails_without_echo(git_repo: Path):
    unknown = "hostile-disposition-" + "secret-value"
    events = valid_events(git_repo, "REVIEWED")
    events[5]["evidence"]["reviewers"][0]["disposition"] = unknown
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert unknown not in result.stdout + result.stderr
    assert "disposition" in result.stderr.lower()


def test_new_candidate_invalidates_older_approved_reviews(git_repo: Path):
    events = valid_events(git_repo, "REVIEWED")
    events.extend([red_event(), implemented_event()])
    stage(git_repo, "changed.txt", b"changed\n")
    events.append(candidate_event(git_repo))
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 0, result.stderr


def test_hostile_ledger_fields_are_never_echoed(git_repo: Path):
    hostile = "attacker-controlled-field-" + "secret-value"
    events = valid_events(git_repo, "BASELINED")
    events[0]["evidence"][hostile] = "credential-content-should-not-echo"
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert hostile not in result.stdout + result.stderr
    assert "credential-content-should-not-echo" not in result.stdout + result.stderr
    assert result.stderr == "[repository-gate] FAIL: BASELINED evidence contains unsupported fields\n"


@pytest.mark.parametrize("boundary", ["outside", "symlink"])
def test_explicit_ledger_must_be_contained_regular_file(git_repo: Path, boundary: str):
    ledger = write_ledger(git_repo, valid_events(git_repo, "BASELINED"))
    if boundary == "outside":
        selected = git_repo / "outside.md"
        selected.write_text(ledger.read_text())
    else:
        selected = ledger.with_name("linked.md")
        selected.symlink_to(ledger)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(selected))

    assert result.returncode == 1
    assert "ledger" in result.stderr.lower()


def test_auto_discovery_rejects_symlinked_iterations_directory(git_repo: Path):
    memory = git_repo / ".github" / "memory"
    target = memory / "real-iterations"
    target.mkdir(parents=True)
    ledger = target / f"{ITERATION_ID}.md"
    ledger.write_text(
        "```workflow-event\n" + json.dumps(valid_events(git_repo, "BASELINED")[0]) + "\n```\n"
    )
    (memory / "iterations").symlink_to(target, target_is_directory=True)

    result = run_gate(git_repo, "verify-ledger")

    assert result.returncode == 1
    assert "policy root component" in result.stderr.lower()


@pytest.mark.parametrize("ancestor", ["none", ".github", "memory", "iterations"])
def test_policy_root_components_are_canonical_for_every_ledger_surface(
    git_repo: Path, ancestor: str
):
    scripts = git_repo / "scripts"
    scripts.mkdir()
    scanner = scripts / GATE.name
    scanner.write_bytes(GATE.read_bytes())
    scanner.chmod(0o755)
    subprocess.run(["git", "add", "scripts/repository_gate.py"], cwd=git_repo, check=True)
    ledger = write_ledger(git_repo, valid_events(git_repo, "VERIFIED"))
    external: Path | None = None
    if ancestor != "none":
        content = ledger.read_text()
        external = git_repo.parent / ("external-policy-" + uuid4().hex)
        component = {
            ".github": git_repo / ".github",
            "memory": git_repo / ".github" / "memory",
            "iterations": git_repo / ".github" / "memory" / "iterations",
        }[ancestor]
        shutil.rmtree(component)
        suffix = {
            ".github": Path("memory/iterations"),
            "memory": Path("iterations"),
            "iterations": Path(),
        }[ancestor]
        target = external / suffix
        target.mkdir(parents=True)
        (target / ledger.name).write_text(content)
        component.symlink_to(external, target_is_directory=True)
    selected = git_repo / ".github" / "memory" / "iterations" / ledger.name
    try:
        results = [
            run_gate(git_repo, "verify-ledger"),
            run_gate(git_repo, "verify-ledger", "--ledger", str(selected)),
            subprocess.run(
                ["bash", str(REPO_ROOT / ".githooks" / "pre-commit")],
                cwd=git_repo,
                text=True,
                capture_output=True,
                env={"PATH": os.environ["PATH"]},
                check=False,
            ),
        ]
    finally:
        if external is not None:
            shutil.rmtree(external)

    expected = 0 if ancestor == "none" else 1
    assert [result.returncode for result in results] == [expected, expected, expected]
    combined = "".join(result.stdout + result.stderr for result in results)
    if external is not None:
        assert str(external) not in combined


def test_symlinked_repository_invocation_uses_canonical_git_toplevel(git_repo: Path):
    scripts = git_repo / "scripts"
    scripts.mkdir()
    scanner = scripts / GATE.name
    scanner.write_bytes(GATE.read_bytes())
    scanner.chmod(0o755)
    subprocess.run(["git", "add", "scripts/repository_gate.py"], cwd=git_repo, check=True)
    write_ledger(git_repo, valid_events(git_repo, "VERIFIED"))
    invocation = git_repo.parent / ("repository-link-" + uuid4().hex)
    invocation.symlink_to(git_repo, target_is_directory=True)
    try:
        result = run_gate(invocation, "verify-ledger")
    finally:
        invocation.unlink()

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("boundary", ["noncanonical", "symlink"])
def test_participant_memories_are_canonical_contained_regular_files(git_repo: Path, boundary: str):
    events = valid_events(git_repo, "CLOSED")
    participant = "../escape" if boundary == "noncanonical" else "security"
    events[8]["evidence"]["participants"].append(participant)
    events[8]["evidence"]["memory_markers"].append(participant)
    if boundary == "noncanonical":
        (git_repo / ".github" / "escape.md").write_text(ITERATION_ID)
    else:
        target = git_repo / ".github" / "memory" / "security-target.md"
        target.write_text(ITERATION_ID)
        (git_repo / ".github" / "memory" / "security.md").symlink_to(target)
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert ("malformed" if boundary == "noncanonical" else "memory") in result.stderr.lower()
    assert "escape" not in result.stderr


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


def test_changed_candidate_invalidates_review_and_manifest(git_repo: Path):
    ledger = write_ledger(git_repo, valid_events(git_repo, "VERIFIED"))
    stage(git_repo, "changed.txt", b"changed\n")

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert "stale" in result.stderr.lower()


def test_red_remediation_invalidates_old_candidate_before_refreeze(git_repo: Path):
    events = valid_events(git_repo, "CANDIDATE_FROZEN")
    events.extend([red_event(), implemented_event()])
    stage(git_repo, "changed.txt", b"changed\n")
    ledger = write_ledger(git_repo, events)
    assert run_gate(git_repo, "verify-ledger", "--ledger", str(ledger)).returncode == 0

    events.append(candidate_event(git_repo))
    write_ledger(git_repo, events)
    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("count", [0, 2])
def test_active_ledger_discovery_requires_exactly_one(git_repo: Path, count: int):
    for index in range(count):
        events = valid_events(git_repo, "BASELINED")
        events[0]["iteration_id"] = f"{ITERATION_ID}-{index}"
        directory = git_repo / ".github" / "memory" / "iterations"
        directory.mkdir(parents=True, exist_ok=True)
        ledger = directory / f"{ITERATION_ID}-{index}.md"
        ledger.write_text("```workflow-event\n" + json.dumps(events[0]) + "\n```\n")

    result = run_gate(git_repo, "verify-ledger")

    assert result.returncode == 1
    assert "active ledger" in result.stderr.lower()


def test_active_discovery_selects_latest_unsuperseded_recovery_epoch(git_repo: Path):
    directory = git_repo / ".github" / "memory" / "iterations"
    directory.mkdir(parents=True)
    closed_events = valid_events(git_repo, "CLOSED")
    for ledger_id, recovered in (("closed-history", False), ("active-recovery", True)):
        events = json.loads(json.dumps(closed_events))
        for item in events:
            item["iteration_id"] = ledger_id
        if recovered:
            commit = events[7]["evidence"]["commit"]
            supersede_closed_epoch(events, commit)
            for item in events[9:]:
                item["iteration_id"] = ledger_id
        (directory / f"{ledger_id}.md").write_text(
            "\n".join("```workflow-event\n" + json.dumps(item) + "\n```" for item in events)
            + "\n"
        )
    for name in ("pm", "developer", "reviewer"):
        (git_repo / ".github" / "memory" / f"{name}.md").write_text(
            "# memory\n\n- closed-history\n- active-recovery\n"
        )

    result = run_gate(git_repo, "verify-ledger")

    assert result.returncode == 0, result.stderr


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


def test_hook_invokes_repository_gate_after_generation_before_compile():
    hook = (REPO_ROOT / ".githooks" / "pre-commit").read_text()

    gate_position = hook.index("repository_gate.py")
    assert "generate-types.sh" in hook[:gate_position]
    assert "npm run compile" in hook[gate_position:]
    assert 'uv run python "$gate_exec" hook' in hook
    gate_source = GATE.read_text()
    assert "scan-staged" in gate_source
    assert "verify-ledger" in gate_source
    assert "version mismatch" in hook


def test_hook_executes_scanner_before_ledger_validation(git_repo: Path):
    scripts = git_repo / "scripts"
    scripts.mkdir()
    shutil.copy2(GATE, scripts / GATE.name)
    subprocess.run(["git", "add", "scripts/repository_gate.py"], cwd=git_repo, check=True)
    stage(git_repo, "candidate.txt", b"token = 'ghp_" + b"abcdefghijklmnopqrstuvwxyz123456'\n")

    result = subprocess.run(
        ["bash", str(REPO_ROOT / ".githooks" / "pre-commit")],
        cwd=git_repo,
        text=True,
        capture_output=True,
        env={"PATH": os.environ["PATH"]},
        check=False,
    )

    assert result.returncode == 1
    assert "credential-prefix" in result.stderr
    assert "active ledger" not in result.stderr


def test_hook_executes_staged_scanner_when_worktree_copy_is_replaced(git_repo: Path):
    scripts = git_repo / "scripts"
    scripts.mkdir()
    scanner = scripts / GATE.name
    scanner.write_bytes(GATE.read_bytes())
    scanner.chmod(0o755)
    subprocess.run(["git", "add", "scripts/repository_gate.py"], cwd=git_repo, check=True)
    scanner.write_text("raise SystemExit(0)\n")
    stage(git_repo, "candidate.txt", b"token = 'ghp_" + b"abcdefghijklmnopqrstuvwxyz123456'\n")

    result = subprocess.run(
        ["bash", str(REPO_ROOT / ".githooks" / "pre-commit")],
        cwd=git_repo,
        text=True,
        capture_output=True,
        env={"PATH": os.environ["PATH"]},
        check=False,
    )

    assert result.returncode == 1
    assert "credential-prefix" in result.stderr
    assert "active ledger" not in result.stderr


@pytest.mark.parametrize("terminal", ["CANDIDATE_FROZEN", "VERIFIED"])
def test_full_hook_requires_reviewed_and_verified_candidate(git_repo: Path, terminal: str):
    scripts = git_repo / "scripts"
    scripts.mkdir()
    scanner = scripts / GATE.name
    scanner.write_bytes(GATE.read_bytes())
    scanner.chmod(0o755)
    subprocess.run(["git", "add", "scripts/repository_gate.py"], cwd=git_repo, check=True)
    write_ledger(git_repo, valid_events(git_repo, terminal))

    result = subprocess.run(
        ["bash", str(REPO_ROOT / ".githooks" / "pre-commit")],
        cwd=git_repo,
        text=True,
        capture_output=True,
        env={"PATH": os.environ["PATH"]},
        check=False,
    )

    expected = 0 if terminal == "VERIFIED" else 1
    assert result.returncode == expected, result.stdout + result.stderr
    if terminal == "CANDIDATE_FROZEN":
        assert "reviewed and verified" in (result.stdout + result.stderr).lower()
