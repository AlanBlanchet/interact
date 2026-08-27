#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

State = Literal[
    "BASELINED",
    "DESIGNED",
    "RED",
    "IMPLEMENTED",
    "CANDIDATE_FROZEN",
    "REVIEWED",
    "VERIFIED",
    "COMMITTED",
    "CLOSED",
]
FindingClass = Literal[
    "private-key",
    "credential-prefix",
    "authorization",
    "credential-assignment",
    "credential-uri",
    "personal-path",
    "confidential-term",
    "unscannable-oversize",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Baseline(_StrictModel):
    request: str
    acceptance: list[str]
    branch: str
    head: str
    status: str
    unstaged_diff_sha256: str
    staged_diff_sha256: str
    untracked_checksums: dict[str, str]
    protected_paths: list[str]
    overlap: str


class _Design(_StrictModel):
    interpretation: str
    non_goals: list[str]
    owners: list[str]
    interfaces: list[str]
    invariants: list[str]
    edge_cases: list[str]
    trust_boundaries: list[str]
    tests: list[str]
    negative_controls: list[str]
    cost: str
    visual_route: str
    compatibility: str


class _CommandEvidence(_StrictModel):
    argv: list[str] = Field(min_length=1)
    cwd: str
    environment: dict[str, str]
    includes: list[str] = Field(min_length=1)
    excludes: list[str]
    exit_code: int
    summary: str


class _Red(_CommandEvidence):
    failing_assertion: str


class _Implemented(_StrictModel):
    owned_paths: list[str] = Field(min_length=1)
    summary: str


class _Candidate(_StrictModel):
    tree: str
    staged_diff_sha256: str
    owned_paths: list[str] = Field(min_length=1)
    acceptance_sha256: str


class _Reviewer(_StrictModel):
    reviewer: str = Field(min_length=1)
    task: str = Field(min_length=1)
    candidate_tree: str
    acceptance_sha256: str
    inspected_paths: list[str] = Field(min_length=1)
    findings: list[str] = Field(min_length=1)
    disposition: Literal["approved", "changes_requested", "rejected"]
    commands: list[_CommandEvidence] = Field(min_length=1)


class _Reviewed(_StrictModel):
    candidate_tree: str
    acceptance_sha256: str
    reviewers: list[_Reviewer] = Field(min_length=1)


class _Verified(_StrictModel):
    candidate_tree: str
    acceptance_sha256: str
    commands: list[_CommandEvidence] = Field(min_length=1)


class _Committed(_StrictModel):
    commit: str
    tree: str
    candidate_tree: str


class _Closed(_StrictModel):
    acceptance: dict[str, Literal["satisfied", "blocked"]] = Field(min_length=1)
    blockers: list[str]
    processes: list[str]
    participants: list[str] = Field(min_length=2)
    memory_markers: list[str] = Field(min_length=2)


class _RawEvent(_StrictModel):
    iteration_id: str
    state: State
    evidence: dict[str, Any]


class _Event(_StrictModel):
    iteration_id: str
    state: State
    evidence: _Baseline | _Design | _Red | _Implemented | _Candidate | _Reviewed | _Verified | _Committed | _Closed


class _Finding(_StrictModel):
    path: str
    line: int | Literal["binary"]
    finding_class: FindingClass


class _GateError(RuntimeError):
    pass


class RepositoryGate(BaseModel):
    root: Path

    _STATES = (
        "BASELINED",
        "DESIGNED",
        "RED",
        "IMPLEMENTED",
        "CANDIDATE_FROZEN",
        "REVIEWED",
        "VERIFIED",
        "COMMITTED",
        "CLOSED",
    )
    _EVIDENCE_TYPES = {
        "BASELINED": _Baseline,
        "DESIGNED": _Design,
        "RED": _Red,
        "IMPLEMENTED": _Implemented,
        "CANDIDATE_FROZEN": _Candidate,
        "REVIEWED": _Reviewed,
        "VERIFIED": _Verified,
        "COMMITTED": _Committed,
        "CLOSED": _Closed,
    }
    # Detector declarations are structurally suppressed only while this exact tuple is parsed.
    _DETECTORS: ClassVar[tuple[tuple[FindingClass, bytes], ...]] = (
        ("private-key", rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
        ("credential-prefix", rb"(?:gh[pousr]_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{20,}|sk-ant-api03-[A-Za-z0-9_-]{40,}|sk-(?:proj-|svcacct-)[A-Za-z0-9_-]{32,}|sk-[A-Za-z0-9]{32,}|AKIA[A-Z0-9]{16})"),
        ("authorization", rb"(?i)(?:authorization\s*[:=]\s*|\bbearer\s+)[A-Za-z0-9._~+/=-]{20,}"),
        ("credential-assignment", rb"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret)\b\s*[:=]\s*['\"]?(?!example|placeholder|dummy|redacted|test)[^'\"\s]{12,}"),
        ("credential-uri", rb"(?i)\b[a-z][a-z0-9+.-]*://[^\s/:]+:[^\s/@]+@"),
        ("personal-path", rb"(?:^|[=:'\"\s])/(?:home|Users)/[^/\s]+/[^\s'\"]+"),
    )
    _MAX_BLOB_BYTES = 8 * 1024 * 1024
    _EVENT_PATTERN = re.compile(r"^```workflow-event\s*$\n(.*?)\n^```\s*$", re.MULTILINE | re.DOTALL)

    @classmethod
    def discover(cls, root: Path):
        probe = cls(root=root.resolve())
        top_level = probe._git(b"rev-parse", b"--show-toplevel")
        assert top_level is not None
        return cls(root=Path(os.fsdecode(top_level.rstrip(b"\n"))).resolve())

    def scan_staged(self):
        findings: list[_Finding] = []
        confidential_terms = self._confidential_terms()
        for path in self._staged_destinations():
            display_path = os.fsdecode(path)
            size = self._blob_size(path)
            if size > self._MAX_BLOB_BYTES:
                findings.append(
                    _Finding(path=display_path, line="binary", finding_class="unscannable-oversize")
                )
                continue
            indexed = self._blob(b":./" + path)
            if indexed is None:
                raise _GateError("indexed scanner input is unavailable")
            if b"\0" in indexed:
                findings.extend(self._scan_bytes(display_path, "binary", indexed, confidential_terms))
                continue
            added = self._added_lines(path, indexed)
            for line_number, line in added:
                findings.extend(self._scan_bytes(display_path, line_number, line, confidential_terms))
        if findings:
            for finding in findings:
                path = json.dumps(
                    self._safe_finding_path(finding.path, confidential_terms), ensure_ascii=True
                )
                print(f"[repository-gate] {path}:{finding.line}: {finding.finding_class}", file=sys.stderr)
            print("[repository-gate] blocked: remove staged confidential content", file=sys.stderr)
            raise _GateError("staged content contains confidential material")

    def verify_ledger(self, ledger: Path | None = None):
        path = self._active_ledger() if ledger is None else self._explicit_ledger(ledger)
        events = self._parse_events(path)
        self._validate_sequence(events)
        self._validate_bindings(events)
        return events[-1].state

    def run_hook(self):
        self.scan_staged()
        if self.verify_ledger() != "VERIFIED":
            raise _GateError("current candidate must be REVIEWED and VERIFIED")

    def _git(self, *arguments: bytes, allowed_failure: bool = False):
        command = [b"git", *arguments]
        try:
            result = subprocess.run(command, cwd=os.fsencode(self.root), capture_output=True, check=False)
        except OSError as error:
            raise _GateError("Git executable unavailable") from error
        if result.returncode != 0:
            if allowed_failure:
                return None
            raise _GateError("Git command failed")
        return result.stdout

    def _staged_destinations(self):
        output = self._git(b"diff", b"--cached", b"--name-status", b"-z", b"--diff-filter=ACMR")
        assert output is not None
        fields = output.rstrip(b"\0").split(b"\0") if output else []
        paths: list[bytes] = []
        index = 0
        while index < len(fields):
            status = fields[index]
            index += 1
            if status[:1] in {b"R", b"C"}:
                if index + 1 >= len(fields):
                    raise _GateError("Git returned malformed staged paths")
                index += 1
                paths.append(fields[index])
                index += 1
            else:
                if index >= len(fields):
                    raise _GateError("Git returned malformed staged paths")
                paths.append(fields[index])
                index += 1
        return paths

    def _blob(self, specification: bytes):
        return self._git(b"show", b"--no-textconv", specification, allowed_failure=True)

    def _blob_size(self, path: bytes):
        output = self._git(b"cat-file", b"-s", b":./" + path, allowed_failure=True)
        if output is None:
            raise _GateError("indexed scanner input is unavailable")
        try:
            return int(output)
        except ValueError as error:
            raise _GateError("Git returned an invalid indexed blob size") from error

    def _added_lines(self, path: bytes, indexed: bytes):
        new_lines = indexed.split(b"\n")
        diff = self._git(
            b"diff",
            b"--cached",
            b"--unified=0",
            b"--text",
            b"--no-color",
            b"--no-ext-diff",
            b"--no-textconv",
            b"--",
            path,
        )
        assert diff is not None
        added: list[tuple[int, bytes]] = []
        for line in diff.split(b"\n"):
            hunk = re.match(rb"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if hunk is None:
                continue
            start = int(hunk.group(1))
            count = int(hunk.group(2) or b"1")
            if count == 0:
                continue
            if start < 1 or start + count - 1 > len(new_lines):
                raise _GateError("Git returned invalid staged hunk metadata")
            added.extend((number, new_lines[number - 1]) for number in range(start, start + count))
        return added

    def _scan_bytes(
        self,
        path: str,
        line_number: int | Literal["binary"],
        content: bytes,
        confidential_terms: list[bytes],
    ):
        findings: list[_Finding] = []
        declaration_class: bytes | None = None
        if path == "scripts/repository_gate.py":
            declaration = re.fullmatch(rb'\s*\("([a-z-]+)", rb".*"\),\s*', content)
            if declaration is not None:
                declaration_class = declaration.group(1)
        for finding_class, pattern in self._DETECTORS:
            if declaration_class == finding_class.encode():
                continue
            if re.search(pattern, content):
                findings.append(_Finding(path=path, line=line_number, finding_class=finding_class))
        if any(term in content for term in confidential_terms):
            findings.append(_Finding(path=path, line=line_number, finding_class="confidential-term"))
        return findings

    def _safe_finding_path(self, path: str, confidential_terms: list[bytes]):
        encoded = os.fsencode(path)
        if any(re.search(pattern, encoded) for _finding_class, pattern in self._DETECTORS) or any(
            term in encoded for term in confidential_terms
        ):
            return "<redacted-path>"
        return path

    def _confidential_terms(self):
        configured = self._git(b"config", b"--local", b"--path", b"--get", b"interact.confidentialTermsFile", allowed_failure=True)
        if not configured:
            return []
        raw_path = os.fsdecode(configured.rstrip(b"\n"))
        git_dir_output = self._git(b"rev-parse", b"--absolute-git-dir")
        assert git_dir_output is not None
        git_dir = Path(os.fsdecode(git_dir_output.rstrip(b"\n"))).resolve()
        configured_path = Path(raw_path)
        path = git_dir / configured_path if not configured_path.is_absolute() else configured_path
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(git_dir)
            metadata = path.lstat()
        except (ValueError, OSError) as error:
            raise _GateError("confidential-term file must be beneath the Git directory") from error
        if resolved != path.absolute() or stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise _GateError("confidential-term file must be a regular non-symlink with mode 0600")
        content = self._read_stable_file(path, metadata, "confidential-term")
        terms = [line for line in content.splitlines() if len(line) >= 4]
        return terms

    def _active_ledger(self):
        directory = self._policy_directory(required=False)
        active: list[Path] = []
        if directory is not None:
            for path in sorted(directory.glob("*.md")):
                if path.is_symlink() or not path.is_file():
                    continue
                events = self._parse_events(path)
                if events[-1].state != "CLOSED":
                    active.append(path)
        if len(active) != 1:
            raise _GateError("exactly one active ledger is required")
        return active[0]

    def _explicit_ledger(self, ledger: Path):
        directory = self._policy_directory(required=True)
        assert directory is not None
        candidate = ledger if ledger.is_absolute() else self.root / ledger
        try:
            metadata = candidate.lstat()
        except OSError as error:
            raise _GateError("explicit ledger must be contained in the iterations directory") from error
        if (
            candidate.parent.absolute() != directory
            or stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
        ):
            raise _GateError("explicit ledger must be a regular non-symlink file")
        return candidate

    def _policy_directory(self, required: bool):
        paths = [
            self.root / ".github",
            self.root / ".github" / "memory",
            self.root / ".github" / "memory" / "iterations",
        ]
        identities: list[tuple[int, int, int]] = []
        for path in paths:
            try:
                metadata = path.lstat()
            except FileNotFoundError as error:
                if required:
                    raise _GateError("repository policy root is unavailable") from error
                return None
            except OSError as error:
                raise _GateError("repository policy root is unreadable") from error
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise _GateError("repository policy root component must be a regular directory")
            identities.append((metadata.st_dev, metadata.st_ino, metadata.st_mode))
        for path, identity in zip(paths, identities, strict=True):
            try:
                metadata = path.lstat()
            except OSError as error:
                raise _GateError("repository policy root changed during validation") from error
            if (metadata.st_dev, metadata.st_ino, metadata.st_mode) != identity:
                raise _GateError("repository policy root changed during validation")
        return paths[-1].absolute()

    def _parse_events(self, path: Path):
        if path.is_symlink() or not path.is_file():
            raise _GateError("ledger must be a regular non-symlink file")
        metadata = path.lstat()
        try:
            text = self._read_stable_file(path, metadata, "ledger").decode("utf-8")
        except UnicodeError as error:
            raise _GateError("ledger is unreadable") from error
        matches = list(self._EVENT_PATTERN.finditer(text))
        if not matches or text.count("```workflow-event") != len(matches):
            raise _GateError("ledger contains no workflow events")
        events: list[_Event] = []
        for match in matches:
            block = match.group(1)
            try:
                raw = _RawEvent.model_validate_json(block)
            except ValidationError as error:
                raise _GateError("ledger event envelope is malformed") from error
            evidence_type = self._EVIDENCE_TYPES[raw.state]
            try:
                evidence = evidence_type.model_validate(raw.evidence)
                events.append(_Event(iteration_id=raw.iteration_id, state=raw.state, evidence=evidence))
            except ValidationError as error:
                raise _GateError(self._safe_validation_message(raw.state, evidence_type, error)) from error
            except ValueError as error:
                raise _GateError("ledger event evidence is malformed") from error
            if raw.state == "CLOSED" and text[match.end() :].strip():
                raise _GateError("CLOSED event must be terminal")
        expected_id = path.stem
        if any(item.iteration_id != expected_id for item in events):
            raise _GateError("ledger filename and iteration id differ")
        return events

    def _validate_sequence(self, events: list[_Event]):
        expected_index = 0
        candidate_seen = False
        remediation_red = False
        for item in events:
            if expected_index == len(self._STATES):
                raise _GateError("ledger has content after CLOSED")
            if candidate_seen and item.state == "RED" and expected_index in {5, 6, 7}:
                expected_index = 2
                remediation_red = True
            elif candidate_seen and item.state == "CANDIDATE_FROZEN" and expected_index in {5, 6, 7}:
                expected_index = 4
            expected = self._STATES[expected_index]
            if item.state != expected:
                raise _GateError("ledger state order is invalid")
            expected_index += 1
            if item.state == "CANDIDATE_FROZEN":
                candidate_seen = True
                remediation_red = False
            elif remediation_red and item.state == "IMPLEMENTED":
                expected_index = 4

    def _validate_bindings(self, events: list[_Event]):
        candidate: _Candidate | None = None
        baseline = events[0].evidence
        assert isinstance(baseline, _Baseline)
        acceptance_sha256 = hashlib.sha256(
            json.dumps(baseline.acceptance, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()
        for item in events:
            if item.state == "CANDIDATE_FROZEN":
                assert isinstance(item.evidence, _Candidate)
                candidate = item.evidence
                if candidate.acceptance_sha256 != acceptance_sha256:
                    raise _GateError("candidate acceptance hash is invalid")
            elif item.state == "REVIEWED":
                assert isinstance(item.evidence, _Reviewed)
                self._require_candidate(candidate, item.evidence.candidate_tree, item.evidence.acceptance_sha256)
                for reviewer in item.evidence.reviewers:
                    self._require_candidate(
                        candidate, reviewer.candidate_tree, reviewer.acceptance_sha256
                    )
                    if reviewer.disposition != "approved":
                        raise _GateError(
                            "candidate is invalid and must be changed and re-frozen"
                        )
                    if any(command.exit_code != 0 for command in reviewer.commands):
                        raise _GateError("REVIEWED command exit_code must be zero")
            elif item.state == "VERIFIED":
                assert isinstance(item.evidence, _Verified)
                self._require_candidate(candidate, item.evidence.candidate_tree, item.evidence.acceptance_sha256)
                if any(command.exit_code != 0 for command in item.evidence.commands):
                    raise _GateError("VERIFIED exit_code must be zero")
            elif item.state == "COMMITTED":
                assert isinstance(item.evidence, _Committed)
                self._validate_commit(candidate, item.evidence)
            elif item.state == "CLOSED":
                assert isinstance(item.evidence, _Closed)
                if set(item.evidence.acceptance) != set(baseline.acceptance):
                    raise _GateError("CLOSED acceptance does not reconcile with BASELINED acceptance")
                self._validate_memories(events[0].iteration_id, item.evidence, candidate)
            elif item.state == "RED":
                assert isinstance(item.evidence, _Red)
                if item.evidence.exit_code == 0:
                    raise _GateError("RED exit_code must be nonzero")
                candidate = None
        if candidate is not None:
            current = self._git(b"write-tree")
            assert current is not None
            if current.decode().strip() != candidate.tree:
                raise _GateError("candidate is stale")
            staged_diff = self._git(b"diff", b"--cached", b"--binary")
            assert staged_diff is not None
            if hashlib.sha256(staged_diff).hexdigest() != candidate.staged_diff_sha256:
                raise _GateError("candidate staged diff hash is stale")

    @staticmethod
    def _require_candidate(candidate: _Candidate | None, tree: str, acceptance_sha256: str):
        if candidate is None or tree != candidate.tree or acceptance_sha256 != candidate.acceptance_sha256:
            raise _GateError("review or verification does not match candidate")

    def _validate_commit(self, candidate: _Candidate | None, committed: _Committed):
        if candidate is None or committed.candidate_tree != candidate.tree or committed.tree != candidate.tree:
            raise _GateError("commit tree does not match candidate tree")
        actual = self._git(b"rev-parse", os.fsencode(committed.commit + "^{tree}"), allowed_failure=True)
        if actual is None or actual.decode().strip() != committed.tree:
            raise _GateError("recorded commit tree does not match Git")
        current_head = self._git(b"rev-parse", b"HEAD", allowed_failure=True)
        current_tree = self._git(b"rev-parse", b"HEAD^{tree}", allowed_failure=True)
        if current_head is None or current_tree is None:
            raise _GateError("current HEAD must be a commit")
        if current_head.decode().strip() != committed.commit:
            raise _GateError("current HEAD does not match recorded commit")
        if current_tree.decode().strip() != committed.tree:
            raise _GateError("current HEAD tree does not match candidate tree")

    def _validate_memories(self, iteration_id: str, closed: _Closed, candidate: _Candidate | None):
        required = set(closed.participants) | {"pm", "developer"}
        prompt_paths = {"AGENTS.md", "CLAUDE.md", ".github/copilot-instructions.md"}
        if candidate is not None and prompt_paths.intersection(candidate.owned_paths):
            required.add("librarian")
        if set(closed.memory_markers) != required:
            raise _GateError("memory marker set does not match participants")
        for participant in required:
            if re.fullmatch(r"[a-z][a-z0-9_]*", participant) is None:
                raise _GateError("memory participant identifier is not canonical")
            path = self.root / ".github" / "memory" / f"{participant.replace('_', '-')}.md"
            try:
                metadata = path.lstat()
                memory_root = (self.root / ".github" / "memory").resolve(strict=True)
                path.resolve(strict=True).relative_to(memory_root)
                if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                    raise _GateError("required memory marker must be a regular non-symlink file")
                content = self._read_stable_file(path, metadata, "memory").decode("utf-8")
            except (OSError, UnicodeError, ValueError) as error:
                raise _GateError("required memory marker is absent") from error
            if iteration_id not in content:
                raise _GateError("required memory marker is absent")

    def _read_stable_file(self, path: Path, metadata: os.stat_result, label: str):
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                before = os.fstat(stream.fileno())
                if before.st_dev != metadata.st_dev or before.st_ino != metadata.st_ino:
                    raise _GateError(f"{label} file changed during validation")
                content = stream.read(self._MAX_BLOB_BYTES + 1)
                after = os.fstat(stream.fileno())
        except OSError as error:
            raise _GateError(f"{label} file is unreadable") from error
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        final_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if identity != final_identity:
            raise _GateError(f"{label} file changed during validation")
        if len(content) > self._MAX_BLOB_BYTES:
            raise _GateError(f"{label} file is too large")
        return content

    @staticmethod
    def _safe_validation_message(state: State, evidence_type: type[_StrictModel], error: ValidationError):
        errors = error.errors(include_input=False)
        if any(item["type"] == "extra_forbidden" for item in errors):
            return f"{state} evidence contains unsupported fields"
        known: set[str] = set(evidence_type.model_fields)
        pending = [_StrictModel]
        while pending:
            model = pending.pop()
            known.update(model.model_fields)
            pending.extend(model.__subclasses__())
        fields = sorted(
            {
                str(item["loc"][-1])
                for item in errors
                if item["loc"] and str(item["loc"][-1]) in known
            }
        )
        if not fields:
            return f"{state} evidence is malformed"
        return f"{state} evidence is malformed: {', '.join(fields)}"

    @staticmethod
    def cli(argv: list[str]):
        parser = argparse.ArgumentParser(description="Validate repository commit and workflow evidence")
        subparsers = parser.add_subparsers(dest="action", required=True)
        subparsers.add_parser("scan-staged")
        verify = subparsers.add_parser("verify-ledger")
        verify.add_argument("--ledger", type=Path)
        subparsers.add_parser("hook")
        arguments = parser.parse_args(argv)
        try:
            gate = RepositoryGate.discover(Path.cwd())
            if arguments.action == "scan-staged":
                gate.scan_staged()
            elif arguments.action == "verify-ledger":
                gate.verify_ledger(arguments.ledger)
            else:
                gate.run_hook()
        except _GateError as error:
            print(f"[repository-gate] FAIL: {error}", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(RepositoryGate.cli(sys.argv[1:]))
