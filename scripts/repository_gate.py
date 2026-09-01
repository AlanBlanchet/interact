#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

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
    "SUPERSEDED",
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
NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
GitObjectId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
AgentId = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z][a-z0-9_]*$")
]
IterationId = Annotated[
    str, StringConstraints(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
]
RepositoryPath = Annotated[str, StringConstraints(min_length=1)]
BootstrapFailureCode = Literal["prospective_authorization_failed"]
BootstrapReplayError = Literal[
    "ordinary_baseline_schema_unsupported",
    "recovery_baseline_chain_invalid",
]
BootstrapAuthority = Literal[
    "workflow_event",
    "product_source",
    "candidate",
    "review",
    "verification",
    "commit",
    "closure",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Baseline(_StrictModel):
    request: NonBlankStr
    acceptance: list[NonBlankStr] = Field(min_length=1)
    branch: str
    head: str
    status: str
    unstaged_diff_sha256: str
    staged_diff_sha256: str
    untracked_checksums: dict[str, str]
    protected_paths: list[str]
    overlap: str


class _Design(_StrictModel):
    interpretation: NonBlankStr
    non_goals: list[NonBlankStr] = Field(min_length=1)
    owners: list[NonBlankStr] = Field(min_length=1)
    interfaces: list[NonBlankStr] = Field(min_length=1)
    invariants: list[NonBlankStr] = Field(min_length=1)
    edge_cases: list[NonBlankStr] = Field(min_length=1)
    trust_boundaries: list[NonBlankStr] = Field(min_length=1)
    tests: list[NonBlankStr] = Field(min_length=1)
    negative_controls: list[NonBlankStr] = Field(min_length=1)
    cost: NonBlankStr
    visual_route: NonBlankStr
    compatibility: NonBlankStr


class _CommandEvidence(_StrictModel):
    argv: list[str] = Field(min_length=1)
    cwd: str
    environment: dict[str, str]
    includes: list[str] = Field(min_length=1)
    excludes: list[str]
    exit_code: int
    summary: NonBlankStr


class _Red(_CommandEvidence):
    failing_assertion: NonBlankStr


class _Implemented(_StrictModel):
    owned_paths: list[str] = Field(min_length=1)
    summary: NonBlankStr


class _Candidate(_StrictModel):
    tree: str
    staged_diff_sha256: str
    owned_paths: list[str] = Field(min_length=1)
    acceptance_sha256: str


class _ReviewFinding(_StrictModel):
    claim: NonBlankStr
    detail: NonBlankStr


class _Reviewer(_StrictModel):
    schema_version: Literal[1]
    reviewer: AgentId
    task: AgentId
    candidate_tree: str
    acceptance_sha256: str
    inspected_paths: list[str] = Field(min_length=1)
    findings: list[_ReviewFinding]
    disposition: Literal["approved", "changes_requested", "rejected"]
    commands: list[_CommandEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_finding_cardinality(self):
        if (self.disposition == "approved") == bool(self.findings):
            raise ValueError("review finding cardinality is invalid")
        return self


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
    participants: list[AgentId] = Field(min_length=2)
    memory_markers: list[AgentId] = Field(min_length=2)


class _Superseded(_StrictModel):
    schema_version: Literal[1]
    closed_commit: str
    contradicted_claim: NonBlankStr
    recovery: Literal["RED", "DESIGNED"]
    review: _Reviewer | None = None

    @model_validator(mode="after")
    def validate_recovery_shape(self):
        if (self.recovery == "DESIGNED") != (self.review is not None):
            raise ValueError("SUPERSEDED recovery evidence is malformed")
        return self


class _MigrationRecord(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_sha256: str
    iteration_id: str
    ordinal: int
    preceding_closed_commit: str
    contradicted_claim: str
    recovery: Literal["RED", "DESIGNED"]


class _ReviewerMigrationRecord(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_sha256: str
    iteration_id: str
    event_ordinal: int
    reviewer_index: int
    preceding_candidate_tree: str
    preceding_commit: str | None
    reviewer: AgentId


class _RawEvent(_StrictModel):
    iteration_id: str
    state: State
    evidence: dict[str, Any]


class _QuarantineManifest(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    predecessor_path: str
    predecessor_iteration_id: str
    predecessor_sha256: Sha256
    predecessor_size: int = Field(gt=0)
    base_head: GitObjectId
    parser_failure_code: Literal[
        "reviewed_commands_missing",
        "recovery_request_mismatch",
        "invalid_state_transition",
        "prospective_authorization_failed",
    ]
    failing_event_ordinal: int = Field(gt=0)
    failing_raw_block_sha256: Sha256
    failing_full_fence_sha256: Sha256 | None = None
    trusted_prefix_event_count: int = Field(ge=0)
    trusted_prefix_sha256: Sha256
    request: NonBlankStr | None = None
    request_sha256: Sha256 | None = None
    actual_request_sha256: Sha256 | None = None
    acceptance_sha256: Sha256
    successor_iteration_id: str
    actual_state: State | None = None
    expected_state: State | None = None
    baseline_snapshot_tree: GitObjectId | None = None
    baseline_snapshot_stderr_sha256: Sha256 | None = None
    prospective_candidate_tree: GitObjectId | None = None
    prospective_candidate_stderr_sha256: Sha256 | None = None
    prospective_gate_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def validate_failure_shape(self):
        legacy = self.parser_failure_code == "reviewed_commands_missing"
        prospective_values = (
            self.baseline_snapshot_tree,
            self.baseline_snapshot_stderr_sha256,
            self.prospective_candidate_tree,
            self.prospective_candidate_stderr_sha256,
            self.prospective_gate_sha256,
        )
        legacy_fields = self.request is not None and self.request_sha256 is None
        mismatch_fields = (
            self.request is None
            and self.request_sha256 is not None
            and self.actual_request_sha256 is not None
            and self.request_sha256 != self.actual_request_sha256
            and self.failing_full_fence_sha256 is not None
            and self.actual_state is None
            and self.expected_state is None
            and all(value is None for value in prospective_values)
        )
        transition_fields = (
            self.request is None
            and self.request_sha256 is not None
            and self.actual_request_sha256 is None
            and self.failing_full_fence_sha256 is not None
            and self.actual_state is not None
            and self.expected_state is not None
            and self.actual_state != self.expected_state
            and all(value is None for value in prospective_values)
        )
        prospective_fields = (
            self.request is None
            and self.request_sha256 is not None
            and self.failing_full_fence_sha256 is not None
            and self.trusted_prefix_event_count == 0
            and all(
                value is not None
                for value in (
                    self.baseline_snapshot_tree,
                    self.baseline_snapshot_stderr_sha256,
                    self.prospective_candidate_tree,
                    self.prospective_candidate_stderr_sha256,
                    self.prospective_gate_sha256,
                )
            )
            and self.actual_state is None
            and self.expected_state is None
        )
        if legacy:
            if not legacy_fields or any(
                value is not None
                for value in (
                    self.failing_full_fence_sha256,
                    self.actual_request_sha256,
                    self.actual_state,
                    self.expected_state,
                    self.baseline_snapshot_tree,
                    self.baseline_snapshot_stderr_sha256,
                    self.prospective_candidate_tree,
                    self.prospective_candidate_stderr_sha256,
                    self.prospective_gate_sha256,
                )
            ):
                raise ValueError("reviewed_commands_missing manifest shape is invalid")
        elif self.parser_failure_code == "recovery_request_mismatch" and not mismatch_fields:
            raise ValueError("recovery_request_mismatch manifest shape is invalid")
        elif self.parser_failure_code == "invalid_state_transition" and not transition_fields:
            raise ValueError("invalid_state_transition manifest shape is invalid")
        elif self.parser_failure_code == "prospective_authorization_failed" and not prospective_fields:
            raise ValueError("prospective_authorization_failed manifest shape is invalid")
        return self


class _BootstrapReplayResult(_StrictModel):
    exit_code: Literal[1]
    error_code: BootstrapReplayError
    stdout_sha256: Sha256
    stderr_sha256: Sha256


class _BootstrapPhase(_StrictModel):
    tree: GitObjectId
    staged_diff_sha256: Sha256
    result: _BootstrapReplayResult


class _BootstrapManifestDelta(_StrictModel):
    path: RepositoryPath
    sha256: Sha256
    size: int = Field(gt=0)
    baseline_state: Literal["absent"]
    prospective_state: Literal["present_exact"]


class _BootstrapReplay(_StrictModel):
    base_commit: GitObjectId
    gate_path: RepositoryPath
    gate_sha256: Sha256
    baseline_snapshot: _BootstrapPhase
    prospective_candidate: _BootstrapPhase
    manifest_delta: _BootstrapManifestDelta


class _BootstrapEventBinding(_StrictModel):
    ordinal: Literal[1]
    raw_sha256: Sha256
    full_fence_sha256: Sha256
    prefix_event_count: Literal[0]
    prefix_sha256: Sha256


class _BootstrapPredecessor(_StrictModel):
    path: RepositoryPath
    iteration_id: IterationId
    sha256: Sha256
    size: int = Field(gt=0)
    event: _BootstrapEventBinding


class _BootstrapSuccessor(_StrictModel):
    iteration_id: IterationId
    single_successor: Literal[True]


class _BootstrapLineage(_StrictModel):
    root_request_sha256: Sha256
    acceptance_sha256: Sha256


class _BootstrapPlannedBlob(_StrictModel):
    path: RepositoryPath
    baseline_state: Literal["present", "absent"]
    planned_sha256: Sha256
    planned_size: int = Field(gt=0)


class _BootstrapEnvelope(_StrictModel):
    path: RepositoryPath
    baseline_state: Literal["absent"]
    canonicalization: Literal["compact_json_sorted_ascii_lf_v1"]


class _BootstrapScope(_StrictModel):
    allowed_paths: list[RepositoryPath] = Field(min_length=1)
    forbidden_authority: list[BootstrapAuthority] = Field(min_length=1)


class _BootstrapCore(_StrictModel):
    schema_version: Literal[1]
    failure_code: BootstrapFailureCode
    predecessor: _BootstrapPredecessor
    successor: _BootstrapSuccessor
    lineage: _BootstrapLineage
    replay: _BootstrapReplay
    planned_blobs: list[_BootstrapPlannedBlob] = Field(min_length=1)
    control_envelope: _BootstrapEnvelope
    scope: _BootstrapScope


class _BootstrapApproval(_StrictModel):
    role: Literal["librarian", "validator"]
    decision: Literal["approved"]
    control_core_sha256: Sha256
    decision_sha256: Sha256


class _BootstrapRecord(_StrictModel):
    schema_version: Literal[1]
    control_type: Literal["quarantine_bootstrap_repair"]
    core: _BootstrapCore
    approvals: list[_BootstrapApproval] = Field(min_length=2, max_length=2)


class _Event(_StrictModel):
    iteration_id: str
    state: State
    evidence: _Baseline | _Design | _Red | _Implemented | _Candidate | _Reviewed | _Verified | _Committed | _Closed | _Superseded


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
    _CLOSURE_CLAIMS: ClassVar[frozenset[str]] = frozenset(
        {
            "acceptance_reconciliation",
            "commit_binding",
            "memory_reconciliation",
            "process_cleanup",
            "verification_evidence",
        }
    )
    _BOOTSTRAP_REPLAY_STDERR: ClassVar[dict[BootstrapReplayError, bytes]] = {
        "ordinary_baseline_schema_unsupported": (
            b"[repository-gate] FAIL: BASELINED evidence contains unsupported fields\n"
        ),
        "recovery_baseline_chain_invalid": (
            b"[repository-gate] FAIL: recovery BASELINED chain is invalid\n"
        ),
    }
    _BOOTSTRAP_FORBIDDEN_AUTHORITY: ClassVar[tuple[BootstrapAuthority, ...]] = (
        "workflow_event",
        "product_source",
        "candidate",
        "review",
        "verification",
        "commit",
        "closure",
    )
    _MIGRATIONS: ClassVar[tuple[_MigrationRecord, ...]] = (
        _MigrationRecord(
            raw_sha256="0fde8406dffad9517285681d7992bc294f55dd4e91d197ea483540b8a3076d60",
            iteration_id="20260827-workflow-gates",
            ordinal=31,
            preceding_closed_commit="723624d4a2a24a4c340d6667f06518fd983ca3c0",
            contradicted_claim="commit_binding",
            recovery="RED",
        ),
    )
    _REVIEWER_MIGRATIONS: ClassVar[tuple[_ReviewerMigrationRecord, ...]] = (
        _ReviewerMigrationRecord(
            raw_sha256="105b66cb076bb4f7faa7639b24aedf8eb2368a922670dcad579729f79d40be80",
            iteration_id="20260827-workflow-gates",
            event_ordinal=27,
            reviewer_index=0,
            preceding_candidate_tree="660f50f49f1bb16b9f918f9f280e6fa75e4eaa56",
            preceding_commit=None,
            reviewer="security",
        ),
        _ReviewerMigrationRecord(
            raw_sha256="6ed1a5652f8b4f9a2eb463425387e5a7c82d77f027bfc02b41090cfa79536449",
            iteration_id="20260827-workflow-gates",
            event_ordinal=27,
            reviewer_index=1,
            preceding_candidate_tree="660f50f49f1bb16b9f918f9f280e6fa75e4eaa56",
            preceding_commit=None,
            reviewer="quality",
        ),
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
        "SUPERSEDED": _Superseded,
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
    _EVENT_PATTERN = re.compile(
        r"^```workflow-event[ \t]*$\n(.*?)\n^```[ \t]*(?:\n|\Z)",
        re.MULTILINE | re.DOTALL,
    )

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
            if display_path.startswith(".github/memory/iterations/"):
                raise _GateError("private workflow ledgers must not be staged")
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
        recoveries = self._validate_quarantines()
        path = self._active_ledger(recoveries) if ledger is None else self._explicit_ledger(ledger)
        predecessors = {
            manifest.predecessor_iteration_id
            for recovery in recoveries.values()
            for manifest in recovery
        }
        if path.stem in predecessors:
            raise _GateError("quarantined predecessor remains structurally invalid")
        events = self._parse_events(path, recoveries.get(path.stem))
        self._validate_sequence(events)
        self._validate_bindings(events)
        return events[-1].state

    def validate_append(self, ledger: Path, event: Path) -> State | None:
        recoveries = self._validate_quarantines()
        path = self._explicit_ledger(ledger)
        predecessors = {
            manifest.predecessor_iteration_id
            for recovery in recoveries.values()
            for manifest in recovery
        }
        if path.stem in predecessors:
            raise _GateError("quarantined predecessor remains structurally invalid")
        recovery = recoveries.get(path.stem)
        metadata = path.lstat()
        prefix_bytes = self._read_stable_file(path, metadata, "ledger")
        try:
            prefix_text = prefix_bytes.decode("utf-8")
        except UnicodeError as error:
            raise _GateError("ledger is unreadable") from error
        empty_prefixes = {"", f"# Iteration {path.stem}"}
        events = (
            []
            if "```workflow-event" not in prefix_text
            and prefix_text.strip() in empty_prefixes
            else self._parse_events(path, recovery)
        )
        expected_state: State | None = "BASELINED"
        if events:
            expected_state = self._validate_sequence(events)
            self._validate_bindings(events)
        proposed = self._decode_event_blocks(
            [self._read_proposed_event(event)],
            path.stem,
            recovery,
        )[0]
        combined = [*events, proposed]
        try:
            next_state = self._validate_sequence(combined)
        except _GateError as error:
            if str(error) == "ledger state order is invalid" and expected_state is not None:
                raise _GateError(
                    f"proposed event state is invalid; expected {expected_state}"
                ) from error
            raise
        self._validate_bindings(combined)
        if self._read_stable_file(path, metadata, "ledger") != prefix_bytes:
            raise _GateError("ledger changed during prospective validation")
        return next_state

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

    def _active_ledger(
        self,
        recoveries: dict[str, tuple[_QuarantineManifest, ...]],
    ):
        directory = self._policy_directory(required=False)
        active: list[Path] = []
        predecessors = {
            manifest.predecessor_iteration_id
            for recovery in recoveries.values()
            for manifest in recovery
        }
        if directory is not None:
            for path in sorted(directory.glob("*.md")):
                if path.is_symlink() or not path.is_file():
                    continue
                if path.stem in predecessors:
                    continue
                events = self._parse_events(path, recoveries.get(path.stem))
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

    def _read_proposed_event(self, event: Path) -> str:
        candidate = event if event.is_absolute() else self.root / event
        try:
            metadata = candidate.lstat()
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.root)
        except (OSError, ValueError) as error:
            raise _GateError("proposed event must be contained in the repository") from error
        if (
            resolved != candidate.absolute()
            or stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
        ):
            raise _GateError("proposed event must be a regular non-symlink file")
        try:
            return self._read_stable_file(candidate, metadata, "proposed event").decode("utf-8")
        except UnicodeError as error:
            raise _GateError("proposed event is unreadable") from error

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

    def _parse_events(
        self,
        path: Path,
        recovery: tuple[_QuarantineManifest, ...] | None = None,
    ):
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
        for index, match in enumerate(matches):
            try:
                envelope = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if not isinstance(envelope, dict) or envelope.get("state") != "CLOSED":
                continue
            boundary = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            following_state: object = None
            if index + 1 < len(matches):
                try:
                    following = json.loads(matches[index + 1].group(1))
                except json.JSONDecodeError:
                    following = None
                following_state = following.get("state") if isinstance(following, dict) else None
            if text[match.end() : boundary].strip() or (
                index + 1 < len(matches) and following_state != "SUPERSEDED"
            ):
                raise _GateError("CLOSED event must be terminal")
        events = self._decode_event_blocks(
            [match.group(1) for match in matches],
            path.stem,
            recovery,
        )
        for index, (match, item) in enumerate(zip(matches, events, strict=True)):
            if item.state != "CLOSED":
                continue
            boundary = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            if text[match.end() : boundary].strip():
                raise _GateError("CLOSED event must be terminal")
            if index + 1 < len(events) and events[index + 1].state != "SUPERSEDED":
                raise _GateError("CLOSED event must be terminal")
        return events

    def _decode_event_blocks(
        self,
        blocks: list[str],
        expected_id: str,
        recovery: tuple[_QuarantineManifest, ...] | None,
    ):
        events: list[_Event] = []
        for index, source_block in enumerate(blocks):
            block = source_block
            block = self._migrate_reviewers(block, index + 1, events)
            migration = next(
                (
                    record
                    for record in self._MIGRATIONS
                    if record.raw_sha256 == hashlib.sha256(block.encode()).hexdigest()
                ),
                None,
            )
            if migration is not None:
                preceding_commit = next(
                    (
                        event.evidence.commit
                        for event in reversed(events)
                        if isinstance(event.evidence, _Committed)
                    ),
                    None,
                )
                if (
                    index + 1 != migration.ordinal
                    or preceding_commit != migration.preceding_closed_commit
                ):
                    raise _GateError("legacy workflow event migration binding is invalid")
                block = json.dumps(
                    {
                        "iteration_id": migration.iteration_id,
                        "state": "SUPERSEDED",
                        "evidence": {
                            "schema_version": 1,
                            "closed_commit": migration.preceding_closed_commit,
                            "contradicted_claim": migration.contradicted_claim,
                            "recovery": migration.recovery,
                        },
                    }
                )
            try:
                raw = _RawEvent.model_validate_json(block)
            except ValidationError as error:
                raise _GateError("ledger event envelope is malformed") from error
            evidence_type = self._EVIDENCE_TYPES[raw.state]
            try:
                evidence = (
                    self._recovery_evidence(raw.state, raw.evidence, recovery)
                    if recovery is not None and raw.state in {"BASELINED", "DESIGNED", "RED"}
                    else evidence_type.model_validate(raw.evidence)
                )
                events.append(_Event(iteration_id=raw.iteration_id, state=raw.state, evidence=evidence))
            except ValidationError as error:
                raise _GateError(self._safe_validation_message(raw.state, evidence_type, error)) from error
            except ValueError as error:
                raise _GateError("ledger event evidence is malformed") from error
        if any(item.iteration_id != expected_id for item in events):
            raise _GateError("ledger filename and iteration id differ")
        return events

    def _validate_quarantines(self) -> dict[str, tuple[_QuarantineManifest, ...]]:
        listed = self._git(b"ls-files", b"-z", b"--", b".github/iteration-quarantine/*.json")
        assert listed is not None
        encoded_paths = listed.rstrip(b"\0").split(b"\0") if listed else []
        if not encoded_paths:
            return {}
        gate_blob = self._blob(b":./scripts/repository_gate.py")
        if gate_blob is None or gate_blob != Path(__file__).read_bytes():
            raise _GateError("executing gate differs from candidate index")
        indexed: dict[str, tuple[bytes, bytes, _QuarantineManifest]] = {}
        for encoded in encoded_paths:
            blob = self._blob(b":./" + encoded)
            if blob is None:
                raise _GateError("quarantine manifest must be available from the candidate index")
            committed_blob = self._blob(b"HEAD:" + encoded)
            if committed_blob is not None and committed_blob != blob:
                raise _GateError("committed quarantine manifest is immutable")
            try:
                manifest = _QuarantineManifest.model_validate_json(blob)
            except ValidationError as error:
                raise _GateError("quarantine manifest is malformed") from error
            path = os.fsdecode(encoded)
            expected = f".github/iteration-quarantine/{manifest.predecessor_sha256}.json"
            if path != expected or manifest.predecessor_iteration_id in indexed:
                raise _GateError("quarantine manifest binding is invalid")
            expected_predecessor = (
                f".github/memory/iterations/{manifest.predecessor_iteration_id}.md"
            )
            if manifest.predecessor_path != expected_predecessor:
                raise _GateError("quarantine predecessor path is invalid")
            indexed[manifest.predecessor_iteration_id] = (encoded, blob, manifest)
        ordered = self._ordered_quarantine_chain(
            [item[2] for item in indexed.values()]
        )
        recoveries: dict[str, tuple[_QuarantineManifest, ...]] = {}
        prefix: list[_QuarantineManifest] = []
        for manifest in ordered:
            encoded, blob, _ = indexed[manifest.predecessor_iteration_id]
            self._validate_quarantine_predecessor(
                encoded,
                blob,
                manifest,
                tuple(prefix),
                gate_blob,
            )
            prefix.append(manifest)
            recoveries[manifest.successor_iteration_id] = tuple(prefix)
        return recoveries

    @staticmethod
    def _ordered_quarantine_chain(
        manifests: list[_QuarantineManifest],
    ) -> tuple[_QuarantineManifest, ...]:
        predecessors = {manifest.predecessor_iteration_id for manifest in manifests}
        successors = {manifest.successor_iteration_id for manifest in manifests}
        if (
            len(predecessors) != len(manifests)
            or len(successors) != len(manifests)
            or any(
                manifest.predecessor_iteration_id == manifest.successor_iteration_id
                for manifest in manifests
            )
            or len({manifest.acceptance_sha256 for manifest in manifests}) != 1
        ):
            raise _GateError("quarantine lineage is invalid")
        roots = predecessors - successors
        terminals = successors - predecessors
        if len(roots) != 1 or len(terminals) != 1:
            raise _GateError("quarantine lineage is invalid")
        by_predecessor = {
            manifest.predecessor_iteration_id: manifest for manifest in manifests
        }
        ordered: list[_QuarantineManifest] = []
        cursor = next(iter(roots))
        while cursor in by_predecessor:
            manifest = by_predecessor[cursor]
            ordered.append(manifest)
            cursor = manifest.successor_iteration_id
            if len(ordered) > len(manifests):
                raise _GateError("quarantine lineage is invalid")
        if len(ordered) != len(manifests) or cursor not in terminals:
            raise _GateError("quarantine lineage is invalid")
        root_request_sha256 = RepositoryGate._manifest_request_sha256(ordered[0])
        if any(
            RepositoryGate._manifest_request_sha256(manifest) != root_request_sha256
            for manifest in ordered
        ):
            raise _GateError("quarantine lineage request is invalid")
        return tuple(ordered)

    @staticmethod
    def _manifest_request_sha256(manifest: _QuarantineManifest) -> str:
        if manifest.request is not None:
            return hashlib.sha256(manifest.request.encode()).hexdigest()
        if manifest.request_sha256 is None:
            raise _GateError("quarantine lineage request is invalid")
        return manifest.request_sha256

    def _validate_quarantine_predecessor(
        self,
        encoded: bytes,
        blob: bytes,
        manifest: _QuarantineManifest,
        incoming: tuple[_QuarantineManifest, ...],
        gate_blob: bytes,
    ) -> None:
        predecessor = self.root / manifest.predecessor_path
        try:
            metadata = predecessor.lstat()
        except FileNotFoundError:
            head_manifest = self._blob(b"HEAD:" + encoded)
            head_gate = self._blob(b"HEAD:scripts/repository_gate.py")
            if head_manifest != blob or head_gate != gate_blob:
                raise _GateError("private quarantine predecessor is required before commit")
            return
        except OSError as error:
            raise _GateError("quarantine predecessor is unreadable") from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise _GateError("quarantine predecessor must be a regular non-symlink")
        raw = self._read_stable_file(predecessor, metadata, "quarantine predecessor")
        if (
            len(raw) != manifest.predecessor_size
            or hashlib.sha256(raw).hexdigest() != manifest.predecessor_sha256
        ):
            raise _GateError("quarantine predecessor binding is invalid")
        try:
            text = raw.decode("utf-8")
        except UnicodeError as error:
            raise _GateError("quarantine predecessor is unreadable") from error
        matches = list(self._EVENT_PATTERN.finditer(text))
        if not matches or text.count("```workflow-event") != len(matches):
            raise _GateError("quarantine predecessor event boundaries are invalid")
        ordinal = manifest.failing_event_ordinal
        if ordinal > len(matches):
            raise _GateError("quarantine failure ordinal is invalid")
        failing_match = matches[ordinal - 1]
        block = failing_match.group(1)
        if (
            hashlib.sha256((block + "\n").encode()).hexdigest()
            != manifest.failing_raw_block_sha256
        ):
            raise _GateError("quarantine failing block binding is invalid")
        prefix_matches = matches[: ordinal - 1]
        canonical_prefix = "".join(match.group(0) for match in prefix_matches).encode()
        if (
            len(prefix_matches) != manifest.trusted_prefix_event_count
            or hashlib.sha256(canonical_prefix).hexdigest()
            != manifest.trusted_prefix_sha256
        ):
            raise _GateError("quarantine trusted prefix binding is invalid")
        try:
            baseline = _RawEvent.model_validate_json(matches[0].group(1))
            failing = _RawEvent.model_validate_json(block)
        except ValidationError as error:
            raise _GateError("quarantine structural reproduction is invalid") from error
        if (
            baseline.iteration_id != manifest.predecessor_iteration_id
            or baseline.state != "BASELINED"
            or failing.iteration_id != manifest.predecessor_iteration_id
        ):
            raise _GateError("quarantine structural reproduction is invalid")
        acceptance_sha = hashlib.sha256(
            json.dumps(
                baseline.evidence.get("acceptance"),
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode()
        ).hexdigest()
        request = baseline.evidence.get("request")
        actual_request_sha256 = (
            hashlib.sha256(request.encode()).hexdigest()
            if isinstance(request, str)
            else None
        )
        lineage = (*incoming, manifest)
        root_manifest = lineage[0]
        root_request_sha256 = self._manifest_request_sha256(root_manifest)
        if manifest.parser_failure_code == "reviewed_commands_missing":
            request_matches = (
                request == manifest.request
                and actual_request_sha256 == root_request_sha256
            )
        elif manifest.parser_failure_code == "recovery_request_mismatch":
            request_matches = (
                bool(incoming)
                and manifest.request_sha256 == root_request_sha256
                and actual_request_sha256 == manifest.actual_request_sha256
                and actual_request_sha256 != root_request_sha256
            )
        else:
            request_matches = (
                manifest.request_sha256 == root_request_sha256
                and actual_request_sha256 == root_request_sha256
            )
        if (
            not request_matches
            or acceptance_sha != manifest.acceptance_sha256
            or manifest.acceptance_sha256 != root_manifest.acceptance_sha256
            or baseline.evidence.get("head") != manifest.base_head
        ):
            raise _GateError("quarantine request or acceptance binding is invalid")
        prefix_events = (
            self._decode_event_blocks(
                [match.group(1) for match in prefix_matches],
                manifest.predecessor_iteration_id,
                incoming or None,
            )
            if prefix_matches
            else []
        )
        if prefix_events:
            expected_state = self._validate_sequence(prefix_events)
            self._validate_bindings(prefix_events, bind_current_candidate=False)
        else:
            expected_state = "BASELINED"
        self._validate_quarantine_failure(
            manifest,
            failing,
            prefix_events,
            expected_state,
            text,
            matches,
            incoming,
        )

    def _validate_quarantine_failure(
        self,
        manifest: _QuarantineManifest,
        failing: _RawEvent,
        prefix_events: list[_Event],
        expected_state: State | None,
        text: str,
        matches: list[re.Match[str]],
        incoming: tuple[_QuarantineManifest, ...],
    ) -> None:
        if manifest.parser_failure_code == "reviewed_commands_missing":
            if failing.state != "REVIEWED" or expected_state != "REVIEWED":
                raise _GateError("quarantine parser failure code is invalid")
            try:
                _Reviewed.model_validate(failing.evidence)
            except ValidationError as error:
                if not any(
                    item["loc"] and item["loc"][-1] == "commands"
                    for item in error.errors()
                ):
                    raise _GateError("quarantine parser failure code is invalid") from error
                return
            raise _GateError("valid ledger is ineligible for quarantine")
        ordinal = manifest.failing_event_ordinal
        failing_match = matches[ordinal - 1]
        separator_end = failing_match.end() + int(text[failing_match.end() :].startswith("\n"))
        full_fence = text[failing_match.start() : separator_end].encode()
        if hashlib.sha256(full_fence).hexdigest() != manifest.failing_full_fence_sha256:
            raise _GateError("quarantine failing fence binding is invalid")
        if manifest.parser_failure_code == "recovery_request_mismatch":
            if failing.state != "BASELINED" or expected_state != "BASELINED" or not incoming:
                raise _GateError("quarantine parser failure code is invalid")
            try:
                self._recovery_evidence(
                    "BASELINED",
                    failing.evidence,
                    incoming,
                )
            except _GateError as error:
                if str(error) == "recovery BASELINED request binding is invalid":
                    return
                raise _GateError("quarantine structural reproduction is invalid") from error
            raise _GateError("valid ledger is ineligible for quarantine")
        if manifest.parser_failure_code == "prospective_authorization_failed":
            if (
                failing.state != "BASELINED"
                or expected_state != "BASELINED"
                or prefix_events
            ):
                raise _GateError("quarantine parser failure code is invalid")
            event_raw = (failing_match.group(1) + "\n").encode()
            self._validate_bootstrap_manifest_control(
                manifest, event_raw, full_fence
            )
            return
        if (
            manifest.parser_failure_code != "invalid_state_transition"
            or failing.state != manifest.actual_state
            or expected_state != manifest.expected_state
        ):
            raise _GateError("quarantine parser failure code is invalid")
        try:
            decoded = self._decode_event_blocks(
                [matches[ordinal - 1].group(1)],
                manifest.predecessor_iteration_id,
                incoming or None,
            )
            self._validate_sequence([*prefix_events, *decoded])
        except _GateError as error:
            if str(error) == "ledger state order is invalid":
                return
            raise _GateError("quarantine structural reproduction is invalid") from error
        raise _GateError("valid ledger is ineligible for quarantine")

    def _recovery_evidence(
        self,
        state: State,
        evidence: dict[str, Any],
        recovery: tuple[_QuarantineManifest, ...],
    ) -> _Baseline | _Design | _Red:
        if state == "BASELINED":
            self._validate_recovery_baseline(evidence, recovery)
            return _Baseline(
                request=evidence["request"], acceptance=evidence["acceptance"],
                branch=evidence["branch"], head=evidence["head"], status=evidence["status"],
                unstaged_diff_sha256=evidence["unstaged_diff_sha256"],
                staged_diff_sha256=evidence["staged_diff_sha256"],
                untracked_checksums=evidence["untracked_checksums"],
                protected_paths=evidence["protected_paths"], overlap="quarantine successor",
            )
        if state == "DESIGNED":
            return _Design(
                interpretation=evidence["interpretation"], non_goals=evidence["non_goals"],
                owners=["successor implementation lead"], interfaces=evidence["source_of_truth"],
                invariants=evidence["invariants"], edge_cases=evidence["quarantine"]["abuse_negatives"],
                trust_boundaries=evidence["quarantine"]["strict_semantics"], tests=evidence["tests"],
                negative_controls=evidence["failure_behavior"], cost="no paid or network calls",
                visual_route="isolated installed extension host", compatibility=evidence["compatibility"],
            )
        commands = evidence.get("commands")
        if not isinstance(commands, list) or not commands:
            raise _GateError("recovery RED commands are malformed")
        command = commands[0]
        return _Red.model_validate({**command, "failing_assertion": command["failing_assertion"]})

    def _validate_recovery_baseline(
        self,
        evidence: dict[str, Any],
        recovery: tuple[_QuarantineManifest, ...],
    ) -> None:
        manifest = recovery[-1]
        acceptance = evidence.get("acceptance")
        acceptance_sha = hashlib.sha256(
            json.dumps(acceptance, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()
        request = evidence.get("request")
        root_request_sha256 = self._manifest_request_sha256(recovery[0])
        if (
            not isinstance(request, str)
            or hashlib.sha256(request.encode()).hexdigest() != root_request_sha256
        ):
            raise _GateError("recovery BASELINED request binding is invalid")
        if (
            evidence.get("schema_version") != 1
            or evidence.get("acceptance_sha256") != manifest.acceptance_sha256
            or acceptance_sha != manifest.acceptance_sha256
            or evidence.get("head") != manifest.base_head
        ):
            raise _GateError("recovery BASELINED binding is invalid")
        self._validate_recovery_context(evidence, recovery)

    def _validate_recovery_context(
        self,
        evidence: dict[str, Any],
        recovery: tuple[_QuarantineManifest, ...],
    ) -> None:
        expected_fields = {
            "schema_version", "recovery_chain_version", "request", "acceptance_sha256",
            "acceptance", "branch", "head", "status", "unstaged_diff_sha256",
            "staged_diff_sha256", "index_path_count", "untracked_checksums",
            "protected_paths", "protected_aggregate_sha256", "ownership", "overlap",
            "recovery_chain", "lineage_constraints", "successor_authority",
            "cleared_context",
        }
        raw_chain = evidence.get("recovery_chain")
        lineage = evidence.get("lineage_constraints")
        cleared = evidence.get("cleared_context")
        ownership = evidence.get("ownership")
        authority = evidence.get("successor_authority")
        if (
            set(evidence) != expected_fields
            or evidence.get("recovery_chain_version") != 2
            or not isinstance(evidence.get("index_path_count"), int)
            or evidence.get("index_path_count") < 0
            or not isinstance(evidence.get("staged_diff_sha256"), str)
            or not isinstance(raw_chain, list)
            or len(raw_chain) != len(recovery)
            or not isinstance(lineage, dict)
            or not isinstance(cleared, list)
            or not isinstance(ownership, dict)
            or not isinstance(authority, dict)
        ):
            raise _GateError("recovery BASELINED chain is invalid")
        expected_order = [recovery[0].predecessor_iteration_id, *(
            manifest.successor_iteration_id for manifest in recovery
        )]
        if (
            set(lineage) != {
                "edge_order", "same_request", "same_acceptance", "same_acceptance_order",
                "forks", "cycles", "dangling_edges", "skipped_edges",
            }
            or lineage.get("edge_order") != expected_order
            or lineage.get("same_request") is not True
            or lineage.get("same_acceptance") is not True
            or lineage.get("same_acceptance_order") is not True
            or any(
                lineage.get(field) is not False
                for field in ("forks", "cycles", "dangling_edges", "skipped_edges")
            )
            or cleared != [
                "design", "red", "implementation", "candidate", "review",
                "verification", "commit", "closure", "approval",
            ]
            or set(ownership) != {
                "pre_existing_user_work", "inherited_agent_residue_modified_paths",
                "inherited_agent_residue_untracked", "residue_authority", "index",
            }
            or ownership.get("residue_authority") != "none"
            or set(authority) != {
                "domain_owner", "decision", "recovery_mode",
                "independent_validator_required", "user_confirmation_required",
                "predecessor_bytes_must_remain_exact",
            }
            or authority != {
                "domain_owner": "librarian",
                "decision": "authorized",
                "recovery_mode": "exact_non_destructive",
                "independent_validator_required": True,
                "user_confirmation_required": False,
                "predecessor_bytes_must_remain_exact": True,
            }
        ):
            raise _GateError("recovery BASELINED context is invalid")
        index = ownership.get("index")
        empty_index = (
            index == "empty"
            and evidence["index_path_count"] == 0
            and evidence["staged_diff_sha256"] == hashlib.sha256(b"").hexdigest()
        )
        captured_index = (
            isinstance(index, dict)
            and set(index) == {"authority", "path_count", "tree", "staged_diff_sha256", "paths"}
            and index.get("authority") == "none"
            and index.get("path_count") == evidence["index_path_count"]
            and index.get("staged_diff_sha256") == evidence["staged_diff_sha256"]
            and isinstance(index.get("tree"), str)
            and re.fullmatch(r"[0-9a-f]{40}", index["tree"]) is not None
            and isinstance(index.get("paths"), list)
            and len(index["paths"]) == index["path_count"]
            and index["paths"] == sorted(set(index["paths"]))
        )
        if not empty_index and not captured_index:
            raise _GateError("recovery BASELINED context is invalid")
        for raw, manifest in zip(raw_chain, recovery, strict=True):
            self._validate_recovery_chain_item(raw, manifest)

    def _validate_recovery_chain_item(
        self,
        raw: Any,
        manifest: _QuarantineManifest,
    ) -> None:
        if not isinstance(raw, dict):
            raise _GateError("recovery BASELINED chain is invalid")
        expected_fields = {
            "manifest_path", "manifest_state_at_baseline",
            "manifest_sha256_at_baseline", "manifest_sha256_planned",
            "predecessor_path",
            "predecessor_iteration_id", "predecessor_sha256", "predecessor_size",
            "base_head", "parser_failure_code", "failing_event_ordinal",
            "failing_raw_block_sha256", "failing_full_fence_sha256",
            "trusted_prefix_event_count", "trusted_prefix_sha256",
            "request_sha256", "actual_request_sha256", "acceptance_sha256",
            "successor_iteration_id",
        }
        request_sha256 = self._manifest_request_sha256(manifest)
        actual_request_sha256 = manifest.actual_request_sha256 or request_sha256
        manifest_path = f".github/iteration-quarantine/{manifest.predecessor_sha256}.json"
        manifest_blob = self._blob(b":./" + os.fsencode(manifest_path))
        if manifest_blob is None:
            raise _GateError("recovery BASELINED planned manifest is invalid")
        expected = {
            "manifest_path": manifest_path,
            "predecessor_path": manifest.predecessor_path,
            "predecessor_iteration_id": manifest.predecessor_iteration_id,
            "predecessor_sha256": manifest.predecessor_sha256,
            "predecessor_size": manifest.predecessor_size,
            "base_head": manifest.base_head,
            "parser_failure_code": manifest.parser_failure_code,
            "failing_event_ordinal": manifest.failing_event_ordinal,
            "failing_raw_block_sha256": manifest.failing_raw_block_sha256,
            "failing_full_fence_sha256": manifest.failing_full_fence_sha256,
            "trusted_prefix_event_count": manifest.trusted_prefix_event_count,
            "trusted_prefix_sha256": manifest.trusted_prefix_sha256,
            "request_sha256": request_sha256,
            "actual_request_sha256": actual_request_sha256,
            "acceptance_sha256": manifest.acceptance_sha256,
            "successor_iteration_id": manifest.successor_iteration_id,
        }
        if manifest.parser_failure_code == "invalid_state_transition":
            expected_fields.update(
                {"manifest_size_planned", "actual_state", "expected_state"}
            )
            expected.update(
                {
                    "manifest_size_planned": len(manifest_blob),
                    "actual_state": manifest.actual_state,
                    "expected_state": manifest.expected_state,
                }
            )
        elif manifest.parser_failure_code == "prospective_authorization_failed":
            expected_fields.update(
                {
                    "manifest_size_planned",
                    "baseline_snapshot_tree", "baseline_snapshot_stderr_sha256",
                    "prospective_candidate_tree", "prospective_candidate_stderr_sha256",
                    "prospective_gate_sha256",
                }
            )
            expected.update(
                {
                    "baseline_snapshot_tree": manifest.baseline_snapshot_tree,
                    "baseline_snapshot_stderr_sha256": manifest.baseline_snapshot_stderr_sha256,
                    "prospective_candidate_tree": manifest.prospective_candidate_tree,
                    "prospective_candidate_stderr_sha256": manifest.prospective_candidate_stderr_sha256,
                    "prospective_gate_sha256": manifest.prospective_gate_sha256,
                    "manifest_size_planned": len(manifest_blob),
                }
            )
        if set(raw) != expected_fields or any(
            raw.get(key) != value for key, value in expected.items()
        ):
            raise _GateError("recovery BASELINED chain is invalid")
        planned_sha256 = raw.get("manifest_sha256_planned")
        if (
            not isinstance(planned_sha256, str)
            or hashlib.sha256(manifest_blob).hexdigest() != planned_sha256
        ):
            raise _GateError("recovery BASELINED planned manifest is invalid")
        state = raw.get("manifest_state_at_baseline")
        baseline_sha256 = raw.get("manifest_sha256_at_baseline")
        valid_baseline = (
            state == "present_untracked_exact_no_authority"
            and baseline_sha256 == planned_sha256
        ) or (
            state == "present_untracked_invalid_no_authority"
            and isinstance(baseline_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", baseline_sha256) is not None
            and baseline_sha256 != planned_sha256
        ) or (
            state == "absent_before_recovery_edit"
            and baseline_sha256 is None
        ) or (
            state == "present_in_candidate_index_exact_no_authority"
            and baseline_sha256 == planned_sha256
        )
        if not valid_baseline:
            raise _GateError("recovery BASELINED chain is invalid")

    def _migrate_reviewers(self, block: str, event_ordinal: int, events: list[_Event]):
        try:
            envelope = json.loads(block)
        except json.JSONDecodeError:
            return block
        evidence = envelope.get("evidence") if isinstance(envelope, dict) else None
        reviewers = evidence.get("reviewers") if isinstance(evidence, dict) else None
        if not isinstance(envelope, dict) or envelope.get("state") != "REVIEWED" or not isinstance(reviewers, list):
            return block
        if all(isinstance(reviewer, dict) and reviewer.get("schema_version") == 1 for reviewer in reviewers):
            return block
        marker = '"reviewers":['
        if marker not in block:
            raise _GateError("unversioned reviewer evidence has no migration")
        candidate = next(
            (event.evidence for event in reversed(events) if isinstance(event.evidence, _Candidate)),
            None,
        )
        preceding_commit = next(
            (event.evidence.commit for event in reversed(events) if isinstance(event.evidence, _Committed)),
            None,
        )
        decoder = json.JSONDecoder()
        position = block.index(marker) + len(marker)
        replacements: list[tuple[int, int, str]] = []
        for reviewer_index in range(len(reviewers)):
            raw_reviewer, end = decoder.raw_decode(block, position)
            exact = block[position:end]
            if not isinstance(raw_reviewer, dict) or raw_reviewer.get("schema_version") != 1:
                digest = hashlib.sha256(exact.encode()).hexdigest()
                migration = next(
                    (
                        record
                        for record in self._REVIEWER_MIGRATIONS
                        if record.raw_sha256 == digest
                    ),
                    None,
                )
                if (
                    migration is None
                    or migration.iteration_id != envelope.get("iteration_id")
                    or migration.event_ordinal != event_ordinal
                    or migration.reviewer_index != reviewer_index
                    or candidate is None
                    or migration.preceding_candidate_tree != candidate.tree
                    or migration.preceding_commit != preceding_commit
                    or migration.reviewer != raw_reviewer.get("reviewer")
                ):
                    raise _GateError("unversioned reviewer evidence has no migration")
                raw_reviewer["schema_version"] = 1
                raw_reviewer["findings"] = []
                replacements.append(
                    (position, end, json.dumps(raw_reviewer, separators=(",", ":")))
                )
            position = end + (1 if end < len(block) and block[end] == "," else 0)
        for start, end, replacement in reversed(replacements):
            block = block[:start] + replacement + block[end:]
        return block

    def _validate_sequence(self, events: list[_Event]) -> State | None:
        if not events:
            raise _GateError("ledger contains no workflow events")
        expected_index = 0
        candidate_seen = False
        remediation_red = False
        for item in events:
            if item.state == "SUPERSEDED":
                if expected_index != len(self._STATES):
                    raise _GateError("ledger state order is invalid")
                assert isinstance(item.evidence, _Superseded)
                expected_index = 1 if item.evidence.review is not None else 2
                candidate_seen = False
                remediation_red = False
                continue
            if expected_index == len(self._STATES):
                raise _GateError("ledger has content after CLOSED")
            if item.state == "RED" and (
                expected_index == 4 or candidate_seen and expected_index in {5, 6, 7}
            ):
                expected_index = 2
                candidate_seen = False
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
            elif item.state == "REVIEWED":
                assert isinstance(item.evidence, _Reviewed)
                if any(
                    reviewer.disposition != "approved"
                    for reviewer in item.evidence.reviewers
                ):
                    expected_index = 2
            elif remediation_red and item.state == "IMPLEMENTED":
                expected_index = 4
        if events[-1].state == "SUPERSEDED":
            raise _GateError("SUPERSEDED must be followed by recovery evidence")
        return None if expected_index == len(self._STATES) else self._STATES[expected_index]

    def _validate_bindings(
        self,
        events: list[_Event],
        *,
        bind_current_candidate: bool = True,
    ):
        candidate: _Candidate | None = None
        committed: _Committed | None = None
        baseline = events[0].evidence
        assert isinstance(baseline, _Baseline)
        acceptance_sha256 = hashlib.sha256(
            json.dumps(baseline.acceptance, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()
        memory_participants: set[str] = {"pm", "developer"}
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
                    memory_participants.add(reviewer.reviewer)
                    expected = (
                        "approved"
                        if reviewer.disposition == "approved"
                        else "nonapproved"
                    )
                    self._validate_review(reviewer, candidate, expected, "REVIEWED")
            elif item.state == "VERIFIED":
                assert isinstance(item.evidence, _Verified)
                self._require_candidate(candidate, item.evidence.candidate_tree, item.evidence.acceptance_sha256)
                if any(command.exit_code != 0 for command in item.evidence.commands):
                    raise _GateError("VERIFIED exit_code must be zero")
            elif item.state == "COMMITTED":
                assert isinstance(item.evidence, _Committed)
                self._validate_commit(candidate, item.evidence)
                committed = item.evidence
            elif item.state == "CLOSED":
                assert isinstance(item.evidence, _Closed)
                if set(item.evidence.acceptance) != set(baseline.acceptance):
                    raise _GateError("CLOSED acceptance does not reconcile with BASELINED acceptance")
                memory_participants.update(item.evidence.participants)
                self._validate_memories(
                    events[0].iteration_id, item.evidence, candidate, memory_participants
                )
            elif item.state == "RED":
                assert isinstance(item.evidence, _Red)
                if item.evidence.exit_code == 0:
                    raise _GateError("RED exit_code must be nonzero")
                candidate = None
            elif item.state == "SUPERSEDED":
                assert isinstance(item.evidence, _Superseded)
                if committed is None or item.evidence.closed_commit != committed.commit:
                    raise _GateError("SUPERSEDED event does not match closed commit")
                if (
                    item.evidence.contradicted_claim not in baseline.acceptance
                    and item.evidence.contradicted_claim not in self._CLOSURE_CLAIMS
                ):
                    raise _GateError("SUPERSEDED contradicted claim is not recognized")
                if item.evidence.review is not None:
                    review = item.evidence.review
                    memory_participants.add(review.reviewer)
                    if any(
                        finding.claim != item.evidence.contradicted_claim
                        for finding in review.findings
                    ):
                        raise _GateError("SUPERSEDED review finding does not match claim")
                    self._validate_review(review, candidate, "nonapproved", "SUPERSEDED")
                candidate = None
                committed = None
        if candidate is not None and bind_current_candidate:
            terminal = events[-1].state
            if terminal in {"COMMITTED", "CLOSED"}:
                if committed is None:
                    raise _GateError("active committed epoch is incomplete")
                current_index = self._git(b"write-tree")
                assert current_index is not None
                if current_index.decode().strip() != committed.tree:
                    raise _GateError("committed repository index must be clean")
                current_head = self._git(b"rev-parse", b"HEAD", allowed_failure=True)
                current_tree = self._git(b"rev-parse", b"HEAD^{tree}", allowed_failure=True)
                if current_head is None or current_tree is None:
                    raise _GateError("current HEAD must be a commit")
                if current_head.decode().strip() != committed.commit:
                    raise _GateError("current HEAD does not match recorded commit")
                if current_tree.decode().strip() != committed.tree:
                    raise _GateError("current HEAD tree does not match candidate tree")
            else:
                staged_diff = self._git(
                    b"diff",
                    b"--cached",
                    b"--binary",
                    b"--no-ext-diff",
                    b"--no-textconv",
                )
                assert staged_diff is not None
                current = self._git(b"write-tree")
                assert current is not None
                if current.decode().strip() != candidate.tree:
                    raise _GateError("candidate is stale")
                if hashlib.sha256(staged_diff).hexdigest() != candidate.staged_diff_sha256:
                    raise _GateError("candidate staged diff hash is stale")

    @staticmethod
    def _require_candidate(candidate: _Candidate | None, tree: str, acceptance_sha256: str):
        if candidate is None or tree != candidate.tree or acceptance_sha256 != candidate.acceptance_sha256:
            raise _GateError("review or verification does not match candidate")

    def _validate_review(
        self,
        review: _Reviewer,
        candidate: _Candidate | None,
        expected_disposition: Literal["approved", "nonapproved"],
        purpose: Literal["REVIEWED", "SUPERSEDED"],
    ):
        self._require_candidate(candidate, review.candidate_tree, review.acceptance_sha256)
        is_approved = review.disposition == "approved"
        if (expected_disposition == "approved") != is_approved:
            if purpose == "REVIEWED":
                raise _GateError("candidate is invalid and must be changed and re-frozen")
            raise _GateError("SUPERSEDED review must contradict the closure claim")
        if any(command.exit_code != 0 for command in review.commands):
            raise _GateError(f"{purpose} review command exit_code must be zero")

    def _validate_commit(self, candidate: _Candidate | None, committed: _Committed):
        if candidate is None or committed.candidate_tree != candidate.tree or committed.tree != candidate.tree:
            raise _GateError("commit tree does not match candidate tree")
        canonical_commit = self._git(
            b"rev-parse",
            b"--verify",
            os.fsencode(committed.commit + "^{commit}"),
            allowed_failure=True,
        )
        if canonical_commit is None or canonical_commit.decode().strip() != committed.commit:
            raise _GateError("recorded commit must be a canonical full object id")
        actual = self._git(
            b"rev-parse", os.fsencode(committed.commit + "^{tree}"), allowed_failure=True
        )
        if actual is None or actual.decode().strip() != committed.tree:
            raise _GateError("recorded commit tree does not match Git")
    def _validate_memories(
        self,
        iteration_id: str,
        closed: _Closed,
        candidate: _Candidate | None,
        required: set[str],
    ):
        prompt_paths = {"AGENTS.md", "CLAUDE.md", ".github/copilot-instructions.md"}
        if candidate is not None and prompt_paths.intersection(candidate.owned_paths):
            required.add("librarian")
        if set(closed.memory_markers) != required:
            raise _GateError("memory marker set does not match participants")
        if set(closed.participants) != required:
            raise _GateError("CLOSED participant set does not reconcile review identities")
        for participant in required:
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

    def validate_bootstrap(self, record_path: Path, ledger: Path):
        candidate_tree_output = self._git(b"write-tree")
        assert candidate_tree_output is not None
        candidate_tree = candidate_tree_output.decode().strip()
        record_raw, record, record_metadata = self._bootstrap_record(
            record_path, candidate_tree
        )
        core = record.core
        core_sha256 = self._validate_bootstrap_approvals(record, record_raw)
        predecessor_path, predecessor_raw, event_raw, event_fence = (
            self._validate_bootstrap_predecessor(core, ledger, candidate_tree)
        )
        delta_manifest = self._validate_bootstrap_phases(core, event_raw)
        target_manifest = self._validate_bootstrap_candidate(
            core,
            record_raw,
            record_path,
            candidate_tree,
            core_sha256,
            delta_manifest,
        )
        self._validate_bootstrap_manifest_binding(
            core, target_manifest, event_raw, event_fence
        )
        self._validate_bootstrap_conflicts(core, candidate_tree)
        self._validate_bootstrap_unconsumed(core)
        old_gate = self._bootstrap_tree_blob(
            core.replay.baseline_snapshot.tree, core.replay.gate_path
        )
        assert old_gate is not None
        self._replay_bootstrap_phases(core, old_gate, event_raw, predecessor_path)
        if self._read_stable_file(record_path, record_metadata, "bootstrap control") != record_raw:
            raise _GateError("bootstrap control changed during validation")
        final_tree_output = self._git(b"write-tree")
        assert final_tree_output is not None
        if final_tree_output.decode().strip() != candidate_tree:
            raise _GateError("bootstrap candidate changed during validation")

    @staticmethod
    def _bootstrap_canonical(value: Any):
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode() + b"\n"

    @staticmethod
    def _bootstrap_sha256(value: bytes):
        return hashlib.sha256(value).hexdigest()

    @staticmethod
    def _validate_bootstrap_repository_path(path: str):
        parts = Path(path).parts
        if (
            not path
            or path.startswith("/")
            or "\\" in path
            or "\0" in path
            or not parts
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise _GateError("bootstrap path is invalid")

    def _bootstrap_record(
        self, record_path: Path, candidate_tree: str
    ) -> tuple[bytes, _BootstrapRecord, os.stat_result]:
        candidate = record_path if record_path.is_absolute() else self.root / record_path
        expected_parent = self.root / ".github" / "iteration-bootstrap"
        try:
            metadata = candidate.lstat()
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise _GateError("bootstrap control is unreadable") from error
        if (
            candidate.parent.absolute() != expected_parent.absolute()
            or resolved != candidate.absolute()
            or stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
        ):
            raise _GateError("bootstrap control path is invalid")
        raw = self._read_stable_file(candidate, metadata, "bootstrap control")
        try:
            decoded = json.loads(raw)
            record = _BootstrapRecord.model_validate(decoded)
        except (json.JSONDecodeError, ValidationError) as error:
            raise _GateError("bootstrap control schema is invalid") from error
        if raw != self._bootstrap_canonical(decoded):
            raise _GateError("bootstrap control is not canonical")
        core = record.core
        self._validate_bootstrap_repository_path(core.control_envelope.path)
        expected_path = (
            f".github/iteration-bootstrap/{core.predecessor.sha256}.json"
        )
        try:
            relative = str(candidate.relative_to(self.root))
        except ValueError as error:
            raise _GateError("bootstrap control path is invalid") from error
        if core.control_envelope.path != expected_path or relative != expected_path:
            raise _GateError("bootstrap control path is invalid")
        indexed = self._bootstrap_tree_blob(candidate_tree, relative)
        if indexed != raw:
            raise _GateError("bootstrap control differs from candidate index")
        return raw, record, metadata

    def _validate_bootstrap_approvals(
        self, record: _BootstrapRecord, record_raw: bytes
    ) -> str:
        core_raw = self._bootstrap_canonical(record.core.model_dump(mode="json"))
        core_sha256 = self._bootstrap_sha256(core_raw)
        expected: list[dict[str, str]] = []
        for role in ("librarian", "validator"):
            payload = {
                "role": role,
                "decision": "approved",
                "control_core_sha256": core_sha256,
            }
            expected.append(
                {
                    **payload,
                    "decision_sha256": self._bootstrap_sha256(
                        self._bootstrap_canonical(payload)
                    ),
                }
            )
        if [item.model_dump(mode="json") for item in record.approvals] != expected:
            raise _GateError("bootstrap approval is invalid")
        if core_sha256.encode() in core_raw:
            raise _GateError("bootstrap core is circular")
        record_sha256 = self._bootstrap_sha256(record_raw).encode()
        decision_hashes = [item.decision_sha256.encode() for item in record.approvals]
        if any(value in core_raw for value in [record_sha256, *decision_hashes]):
            raise _GateError("bootstrap approval is circular")
        return core_sha256

    def _validate_bootstrap_predecessor(
        self, core: _BootstrapCore, ledger: Path, candidate_tree: str
    ) -> tuple[Path, bytes, bytes, bytes]:
        predecessor = core.predecessor
        self._validate_bootstrap_repository_path(predecessor.path)
        expected_path = (
            f".github/memory/iterations/{predecessor.iteration_id}.md"
        )
        path = self._explicit_ledger(ledger)
        if predecessor.path != expected_path or path != self.root / expected_path:
            raise _GateError("bootstrap predecessor path is invalid")
        metadata = path.lstat()
        raw = self._read_stable_file(path, metadata, "bootstrap predecessor")
        if (
            len(raw) != predecessor.size
            or self._bootstrap_sha256(raw) != predecessor.sha256
            or self._bootstrap_tree_blob(candidate_tree, predecessor.path) is not None
        ):
            raise _GateError("bootstrap predecessor binding is invalid")
        try:
            text = raw.decode("utf-8")
        except UnicodeError as error:
            raise _GateError("bootstrap predecessor is unreadable") from error
        matches = list(self._EVENT_PATTERN.finditer(text))
        if len(matches) != 1 or text.count("```workflow-event") != 1:
            raise _GateError("bootstrap event boundary is invalid")
        match = matches[0]
        if (
            text[: match.start()].strip() != f"# Iteration {predecessor.iteration_id}"
            or text[match.end() :].strip()
        ):
            raise _GateError("bootstrap event boundary is invalid")
        event_raw = (match.group(1) + "\n").encode()
        event_fence = text[match.start() : match.end()].encode()
        event_binding = predecessor.event
        if (
            self._bootstrap_sha256(event_raw) != event_binding.raw_sha256
            or self._bootstrap_sha256(event_fence) != event_binding.full_fence_sha256
            or event_binding.prefix_sha256 != self._bootstrap_sha256(b"")
        ):
            raise _GateError("bootstrap event binding is invalid")
        try:
            event = _RawEvent.model_validate_json(event_raw)
        except ValidationError as error:
            raise _GateError("bootstrap event is malformed") from error
        request = event.evidence.get("request")
        acceptance = event.evidence.get("acceptance")
        if (
            event.iteration_id != predecessor.iteration_id
            or event.state != "BASELINED"
            or not isinstance(request, str)
            or not request.strip()
            or not isinstance(acceptance, list)
            or not acceptance
            or any(not isinstance(item, str) or not item.strip() for item in acceptance)
        ):
            raise _GateError("bootstrap lineage event is invalid")
        acceptance_sha256 = self._bootstrap_sha256(
            json.dumps(acceptance, separators=(",", ":"), ensure_ascii=True).encode()
        )
        if (
            self._bootstrap_sha256(request.encode())
            != core.lineage.root_request_sha256
            or acceptance_sha256 != core.lineage.acceptance_sha256
        ):
            raise _GateError("bootstrap lineage binding is invalid")
        return path, raw, event_raw, event_fence

    def _validate_bootstrap_phases(
        self, core: _BootstrapCore, event_raw: bytes
    ) -> _QuarantineManifest:
        replay = core.replay
        object_type = self._git(b"cat-file", b"-t", replay.base_commit.encode())
        if object_type != b"commit\n":
            raise _GateError("bootstrap base commit is invalid")
        phases = (
            (replay.baseline_snapshot, "ordinary_baseline_schema_unsupported"),
            (replay.prospective_candidate, "recovery_baseline_chain_invalid"),
        )
        old_gate: bytes | None = None
        for phase, expected_error in phases:
            tree_type = self._git(b"cat-file", b"-t", phase.tree.encode())
            if tree_type != b"tree\n":
                raise _GateError("bootstrap phase tree is invalid")
            diff = self._git(
                b"diff",
                b"--binary",
                b"--no-ext-diff",
                replay.base_commit.encode(),
                phase.tree.encode(),
            )
            assert diff is not None
            if self._bootstrap_sha256(diff) != phase.staged_diff_sha256:
                raise _GateError("bootstrap phase diff is invalid")
            gate_blob = self._bootstrap_tree_blob(phase.tree, replay.gate_path)
            if (
                gate_blob is None
                or self._bootstrap_sha256(gate_blob) != replay.gate_sha256
                or old_gate is not None and gate_blob != old_gate
            ):
                raise _GateError("bootstrap replay gate is invalid")
            old_gate = gate_blob
            expected_stderr = self._BOOTSTRAP_REPLAY_STDERR[expected_error]
            if (
                phase.result.error_code != expected_error
                or phase.result.stdout_sha256 != self._bootstrap_sha256(b"")
                or phase.result.stderr_sha256
                != self._bootstrap_sha256(expected_stderr)
            ):
                raise _GateError("bootstrap replay result binding is invalid")
        delta = replay.manifest_delta
        self._validate_bootstrap_repository_path(delta.path)
        changed = self._git(
            b"diff-tree",
            b"--no-commit-id",
            b"--name-status",
            b"--no-renames",
            b"-z",
            b"-r",
            replay.baseline_snapshot.tree.encode(),
            replay.prospective_candidate.tree.encode(),
        )
        if changed != b"A\0" + os.fsencode(delta.path) + b"\0":
            raise _GateError("bootstrap cross-phase delta is invalid")
        if self._bootstrap_tree_blob(replay.baseline_snapshot.tree, delta.path) is not None:
            raise _GateError("bootstrap baseline manifest state is invalid")
        delta_blob = self._bootstrap_tree_blob(
            replay.prospective_candidate.tree, delta.path
        )
        if (
            delta_blob is None
            or len(delta_blob) != delta.size
            or self._bootstrap_sha256(delta_blob) != delta.sha256
        ):
            raise _GateError("bootstrap prospective manifest state is invalid")
        try:
            manifest = _QuarantineManifest.model_validate_json(delta_blob)
        except ValidationError as error:
            raise _GateError("bootstrap phase manifest is malformed") from error
        expected_delta_path = (
            f".github/iteration-quarantine/{manifest.predecessor_sha256}.json"
        )
        if (
            delta.path != expected_delta_path
            or manifest.successor_iteration_id != core.predecessor.iteration_id
            or manifest.base_head != replay.base_commit
            or self._manifest_request_sha256(manifest)
            != core.lineage.root_request_sha256
            or manifest.acceptance_sha256 != core.lineage.acceptance_sha256
            or core.predecessor.event.raw_sha256
            != self._bootstrap_sha256(event_raw)
        ):
            raise _GateError("bootstrap phase manifest binding is invalid")
        return manifest

    def _validate_bootstrap_candidate(
        self,
        core: _BootstrapCore,
        record_raw: bytes,
        record_path: Path,
        candidate_tree: str,
        core_sha256: str,
        delta_manifest: _QuarantineManifest,
    ) -> _QuarantineManifest:
        replay = core.replay
        planned_paths = [item.path for item in core.planned_blobs]
        target_path = (
            f".github/iteration-quarantine/{core.predecessor.sha256}.json"
        )
        expected_plans = (
            ("AGENTS.md", "present"),
            ("scripts/repository_gate.py", "present"),
            ("tests/test_repository_gate.py", "present"),
            (target_path, "absent"),
        )
        actual_plans = tuple(
            (item.path, item.baseline_state) for item in core.planned_blobs
        )
        if actual_plans != expected_plans:
            raise _GateError("bootstrap planned paths are invalid")
        for path in planned_paths:
            self._validate_bootstrap_repository_path(path)
        expected_allowed = [*planned_paths, core.control_envelope.path]
        if (
            core.scope.allowed_paths != expected_allowed
            or len(expected_allowed) != len(set(expected_allowed))
            or tuple(core.scope.forbidden_authority)
            != self._BOOTSTRAP_FORBIDDEN_AUTHORITY
            or replay.manifest_delta.path in expected_allowed
        ):
            raise _GateError("bootstrap scope is invalid")
        changed = self._git(
            b"diff-tree",
            b"--no-commit-id",
            b"--name-only",
            b"-z",
            b"-r",
            replay.prospective_candidate.tree.encode(),
            candidate_tree.encode(),
        )
        assert changed is not None
        changed_paths = [os.fsdecode(path) for path in changed.rstrip(b"\0").split(b"\0")]
        if sorted(changed_paths) != sorted(expected_allowed):
            raise _GateError("bootstrap candidate path set is invalid")
        forbidden = {
            core_sha256.encode(),
            self._bootstrap_sha256(record_raw).encode(),
        }
        for item in core.planned_blobs:
            blob = self._bootstrap_tree_blob(candidate_tree, item.path)
            prospective = self._bootstrap_tree_blob(
                replay.prospective_candidate.tree, item.path
            )
            expected_present = item.baseline_state == "present"
            if (
                blob is None
                or len(blob) != item.planned_size
                or self._bootstrap_sha256(blob) != item.planned_sha256
                or (prospective is not None) != expected_present
                or any(value in blob for value in forbidden)
            ):
                raise _GateError("bootstrap planned blob is invalid")
        executing = Path(__file__)
        try:
            executing_metadata = executing.lstat()
            executing_bytes = self._read_stable_file(
                executing, executing_metadata, "executing bootstrap gate"
            )
        except OSError as error:
            raise _GateError("executing bootstrap gate is unavailable") from error
        candidate_gate = self._bootstrap_tree_blob(candidate_tree, replay.gate_path)
        if (
            executing.is_symlink()
            or not executing.is_file()
            or candidate_gate != executing_bytes
        ):
            raise _GateError("executing gate differs from bootstrap candidate")
        if (
            self._bootstrap_tree_blob(
                replay.prospective_candidate.tree, core.control_envelope.path
            )
            is not None
            or self._bootstrap_tree_blob("HEAD", core.control_envelope.path)
            is not None
        ):
            raise _GateError("bootstrap control baseline state is invalid")
        target_item = next(
            (item for item in core.planned_blobs if item.path == target_path), None
        )
        if target_item is None or target_item.baseline_state != "absent":
            raise _GateError("bootstrap target manifest plan is invalid")
        target_blob = self._bootstrap_tree_blob(candidate_tree, target_path)
        if target_blob is None:
            raise _GateError("bootstrap target manifest is unavailable")
        try:
            target = _QuarantineManifest.model_validate_json(target_blob)
        except ValidationError as error:
            raise _GateError("bootstrap target manifest is malformed") from error
        if delta_manifest.successor_iteration_id != target.predecessor_iteration_id:
            raise _GateError("bootstrap manifest chain is invalid")
        record_relative = core.control_envelope.path
        indexed_record = self._bootstrap_tree_blob(candidate_tree, record_relative)
        if indexed_record != record_raw:
            raise _GateError("bootstrap control differs from candidate")
        return target

    def _validate_bootstrap_manifest_binding(
        self,
        core: _BootstrapCore,
        manifest: _QuarantineManifest,
        event_raw: bytes,
        event_fence: bytes,
    ) -> None:
        predecessor = core.predecessor
        replay = core.replay
        event = predecessor.event
        if (
            manifest.parser_failure_code != core.failure_code
            or manifest.predecessor_path != predecessor.path
            or manifest.predecessor_iteration_id != predecessor.iteration_id
            or manifest.predecessor_sha256 != predecessor.sha256
            or manifest.predecessor_size != predecessor.size
            or manifest.base_head != replay.base_commit
            or manifest.failing_event_ordinal != event.ordinal
            or manifest.failing_raw_block_sha256 != event.raw_sha256
            or manifest.failing_full_fence_sha256 != event.full_fence_sha256
            or manifest.trusted_prefix_event_count != event.prefix_event_count
            or manifest.trusted_prefix_sha256 != event.prefix_sha256
            or self._manifest_request_sha256(manifest)
            != core.lineage.root_request_sha256
            or manifest.acceptance_sha256 != core.lineage.acceptance_sha256
            or manifest.successor_iteration_id != core.successor.iteration_id
            or manifest.baseline_snapshot_tree != replay.baseline_snapshot.tree
            or manifest.baseline_snapshot_stderr_sha256
            != replay.baseline_snapshot.result.stderr_sha256
            or manifest.prospective_candidate_tree
            != replay.prospective_candidate.tree
            or manifest.prospective_candidate_stderr_sha256
            != replay.prospective_candidate.result.stderr_sha256
            or manifest.prospective_gate_sha256 != replay.gate_sha256
            or event.raw_sha256 != self._bootstrap_sha256(event_raw)
            or event.full_fence_sha256 != self._bootstrap_sha256(event_fence)
        ):
            raise _GateError("bootstrap target manifest binding is invalid")

    def _validate_bootstrap_manifest_control(
        self,
        manifest: _QuarantineManifest,
        event_raw: bytes,
        event_fence: bytes,
    ) -> None:
        control_path = (
            f".github/iteration-bootstrap/{manifest.predecessor_sha256}.json"
        )
        candidate_tree_output = self._git(b"write-tree")
        assert candidate_tree_output is not None
        candidate_tree = candidate_tree_output.decode().strip()
        control_blob = self._bootstrap_tree_blob(candidate_tree, control_path)
        if control_blob is None:
            raise _GateError("bootstrap manifest control is unavailable")
        try:
            decoded = json.loads(control_blob)
            record = _BootstrapRecord.model_validate(decoded)
        except (json.JSONDecodeError, ValidationError) as error:
            raise _GateError("bootstrap manifest control is malformed") from error
        if control_blob != self._bootstrap_canonical(decoded):
            raise _GateError("bootstrap manifest control is not canonical")
        self._validate_bootstrap_approvals(record, control_blob)
        core = record.core
        if (
            core.control_envelope.path != control_path
            or core.predecessor.sha256 != manifest.predecessor_sha256
        ):
            raise _GateError("bootstrap manifest control binding is invalid")
        delta_manifest = self._validate_bootstrap_phases(core, event_raw)
        if delta_manifest.successor_iteration_id != manifest.predecessor_iteration_id:
            raise _GateError("bootstrap manifest chain is invalid")
        self._validate_bootstrap_manifest_binding(
            core, manifest, event_raw, event_fence
        )
        target_path = (
            f".github/iteration-quarantine/{manifest.predecessor_sha256}.json"
        )
        target_blob = self._bootstrap_tree_blob(candidate_tree, target_path)
        target_item = next(
            (item for item in core.planned_blobs if item.path == target_path), None
        )
        if (
            target_blob is None
            or target_item is None
            or len(target_blob) != target_item.planned_size
            or self._bootstrap_sha256(target_blob) != target_item.planned_sha256
        ):
            raise _GateError("bootstrap manifest planned binding is invalid")
        committed_control = self._bootstrap_tree_blob("HEAD", control_path)
        if committed_control is not None and committed_control != control_blob:
            raise _GateError("committed bootstrap control is immutable")
        old_gate = self._bootstrap_tree_blob(
            core.replay.baseline_snapshot.tree, core.replay.gate_path
        )
        assert old_gate is not None
        self._replay_bootstrap_phases(
            core,
            old_gate,
            event_raw,
            self.root / manifest.predecessor_path,
        )

    def _validate_bootstrap_conflicts(
        self, core: _BootstrapCore, candidate_tree: str
    ) -> None:
        control_path = core.control_envelope.path
        target_manifest_path = (
            f".github/iteration-quarantine/{core.predecessor.sha256}.json"
        )
        for path in self._bootstrap_tree_paths(
            candidate_tree, ".github/iteration-bootstrap"
        ):
            blob = self._bootstrap_tree_blob(candidate_tree, path)
            assert blob is not None
            try:
                other = _BootstrapRecord.model_validate_json(blob)
            except ValidationError as error:
                raise _GateError("bootstrap control collection is malformed") from error
            if path == control_path:
                continue
            if (
                other.core.predecessor.sha256 == core.predecessor.sha256
                or other.core.predecessor.iteration_id
                == core.predecessor.iteration_id
                or other.core.successor.iteration_id
                == core.successor.iteration_id
            ):
                raise _GateError("bootstrap control is conflicting")
        for path in self._bootstrap_tree_paths(
            candidate_tree, ".github/iteration-quarantine"
        ):
            blob = self._bootstrap_tree_blob(candidate_tree, path)
            assert blob is not None
            try:
                manifest = _QuarantineManifest.model_validate_json(blob)
            except ValidationError as error:
                raise _GateError("bootstrap manifest collection is malformed") from error
            if path == target_manifest_path:
                continue
            if (
                manifest.predecessor_sha256 == core.predecessor.sha256
                or manifest.predecessor_iteration_id
                == core.predecessor.iteration_id
                or manifest.successor_iteration_id
                == core.successor.iteration_id
            ):
                raise _GateError("bootstrap manifest is conflicting")

    def _validate_bootstrap_unconsumed(self, core: _BootstrapCore) -> None:
        successor = (
            self.root
            / ".github"
            / "memory"
            / "iterations"
            / f"{core.successor.iteration_id}.md"
        )
        try:
            successor.lstat()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise _GateError("bootstrap successor state is unreadable") from error
        else:
            raise _GateError("bootstrap successor already exists")
        manifest_path = (
            f".github/iteration-quarantine/{core.predecessor.sha256}.json"
        )
        if (
            self._bootstrap_tree_blob("HEAD", core.control_envelope.path) is not None
            or self._bootstrap_tree_blob("HEAD", manifest_path) is not None
        ):
            raise _GateError("bootstrap authority is already committed")

    def _replay_bootstrap_phases(
        self,
        core: _BootstrapCore,
        old_gate: bytes,
        event_raw: bytes,
        predecessor_path: Path,
    ) -> None:
        scratch_parent = self.root / "out" / "tests"
        scratch_parent.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.pop("GIT_INDEX_FILE", None)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        with tempfile.TemporaryDirectory(
            prefix="bootstrap-replay-", dir=scratch_parent
        ) as directory:
            replay_root = Path(directory) / "repository"
            cloned = subprocess.run(
                [
                    "git",
                    "clone",
                    "--shared",
                    "--no-checkout",
                    "-q",
                    str(self.root),
                    str(replay_root),
                ],
                env=environment,
                capture_output=True,
                check=False,
            )
            if cloned.returncode:
                raise _GateError("bootstrap replay repository is unavailable")
            self._copy_bootstrap_private_ledgers(core, replay_root)
            replay_gate = replay_root / core.replay.gate_path
            replay_gate.parent.mkdir(parents=True, exist_ok=True)
            replay_gate.write_bytes(old_gate)
            replay_ledger = replay_root / core.predecessor.path
            replay_ledger.parent.mkdir(parents=True, exist_ok=True)
            replay_ledger.write_bytes(b"")
            replay_event = replay_root / "out" / "tests" / "bootstrap-event.json"
            replay_event.parent.mkdir(parents=True, exist_ok=True)
            replay_event.write_bytes(event_raw)
            phases = (
                core.replay.baseline_snapshot,
                core.replay.prospective_candidate,
            )
            for phase in phases:
                prepared = subprocess.run(
                    ["git", "read-tree", phase.tree],
                    cwd=replay_root,
                    env=environment,
                    capture_output=True,
                    check=False,
                )
                if prepared.returncode:
                    raise _GateError("bootstrap replay index is invalid")
                result = subprocess.run(
                    [
                        sys.executable,
                        str(replay_gate),
                        "validate-append",
                        "--ledger",
                        str(replay_ledger),
                        "--event",
                        str(replay_event),
                    ],
                    cwd=replay_root,
                    env=environment,
                    capture_output=True,
                    check=False,
                )
                evidence = phase.result
                if (
                    result.returncode != evidence.exit_code
                    or self._bootstrap_sha256(result.stdout)
                    != evidence.stdout_sha256
                    or self._bootstrap_sha256(result.stderr)
                    != evidence.stderr_sha256
                    or result.stderr
                    != self._BOOTSTRAP_REPLAY_STDERR[evidence.error_code]
                ):
                    raise _GateError("bootstrap replay result is invalid")
        if predecessor_path.read_bytes() == b"":
            raise _GateError("bootstrap predecessor changed during replay")

    def _copy_bootstrap_private_ledgers(
        self, core: _BootstrapCore, replay_root: Path
    ) -> None:
        trees = (
            core.replay.baseline_snapshot.tree,
            core.replay.prospective_candidate.tree,
        )
        paths: set[str] = set()
        for tree in trees:
            for path in self._bootstrap_tree_paths(
                tree, ".github/iteration-quarantine"
            ):
                blob = self._bootstrap_tree_blob(tree, path)
                assert blob is not None
                try:
                    manifest = _QuarantineManifest.model_validate_json(blob)
                except ValidationError as error:
                    raise _GateError("bootstrap replay manifest is malformed") from error
                paths.add(manifest.predecessor_path)
        for path in paths:
            source = self.root / path
            try:
                metadata = source.lstat()
            except FileNotFoundError:
                continue
            except OSError as error:
                raise _GateError("bootstrap replay predecessor is unreadable") from error
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise _GateError("bootstrap replay predecessor is invalid")
            target = replay_root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                self._read_stable_file(source, metadata, "bootstrap replay predecessor")
            )

    def _bootstrap_tree_blob(self, tree: str, path: str) -> bytes | None:
        self._validate_bootstrap_repository_path(path)
        entry = self._git(
            b"ls-tree", b"-z", tree.encode(), b"--", os.fsencode(path)
        )
        assert entry is not None
        if not entry:
            return None
        records = entry.rstrip(b"\0").split(b"\0")
        if len(records) != 1 or b"\t" not in records[0]:
            raise _GateError("bootstrap Git tree entry is invalid")
        metadata, encoded_path = records[0].split(b"\t", 1)
        fields = metadata.split(b" ")
        if (
            encoded_path != os.fsencode(path)
            or len(fields) != 3
            or fields[0] not in {b"100644", b"100755"}
            or fields[1] != b"blob"
            or re.fullmatch(rb"[0-9a-f]{40}", fields[2]) is None
        ):
            raise _GateError("bootstrap Git tree entry is invalid")
        blob = self._git(b"cat-file", b"blob", fields[2])
        assert blob is not None
        return blob

    def _bootstrap_tree_paths(self, tree: str, directory: str) -> list[str]:
        self._validate_bootstrap_repository_path(directory)
        output = self._git(
            b"ls-tree",
            b"-r",
            b"-z",
            b"--name-only",
            tree.encode(),
            b"--",
            os.fsencode(directory),
        )
        assert output is not None
        if not output:
            return []
        paths = [os.fsdecode(path) for path in output.rstrip(b"\0").split(b"\0")]
        if len(paths) != len(set(paths)):
            raise _GateError("bootstrap Git path collection is invalid")
        return paths

    @staticmethod
    def cli(argv: list[str]):
        parser = argparse.ArgumentParser(description="Validate repository commit and workflow evidence")
        subparsers = parser.add_subparsers(dest="action", required=True)
        subparsers.add_parser("scan-staged")
        verify = subparsers.add_parser("verify-ledger")
        verify.add_argument("--ledger", type=Path)
        validate_append = subparsers.add_parser("validate-append")
        validate_append.add_argument("--ledger", type=Path, required=True)
        validate_append.add_argument("--event", type=Path, required=True)
        validate_bootstrap = subparsers.add_parser("validate-bootstrap")
        validate_bootstrap.add_argument("--record", type=Path, required=True)
        validate_bootstrap.add_argument("--ledger", type=Path, required=True)
        subparsers.add_parser("hook")
        arguments = parser.parse_args(argv)
        try:
            gate = RepositoryGate.discover(Path.cwd())
            if arguments.action == "scan-staged":
                gate.scan_staged()
            elif arguments.action == "verify-ledger":
                gate.verify_ledger(arguments.ledger)
            elif arguments.action == "validate-append":
                next_state = gate.validate_append(arguments.ledger, arguments.event)
                print(f"[repository-gate] next state: {next_state or 'COMPLETE'}")
            elif arguments.action == "validate-bootstrap":
                gate.validate_bootstrap(arguments.record, arguments.ledger)
                print("[repository-gate] bootstrap control valid")
            else:
                gate.run_hook()
        except _GateError as error:
            print(f"[repository-gate] FAIL: {error}", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(RepositoryGate.cli(sys.argv[1:]))
