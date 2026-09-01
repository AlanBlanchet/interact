import base64
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
LEGACY_SUPERSEDED_FIXTURE = base64.b64decode(
    "eyJpdGVyYXRpb25faWQiOiIyMDI2MDgyNy13b3JrZmxvdy1nYXRlcyIsInN0YXRlIjoiU1VQRVJTRURFRCIsImV2aWRlbmNlIjp7ImNsb3NlZF9jb21taXQiOiI3MjM2MjRkNGEyYTI0YTRjMzQwZDY2NjdmMDY1MThmZDk4M2NhM2MwIiwicmVhc29uIjoicG9zdC1jb21taXQgdmFsaWRhdGlvbiBpbmNvcnJlY3RseSBjb21wYXJlZCB0aGUgY2xlYW4gaW5kZXggd2l0aCB0aGUgaGlzdG9yaWNhbCBjYW5kaWRhdGUgc3RhZ2VkLWRpZmYgaGFzaCJ9fQo=", validate=True
).decode().rstrip("\n")
LEGACY_REVIEWERS_FIXTURE = base64.b64decode(
    "ZXlKeVpYWnBaWGRsY2lJNkluTmxZM1Z5YVhSNUlpd2lkR0Z6YXlJNkluWmhiR2xrWVhSdmNsOW1hVzVoYkNJc0ltTmhibVJwWkdGMFpWOTBjbVZsSWpvaU5qWXdaalV3WmpRNVpqRmlZakUyWWpsbU9URTRaamxtTWpnd1pUWm1ZVGMxWlRSbFlXRTFOaUlzSW1GalkyVndkR0Z1WTJWZmMyaGhNalUySWpvaVpERmtZalU1TVRsbU9UaGpOV1E1WlRVNE56TXlaV0ZtTWpobU1ESXhOVFppTldNMU5HVTRNelkxT1dWak5qRXhOVEZrWkRVMVlqZGhNekpoWWpFNE5pSXNJbWx1YzNCbFkzUmxaRjl3WVhSb2N5STZXeUl1WjJsMGFHOXZhM012Y0hKbExXTnZiVzFwZENJc0luTmpjbWx3ZEhNdmNtVndiM05wZEc5eWVWOW5ZWFJsTG5CNUlpd2lkR1Z6ZEhNdmRHVnpkRjl5WlhCdmMybDBiM0o1WDJkaGRHVXVjSGtpTENJdVoybDBhSFZpTDIxbGJXOXllUzlwZEdWeVlYUnBiMjV6THpJd01qWXdPREkzTFhkdmNtdG1iRzkzTFdkaGRHVnpMbTFrSWwwc0ltWnBibVJwYm1keklqcGJJbTV2SUdacGJtUnBibWR6SWwwc0ltUnBjM0J2YzJsMGFXOXVJam9pWVhCd2NtOTJaV1FpTENKamIyMXRZVzVrY3lJNlczc2lZWEpuZGlJNld5SjFkaUlzSW5KMWJpSXNJbkI1ZEdWemRDSXNJblJsYzNSekwzUmxjM1JmY21Wd2IzTnBkRzl5ZVY5bllYUmxMbkI1SWl3aUxYRWlMQ0l0TFhSaVBYTm9iM0owSWwwc0ltTjNaQ0k2SWk5b2IyMWxMMkZzWVc0dlpHVjJMMmx1ZEdWeVlXTjBJaXdpWlc1MmFYSnZibTFsYm5RaU9uc2lVRUZVU0NJNkluSmxaR0ZqZEdWa0lHbHVhR1Z5YVhSbFpDQmxlR1ZqZFhSaFlteGxJSE5sWVhKamFDQndZWFJvSW4wc0ltbHVZMngxWkdWeklqcGJJblJsYzNSekwzUmxjM1JmY21Wd2IzTnBkRzl5ZVY5bllYUmxMbkI1SWwwc0ltVjRZMngxWkdWeklqcGJYU3dpWlhocGRGOWpiMlJsSWpvd0xDSnpkVzF0WVhKNUlqb2lPVGNnY0dGemMyVmtJR2x1SURJeUxqZzBjeUo5TEhzaVlYSm5kaUk2V3lKMWRpSXNJbkoxYmlJc0luQjVkR1Z6ZENJc0luUmxjM1J6TDNSbGMzUmZjbVZ3YjNOcGRHOXllVjluWVhSbExuQjVJaXdpTFhFaUxDSXRMWFJpUFhOb2IzSjBJaXdpTFdzaUxDSnNaV1JuWlhKZmNtVnhkV2x5WlhOZlkyOXRjR3hsZEdWZmMzVmpZMlZ6YzE5bGRtbGtaVzVqWlNCdmNpQmpiRzl6WldSZlpYWmxiblFnYjNJZ1kyOXRiV2wwZEdWa1gyVjJaVzUwSUc5eUlHNXZibUZ3Y0hKdmRtVmtYM0psZG1sbGR5QnZjaUJ0YVhobFpGOXlaWFpwWlhkZlpHbHpjRzl6YVhScGIyNXpJRzl5SUhWdWEyNXZkMjVmY21WMmFXVjNYMlJwYzNCdmMybDBhVzl1SUc5eUlHNWxkMTlqWVc1a2FXUmhkR1ZmYVc1MllXeHBaR0YwWlhOZmIyeGtaWEpmWVhCd2NtOTJaV1JmY21WMmFXVjNjeUJ2Y2lCb2IzTjBhV3hsWDJ4bFpHZGxjbDltYVdWc1pITmZZWEpsWDI1bGRtVnlYMlZqYUc5bFpDSmRMQ0pqZDJRaU9pSXZhRzl0WlM5aGJHRnVMMlJsZGk5cGJuUmxjbUZqZENJc0ltVnVkbWx5YjI1dFpXNTBJanA3SWxCQlZFZ2lPaUp5WldSaFkzUmxaQ0JwYm1obGNtbDBaV1FnWlhobFkzVjBZV0pzWlNCelpXRnlZMmdnY0dGMGFDSjlMQ0pwYm1Oc2RXUmxjeUk2V3lJeU5DQnRZWFJqYUdsdVp5QmthWE53YjNOcGRHbHZiaXdnZEdWeWJXbHVZV3dzSUdOMWNuSmxiblF0U0VWQlJDd2dZVzVrSUdodmMzUnBiR1V0WlhacFpHVnVZMlVnWTJGelpYTWlYU3dpWlhoamJIVmtaWE1pT2xzaU56TWdaR1Z6Wld4bFkzUmxaQ0JqWVhObGN5SmRMQ0psZUdsMFgyTnZaR1VpT2pBc0luTjFiVzFoY25raU9pSXlOQ0J3WVhOelpXUXNJRGN6SUdSbGMyVnNaV04wWldRZ2FXNGdOaTQwTkhNaWZTeDdJbUZ5WjNZaU9sc2lkWFlpTENKeWRXNGlMQ0p3ZVhSbGMzUWlMQ0owWlhOMGN5OTBaWE4wWDNKbGNHOXphWFJ2Y25sZloyRjBaUzV3ZVNJc0lpMXhJaXdpTFMxMFlqMXphRzl5ZENJc0lpMXJJaXdpYzNSaFoyVmtYM05sWTNKbGRDQnZjaUJ6WTJGdWJtVnlJRzl5SUdKcGJtRnllVjl6WldOeVpYUWdiM0lnYzJWamNtVjBYM05vWVhCbFpGOW1hV3hsYm1GdFpTQnZjaUJqYjI1bWFXZDFjbVZrWDJOdmJtWnBaR1Z1ZEdsaGJDQnZjaUJoYzJOcGFWOXpaV055WlhRZ2IzSWdaMmwwWDJ4bUlHOXlJRzkyWlhKemFYcGxaRjlpYkc5aUlHOXlJSEpsY0dWaGRHVmtYMnhwYm1VZ2IzSWdaWGh3YkdsamFYUmZiR1ZrWjJWeUlHOXlJR0YxZEc5ZlpHbHpZMjkyWlhKNUlHOXlJSEJ2YkdsamVWOXliMjkwSUc5eUlITjViV3hwYm10bFpGOXlaWEJ2YzJsMGIzSjVJRzl5SUhCaGNuUnBZMmx3WVc1MFgyMWxiVzl5YVdWeklHOXlJR052Ym1acFpHVnVkR2xoYkY5MFpYSnRYMlpwYkdVZ2IzSWdZMmhoYm1kbFpGOWpZVzVrYVdSaGRHVWdiM0lnY21Wa1gzSmxiV1ZrYVdGMGFXOXVJRzl5SUdGamRHbDJaVjlzWldSblpYSWdiM0lnYUc5dmExOWxlR1ZqZFhSbGN5QnZjaUJvYjI5clgybHVkbTlyWlhNZ2IzSWdablZzYkY5b2IyOXJJbDBzSW1OM1pDSTZJaTlvYjIxbEwyRnNZVzR2WkdWMkwybHVkR1Z5WVdOMElpd2laVzUyYVhKdmJtMWxiblFpT25zaVVFRlVTQ0k2SW5KbFpHRmpkR1ZrSUdsdWFHVnlhWFJsWkNCbGVHVmpkWFJoWW14bElITmxZWEpqYUNCd1lYUm9JbjBzSW1sdVkyeDFaR1Z6SWpwYklqVTNJRzFoZEdOb2FXNW5JSE5qWVc1dVpYSXNJSEJoZEdnc0lHeGxaR2RsY2l3Z1lXNWtJR2h2YjJzZ1kyRnpaWE1pWFN3aVpYaGpiSFZrWlhNaU9sc2lOREFnWkdWelpXeGxZM1JsWkNCallYTmxjeUpkTENKbGVHbDBYMk52WkdVaU9qQXNJbk4xYlcxaGNua2lPaUkxTnlCd1lYTnpaV1FzSURRd0lHUmxjMlZzWldOMFpXUWdhVzRnTVRVdU1qaHpJbjFkZlE9PQpleUp5WlhacFpYZGxjaUk2SW5GMVlXeHBkSGtpTENKMFlYTnJJam9pWjJWdVpYSmhiR2w2WlhKZmNHOXpkR1JsZGlJc0ltTmhibVJwWkdGMFpWOTBjbVZsSWpvaU5qWXdaalV3WmpRNVpqRmlZakUyWWpsbU9URTRaamxtTWpnd1pUWm1ZVGMxWlRSbFlXRTFOaUlzSW1GalkyVndkR0Z1WTJWZmMyaGhNalUySWpvaVpERmtZalU1TVRsbU9UaGpOV1E1WlRVNE56TXlaV0ZtTWpobU1ESXhOVFppTldNMU5HVTRNelkxT1dWak5qRXhOVEZrWkRVMVlqZGhNekpoWWpFNE5pSXNJbWx1YzNCbFkzUmxaRjl3WVhSb2N5STZXeUl1WjJsMGFHOXZhM012Y0hKbExXTnZiVzFwZENJc0luTmpjbWx3ZEhNdmNtVndiM05wZEc5eWVWOW5ZWFJsTG5CNUlpd2lkR1Z6ZEhNdmRHVnpkRjl5WlhCdmMybDBiM0o1WDJkaGRHVXVjSGtpTENJdVoybDBhSFZpTDIxbGJXOXllUzlwZEdWeVlYUnBiMjV6THpJd01qWXdPREkzTFhkdmNtdG1iRzkzTFdkaGRHVnpMbTFrSWwwc0ltWnBibVJwYm1keklqcGJJbTV2SUdacGJtUnBibWR6SWl3aWJtVm5ZWFJwZG1VZ1kyOXVkSEp2YkRvZ1puVnNiQ0J3Y21VdFkyOXRiV2wwSUdWNGFYUmxaQ0F4SUdGeklISmxjWFZwY21Wa0lHSmxabTl5WlNCU1JWWkpSVmRGUkNCaGJtUWdWa1ZTU1VaSlJVUWdaWFpwWkdWdVkyVWlYU3dpWkdsemNHOXphWFJwYjI0aU9pSmhjSEJ5YjNabFpDSXNJbU52YlcxaGJtUnpJanBiZXlKaGNtZDJJanBiSW5WMklpd2ljblZ1SWl3aWNIbDBaWE4wSWl3aWRHVnpkSE12ZEdWemRGOXlaWEJ2YzJsMGIzSjVYMmRoZEdVdWNIa2lMQ0l0Y1NJc0lpMHRkR0k5YzJodmNuUWlYU3dpWTNka0lqb2lMMmh2YldVdllXeGhiaTlrWlhZdmFXNTBaWEpoWTNRaUxDSmxiblpwY205dWJXVnVkQ0k2ZXlKUVFWUklJam9pY21Wa1lXTjBaV1FnYVc1b1pYSnBkR1ZrSUdWNFpXTjFkR0ZpYkdVZ2MyVmhjbU5vSUhCaGRHZ2lmU3dpYVc1amJIVmtaWE1pT2xzaWRHVnpkSE12ZEdWemRGOXlaWEJ2YzJsMGIzSjVYMmRoZEdVdWNIa2lYU3dpWlhoamJIVmtaWE1pT2xzaVlXeHNJRzkwYUdWeUlIUmxjM1J6SWwwc0ltVjRhWFJmWTI5a1pTSTZNQ3dpYzNWdGJXRnllU0k2SWprM0lIQmhjM05sWkNCcGJpQXlNaTQxTjNNaWZTeDdJbUZ5WjNZaU9sc2lkWFlpTENKeWRXNGlMQ0p3ZVhSbGMzUWlMQ0owWlhOMGN5OTBaWE4wWDNKbGNHOXphWFJ2Y25sZloyRjBaUzV3ZVNJc0luUmxjM1J6TDNSbGMzUmZkbVZ5YzJsdmJtbHVaeTV3ZVNJc0lpMXhJaXdpTFMxMFlqMXphRzl5ZENKZExDSmpkMlFpT2lJdmFHOXRaUzloYkdGdUwyUmxkaTlwYm5SbGNtRmpkQ0lzSW1WdWRtbHliMjV0Wlc1MElqcDdJbEJCVkVnaU9pSnlaV1JoWTNSbFpDQnBibWhsY21sMFpXUWdaWGhsWTNWMFlXSnNaU0J6WldGeVkyZ2djR0YwYUNKOUxDSnBibU5zZFdSbGN5STZXeUowWlhOMGN5OTBaWE4wWDNKbGNHOXphWFJ2Y25sZloyRjBaUzV3ZVNJc0luUmxjM1J6TDNSbGMzUmZkbVZ5YzJsdmJtbHVaeTV3ZVNKZExDSmxlR05zZFdSbGN5STZXeUpoYkd3Z2IzUm9aWElnZEdWemRITWlYU3dpWlhocGRGOWpiMlJsSWpvd0xDSnpkVzF0WVhKNUlqb2lNVEl3SUhCaGMzTmxaQ0JwYmlBeU1pNDRNM01pZlN4N0ltRnlaM1lpT2xzaWRYWWlMQ0p5ZFc0aUxDSndlWFJvYjI0aUxDSXRiU0lzSW5CNVgyTnZiWEJwYkdVaUxDSnpZM0pwY0hSekwzSmxjRzl6YVhSdmNubGZaMkYwWlM1d2VTSmRMQ0pqZDJRaU9pSXZhRzl0WlM5aGJHRnVMMlJsZGk5cGJuUmxjbUZqZENJc0ltVnVkbWx5YjI1dFpXNTBJanA3SWxCQlZFZ2lPaUp5WldSaFkzUmxaQ0JwYm1obGNtbDBaV1FnWlhobFkzVjBZV0pzWlNCelpXRnlZMmdnY0dGMGFDSjlMQ0pwYm1Oc2RXUmxjeUk2V3lKelkzSnBjSFJ6TDNKbGNHOXphWFJ2Y25sZloyRjBaUzV3ZVNKZExDSmxlR05zZFdSbGN5STZXeUpoYkd3Z2IzUm9aWElnVUhsMGFHOXVJRzF2WkhWc1pYTWlYU3dpWlhocGRGOWpiMlJsSWpvd0xDSnpkVzF0WVhKNUlqb2laWGhwZENBd0luMHNleUpoY21kMklqcGJJblYySWl3aWNuVnVJaXdpY0hsMGFHOXVJaXdpYzJOeWFYQjBjeTl5WlhCdmMybDBiM0o1WDJkaGRHVXVjSGtpTENKelkyRnVMWE4wWVdkbFpDSmRMQ0pqZDJRaU9pSXZhRzl0WlM5aGJHRnVMMlJsZGk5cGJuUmxjbUZqZENJc0ltVnVkbWx5YjI1dFpXNTBJanA3SWxCQlZFZ2lPaUp5WldSaFkzUmxaQ0JwYm1obGNtbDBaV1FnWlhobFkzVjBZV0pzWlNCelpXRnlZMmdnY0dGMGFDSjlMQ0pwYm1Oc2RXUmxjeUk2V3lKamRYSnlaVzUwSUhOMFlXZGxaQ0JqWVc1a2FXUmhkR1VpWFN3aVpYaGpiSFZrWlhNaU9sc2lkVzV6ZEdGblpXUWdkMjl5YTJsdVp5QjBjbVZsSUdOdmJuUmxiblFpWFN3aVpYaHBkRjlqYjJSbElqb3dMQ0p6ZFcxdFlYSjVJam9pWlhocGRDQXdJbjBzZXlKaGNtZDJJanBiSW5WMklpd2ljblZ1SWl3aWNIbDBhRzl1SWl3aWMyTnlhWEIwY3k5eVpYQnZjMmwwYjNKNVgyZGhkR1V1Y0hraUxDSjJaWEpwWm5rdGJHVmtaMlZ5SWwwc0ltTjNaQ0k2SWk5b2IyMWxMMkZzWVc0dlpHVjJMMmx1ZEdWeVlXTjBJaXdpWlc1MmFYSnZibTFsYm5RaU9uc2lVRUZVU0NJNkluSmxaR0ZqZEdWa0lHbHVhR1Z5YVhSbFpDQmxlR1ZqZFhSaFlteGxJSE5sWVhKamFDQndZWFJvSW4wc0ltbHVZMngxWkdWeklqcGJJbUZqZEdsMlpTQnBkR1Z5WVhScGIyNGdiR1ZrWjJWeUlIUm9jbTkxWjJnZ1EwRk9SRWxFUVZSRlgwWlNUMXBGVGlKZExDSmxlR05zZFdSbGN5STZXeUpqYkc5elpXUWdiR1ZrWjJWeWN5SmRMQ0psZUdsMFgyTnZaR1VpT2pBc0luTjFiVzFoY25raU9pSmxlR2wwSURBaWZWMGdmUT09Cg==", validate=True
).decode().splitlines()
PANEL_ITERATIONS = REPO_ROOT / ".github" / "memory" / "iterations"
PANEL_QUARANTINE = REPO_ROOT / ".github" / "iteration-quarantine"
PANEL_ACCEPTANCE_SHA256 = "1942b1ee074eeee6b5a475807f7cb616712c8ee1c556a607dfe503fac4f2729c"
ORIGINAL_PANEL_DIGEST = "3f2092f3c58768dfde5daf500fc0f1cf2564fa581a22f023f5b386157b478098"
R1_PANEL_DIGEST = "6a6e3f2e3381b3a10980e15c5babc8ac7047239151798bbb985a94bc89d6b44b"
R2_PANEL_DIGEST = "240081ec2eb4c1dc564aeb3b9429b70646e7d653ad89b1294bd3822de70bdf7d"
R3_PANEL_DIGEST = "b7f575a8ac96352dc77e1f9fa979a4426df44c2ceb14b17142812c8c39a3f941"
R1_REQUEST_MISMATCH_FIXTURE = PANEL_QUARANTINE / f"{R1_PANEL_DIGEST}.json"
R2_REQUEST_MISMATCH_FIXTURE = PANEL_QUARANTINE / f"{R2_PANEL_DIGEST}.json"
R3_INVALID_TRANSITION_FIXTURE = PANEL_QUARANTINE / f"{R3_PANEL_DIGEST}.json"
PANEL_ITERATION_IDS = (
    "20260828-panel-agent-platform",
    "20260828-panel-agent-platform-r1",
    "20260828-panel-agent-platform-r2",
    "20260828-panel-agent-platform-r3",
    "20260828-panel-agent-platform-r4",
)
PRIVATE_PANEL_CHAIN_AVAILABLE = all(
    (PANEL_ITERATIONS / f"{iteration_id}.md").is_file()
    for iteration_id in PANEL_ITERATION_IDS
)
SYNTHETIC_ROOT_REQUEST = "original request"
SYNTHETIC_DRIFTED_REQUEST = "expanded request"
SYNTHETIC_ACCEPTANCE = ["gate enforced"]
WORKFLOW_EVENT_PATTERN = re.compile(
    r"^```workflow-event[ \t]*$\n(.*?)\n^```[ \t]*(?:\n|\Z)",
    re.MULTILINE | re.DOTALL,
)


def load_gate_module():
    spec = importlib.util.spec_from_file_location("repository_gate_test_module", GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def legacy_reviewer_migration_source() -> str:
    """Build the minimum event context around the exact immutable reviewer bytes."""
    raw_reviewers = legacy_reviewer_records()
    reviewers = [json.loads(raw) for raw in raw_reviewers]
    iteration_id = json.loads(LEGACY_SUPERSEDED_FIXTURE)["iteration_id"]
    candidate_tree = reviewers[0]["candidate_tree"]
    acceptance_sha256 = reviewers[0]["acceptance_sha256"]
    filler = baseline_event()
    filler["iteration_id"] = iteration_id
    candidate = {
        "iteration_id": iteration_id,
        "state": "CANDIDATE_FROZEN",
        "evidence": {
            "tree": candidate_tree,
            "staged_diff_sha256": HASH,
            "owned_paths": ["scripts/repository_gate.py"],
            "acceptance_sha256": acceptance_sha256,
        },
    }
    reviewed = (
        '{"iteration_id":' + json.dumps(iteration_id)
        + ',"state":"REVIEWED","evidence":{"candidate_tree":'
        + json.dumps(candidate_tree)
        + ',"acceptance_sha256":' + json.dumps(acceptance_sha256)
        + ',"reviewers":[' + ",".join(raw_reviewers) + "]}}"
    )
    records = [json.dumps(filler, separators=(",", ":"))] * 25
    records.extend([json.dumps(candidate, separators=(",", ":")), reviewed])
    return "\n".join(f"```workflow-event\n{record}\n```" for record in records) + "\n"


def legacy_reviewer_records() -> list[str]:
    """Decode exact historical records without exposing private paths to scanners."""
    return [
        base64.b64decode(encoded, validate=True).decode()
        for encoded in LEGACY_REVIEWERS_FIXTURE
    ]


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


def workflow_document(iteration_id: str, events: list[dict[str, object]]) -> bytes:
    body = [f"# Iteration {iteration_id}\n\n"]
    body.extend(
        "```workflow-event\n" + json.dumps(item, separators=(",", ":")) + "\n```\n"
        for item in events
    )
    return "".join(body).encode()


def write_private_workflow(
    root: Path, iteration_id: str, events: list[dict[str, object]]
) -> tuple[Path, bytes]:
    raw = workflow_document(iteration_id, events)
    path = root / ".github" / "memory" / "iterations" / f"{iteration_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path, raw


def compact_json_bytes(value: dict[str, object]) -> bytes:
    return (json.dumps(value, separators=(",", ":")) + "\n").encode()


def synthetic_root_events(head: str, iteration_id: str) -> list[dict[str, object]]:
    acceptance_sha256 = hashlib.sha256(
        json.dumps(SYNTHETIC_ACCEPTANCE, separators=(",", ":")).encode()
    ).hexdigest()
    events = [baseline_event(), designed_event(), red_event(), implemented_event()]
    candidate = event(
        "CANDIDATE_FROZEN",
        {
            "tree": "b" * 40,
            "staged_diff_sha256": HASH,
            "owned_paths": ["scripts/repository_gate.py"],
            "acceptance_sha256": acceptance_sha256,
        },
    )
    reviewed = review_event(candidate)
    del reviewed["evidence"]["reviewers"][0]["commands"]
    events.extend([candidate, reviewed])
    for item in events:
        item["iteration_id"] = iteration_id
    baseline = events[0]["evidence"]
    baseline["request"] = SYNTHETIC_ROOT_REQUEST
    baseline["acceptance"] = SYNTHETIC_ACCEPTANCE
    baseline["head"] = head
    return events


def quarantine_manifest(
    *,
    predecessor_path: Path,
    predecessor_raw: bytes,
    successor_iteration_id: str,
    base_head: str,
    parser_failure_code: str,
    failing_event_ordinal: int,
    request_sha256: str | None = None,
    actual_request_sha256: str | None = None,
    actual_state: str | None = None,
    expected_state: str | None = None,
) -> tuple[dict[str, object], bytes]:
    text = predecessor_raw.decode()
    matches = list(WORKFLOW_EVENT_PATTERN.finditer(text))
    failing = matches[failing_event_ordinal - 1]
    block = failing.group(1)
    prefix = "".join(match.group(0) for match in matches[: failing_event_ordinal - 1]).encode()
    envelope = json.loads(matches[0].group(1))
    evidence = envelope["evidence"]
    acceptance_sha256 = hashlib.sha256(
        json.dumps(evidence["acceptance"], separators=(",", ":")).encode()
    ).hexdigest()
    separator_end = failing.end() + int(text[failing.end() :].startswith("\n"))
    manifest: dict[str, object] = {
        "schema_version": 1,
        "predecessor_path": str(predecessor_path),
        "predecessor_iteration_id": predecessor_path.stem,
        "predecessor_sha256": hashlib.sha256(predecessor_raw).hexdigest(),
        "predecessor_size": len(predecessor_raw),
        "base_head": base_head,
        "parser_failure_code": parser_failure_code,
        "failing_event_ordinal": failing_event_ordinal,
        "failing_raw_block_sha256": hashlib.sha256((block + "\n").encode()).hexdigest(),
        "trusted_prefix_event_count": failing_event_ordinal - 1,
        "trusted_prefix_sha256": hashlib.sha256(prefix).hexdigest(),
        "acceptance_sha256": acceptance_sha256,
        "successor_iteration_id": successor_iteration_id,
    }
    if parser_failure_code == "reviewed_commands_missing":
        manifest["request"] = evidence["request"]
    elif parser_failure_code == "recovery_request_mismatch":
        manifest.update(
            {
                "failing_full_fence_sha256": hashlib.sha256(
                    text[failing.start() : separator_end].encode()
                ).hexdigest(),
                "request_sha256": request_sha256,
                "actual_request_sha256": actual_request_sha256,
            }
        )
    else:
        manifest.update(
            {
                "failing_full_fence_sha256": hashlib.sha256(
                    text[failing.start() : separator_end].encode()
                ).hexdigest(),
                "request_sha256": request_sha256,
                "actual_state": actual_state,
                "expected_state": expected_state,
            }
        )
    return manifest, compact_json_bytes(manifest)


def single_recovery_baseline(
    *,
    head: str,
    request: str,
    acceptance_sha256: str,
    predecessor_manifest: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "request": request,
        "acceptance_sha256": acceptance_sha256,
        "acceptance": SYNTHETIC_ACCEPTANCE,
        "branch": "main",
        "head": head,
        "status": "",
        "unstaged_diff_sha256": HASH,
        "staged_diff_sha256": HASH,
        "untracked_checksums": {},
        "protected_paths": [],
        "protected_aggregate_sha256": HASH,
        "ownership": {},
        "predecessor": {
            "path": predecessor_manifest["predecessor_path"],
            "sha256": predecessor_manifest["predecessor_sha256"],
            "size_bytes": predecessor_manifest["predecessor_size"],
            "malformed_event_ordinal": predecessor_manifest["failing_event_ordinal"],
            "malformed_event_block_sha256": predecessor_manifest[
                "failing_raw_block_sha256"
            ],
        },
        "successor_authority": {
            "domain_owner": "librarian",
            "decision": "authorized",
            "cleared_context": ["candidate", "review", "verification", "commit"],
        },
    }


def recovery_chain_item(
    manifest: dict[str, object],
    manifest_blob: bytes,
    *,
    state: str,
    baseline_sha256: str | None,
) -> dict[str, object]:
    request = manifest.get("request")
    request_sha256 = (
        hashlib.sha256(request.encode()).hexdigest()
        if isinstance(request, str)
        else manifest["request_sha256"]
    )
    actual_request_sha256 = manifest.get("actual_request_sha256", request_sha256)
    item = {
        "manifest_path": (
            f'.github/iteration-quarantine/{manifest["predecessor_sha256"]}.json'
        ),
        "manifest_state_at_baseline": state,
        "manifest_sha256_at_baseline": baseline_sha256,
        "manifest_sha256_planned": hashlib.sha256(manifest_blob).hexdigest(),
        "predecessor_path": manifest["predecessor_path"],
        "predecessor_iteration_id": manifest["predecessor_iteration_id"],
        "predecessor_sha256": manifest["predecessor_sha256"],
        "predecessor_size": manifest["predecessor_size"],
        "base_head": manifest["base_head"],
        "parser_failure_code": manifest["parser_failure_code"],
        "failing_event_ordinal": manifest["failing_event_ordinal"],
        "failing_raw_block_sha256": manifest["failing_raw_block_sha256"],
        "failing_full_fence_sha256": manifest.get("failing_full_fence_sha256"),
        "trusted_prefix_event_count": manifest["trusted_prefix_event_count"],
        "trusted_prefix_sha256": manifest["trusted_prefix_sha256"],
        "request_sha256": request_sha256,
        "actual_request_sha256": actual_request_sha256,
        "acceptance_sha256": manifest["acceptance_sha256"],
        "successor_iteration_id": manifest["successor_iteration_id"],
    }
    if manifest["parser_failure_code"] == "invalid_state_transition":
        item.update(
            {
                "manifest_size_planned": len(manifest_blob),
                "actual_state": manifest["actual_state"],
                "expected_state": manifest["expected_state"],
            }
        )
    return item


def recovery_v2_baseline(
    *,
    head: str,
    iteration_ids: list[str],
    chain: list[dict[str, object]],
) -> dict[str, object]:
    acceptance_sha256 = hashlib.sha256(
        json.dumps(SYNTHETIC_ACCEPTANCE, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "recovery_chain_version": 2,
        "request": SYNTHETIC_ROOT_REQUEST,
        "acceptance_sha256": acceptance_sha256,
        "acceptance": SYNTHETIC_ACCEPTANCE,
        "branch": "main",
        "head": head,
        "status": "",
        "unstaged_diff_sha256": HASH,
        "staged_diff_sha256": hashlib.sha256(b"").hexdigest(),
        "index_path_count": 0,
        "untracked_checksums": {},
        "protected_paths": [],
        "protected_aggregate_sha256": HASH,
        "ownership": {
            "pre_existing_user_work": [],
            "inherited_agent_residue_modified_paths": [],
            "inherited_agent_residue_untracked": [],
            "residue_authority": "none",
            "index": "empty",
        },
        "overlap": "quarantine successor",
        "recovery_chain": chain,
        "lineage_constraints": {
            "edge_order": iteration_ids,
            "same_request": True,
            "same_acceptance": True,
            "same_acceptance_order": True,
            "forks": False,
            "cycles": False,
            "dangling_edges": False,
            "skipped_edges": False,
        },
        "successor_authority": {
            "domain_owner": "librarian",
            "decision": "authorized",
            "recovery_mode": "exact_non_destructive",
            "independent_validator_required": True,
            "user_confirmation_required": False,
            "predecessor_bytes_must_remain_exact": True,
        },
        "cleared_context": [
            "design",
            "red",
            "implementation",
            "candidate",
            "review",
            "verification",
            "commit",
            "closure",
            "approval",
        ],
    }


def materialize_synthetic_request_mismatch_chain(root: Path) -> dict[str, object]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
    ).stdout.strip()
    root_id = f"{ITERATION_ID}-root"
    drift_id = f"{ITERATION_ID}-drift"
    successor_id = f"{ITERATION_ID}-successor"
    root_path, root_raw = write_private_workflow(
        root, root_id, synthetic_root_events(head, root_id)
    )
    root_relative = root_path.relative_to(root)
    root_manifest, root_blob = quarantine_manifest(
        predecessor_path=root_relative,
        predecessor_raw=root_raw,
        successor_iteration_id=drift_id,
        base_head=head,
        parser_failure_code="reviewed_commands_missing",
        failing_event_ordinal=6,
    )
    root_manifest_path = (
        f'.github/iteration-quarantine/{root_manifest["predecessor_sha256"]}.json'
    )
    stage(root, "scripts/repository_gate.py", GATE.read_bytes())
    stage(root, root_manifest_path, root_blob)

    drift_baseline = single_recovery_baseline(
        head=head,
        request=SYNTHETIC_DRIFTED_REQUEST,
        acceptance_sha256=root_manifest["acceptance_sha256"],
        predecessor_manifest=root_manifest,
    )
    drift_path, drift_raw = write_private_workflow(
        root, drift_id, [event("BASELINED", drift_baseline) | {"iteration_id": drift_id}]
    )
    root_request_sha256 = hashlib.sha256(SYNTHETIC_ROOT_REQUEST.encode()).hexdigest()
    actual_request_sha256 = hashlib.sha256(SYNTHETIC_DRIFTED_REQUEST.encode()).hexdigest()
    drift_manifest, drift_blob = quarantine_manifest(
        predecessor_path=drift_path.relative_to(root),
        predecessor_raw=drift_raw,
        successor_iteration_id=successor_id,
        base_head=head,
        parser_failure_code="recovery_request_mismatch",
        failing_event_ordinal=1,
        request_sha256=root_request_sha256,
        actual_request_sha256=actual_request_sha256,
    )
    drift_manifest_path = (
        f'.github/iteration-quarantine/{drift_manifest["predecessor_sha256"]}.json'
    )
    stage(root, drift_manifest_path, drift_blob)
    chain = [
        recovery_chain_item(
            root_manifest,
            root_blob,
            state="present_untracked_exact_no_authority",
            baseline_sha256=hashlib.sha256(root_blob).hexdigest(),
        ),
        recovery_chain_item(
            drift_manifest,
            drift_blob,
            state="absent_before_recovery_edit",
            baseline_sha256=None,
        ),
    ]
    successor_baseline = recovery_v2_baseline(
        head=head,
        iteration_ids=[root_id, drift_id, successor_id],
        chain=chain,
    )
    successor_path, successor_raw = write_private_workflow(
        root,
        successor_id,
        [event("BASELINED", successor_baseline) | {"iteration_id": successor_id}],
    )
    return {
        "root_path": root_path,
        "drift_path": drift_path,
        "successor_path": successor_path,
        "successor_raw": successor_raw,
        "root_manifest": root_manifest,
        "root_blob": root_blob,
        "drift_manifest": drift_manifest,
        "drift_blob": drift_blob,
        "root_manifest_path": root_manifest_path,
        "drift_manifest_path": drift_manifest_path,
        "chain": chain,
        "iteration_ids": [root_id, drift_id, successor_id],
        "successor_baseline": successor_baseline,
        "predecessor_paths": [root_path, drift_path],
    }


def materialize_synthetic_invalid_transition_chain(root: Path) -> dict[str, object]:
    fixture = materialize_synthetic_request_mismatch_chain(root)
    invalid_path = fixture["successor_path"]
    invalid_id = invalid_path.stem
    invalid_path, invalid_raw = write_private_workflow(
        root,
        invalid_id,
        [
            event("BASELINED", fixture["successor_baseline"])
            | {"iteration_id": invalid_id},
            {
                "iteration_id": invalid_id,
                "state": "RED",
                "evidence": {"commands": [red_event()["evidence"]]},
            },
        ],
    )
    recovered_id = f"{invalid_id}-recovered"
    root_request_sha256 = hashlib.sha256(SYNTHETIC_ROOT_REQUEST.encode()).hexdigest()
    invalid_manifest, invalid_blob = quarantine_manifest(
        predecessor_path=invalid_path.relative_to(root),
        predecessor_raw=invalid_raw,
        successor_iteration_id=recovered_id,
        base_head=fixture["root_manifest"]["base_head"],
        parser_failure_code="invalid_state_transition",
        failing_event_ordinal=2,
        request_sha256=root_request_sha256,
        actual_state="RED",
        expected_state="DESIGNED",
    )
    invalid_manifest_path = (
        f'.github/iteration-quarantine/{invalid_manifest["predecessor_sha256"]}.json'
    )
    stage(root, invalid_manifest_path, invalid_blob)
    chain = [
        *fixture["chain"],
        recovery_chain_item(
            invalid_manifest,
            invalid_blob,
            state="absent_before_recovery_edit",
            baseline_sha256=None,
        ),
    ]
    recovered_baseline = recovery_v2_baseline(
        head=fixture["root_manifest"]["base_head"],
        iteration_ids=[*fixture["iteration_ids"], recovered_id],
        chain=chain,
    )
    recovered_path, recovered_raw = write_private_workflow(
        root,
        recovered_id,
        [event("BASELINED", recovered_baseline) | {"iteration_id": recovered_id}],
    )
    return {
        **fixture,
        "invalid_path": invalid_path,
        "invalid_manifest": invalid_manifest,
        "invalid_manifest_path": invalid_manifest_path,
        "successor_path": recovered_path,
        "successor_raw": recovered_raw,
        "predecessor_paths": [*fixture["predecessor_paths"], invalid_path],
    }


def materialize_panel_quarantine_chain(root: Path) -> dict[str, Path]:
    ledgers: dict[str, Path] = {}
    for iteration_id in PANEL_ITERATION_IDS:
        target = root / ".github" / "memory" / "iterations" / f"{iteration_id}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((PANEL_ITERATIONS / target.name).read_bytes())
        ledgers[iteration_id] = target
    manifests = {
        ORIGINAL_PANEL_DIGEST: PANEL_QUARANTINE / f"{ORIGINAL_PANEL_DIGEST}.json",
        R1_PANEL_DIGEST: R1_REQUEST_MISMATCH_FIXTURE,
        R2_PANEL_DIGEST: R2_REQUEST_MISMATCH_FIXTURE,
        R3_PANEL_DIGEST: R3_INVALID_TRANSITION_FIXTURE,
    }
    stage(root, "scripts/repository_gate.py", GATE.read_bytes())
    for digest, source in manifests.items():
        stage(root, f".github/iteration-quarantine/{digest}.json", source.read_bytes())
    return ledgers


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
    reviewer_names: set[str] = set()
    for item in events:
        if item["state"] != "REVIEWED":
            continue
        evidence = item["evidence"]
        assert isinstance(evidence, dict)
        reviewers = evidence["reviewers"]
        assert isinstance(reviewers, list)
        for reviewer in reviewers:
            assert isinstance(reviewer, dict)
            reviewer_name = reviewer.get("reviewer")
            assert isinstance(reviewer_name, str)
            reviewer_names.add(reviewer_name)
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
    legacy = LEGACY_SUPERSEDED_FIXTURE
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


def test_immutable_migration_fixtures_bind_every_declared_digest() -> None:
    """Candidate-local bytes, not Git metadata or ignored ledgers, authorize migrations."""
    module = load_gate_module()
    raw_records = [
        LEGACY_SUPERSEDED_FIXTURE,
        *legacy_reviewer_records(),
    ]
    actual = [hashlib.sha256(raw.encode()).hexdigest() for raw in raw_records]
    declared = [
        *(record.raw_sha256 for record in module.RepositoryGate._MIGRATIONS),
        *(record.raw_sha256 for record in module.RepositoryGate._REVIEWER_MIGRATIONS),
    ]

    assert actual == declared


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
    candidate = event(
        "CANDIDATE_FROZEN",
        {
            "tree": "b" * 40,
            "staged_diff_sha256": HASH,
            "owned_paths": ["scripts/repository_gate.py"],
            "acceptance_sha256": HASH,
        },
    )
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
    source = legacy_reviewer_migration_source()
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
def test_nonapproved_review_is_a_valid_terminal_and_only_authorizes_red(
    git_repo: Path, disposition: str
):
    events = valid_events(git_repo, "REVIEWED")
    events[5]["evidence"]["reviewers"][0]["disposition"] = disposition
    events[5]["evidence"]["reviewers"][0]["findings"] = [
        {"claim": "gate enforced", "detail": "candidate must change"}
    ]
    ledger = write_ledger(git_repo, events)
    ledger_before = ledger.read_bytes()

    verified_terminal = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert verified_terminal.returncode == 0, verified_terminal.stderr

    proposed_path = git_repo / "out" / "tests" / "review-recovery-event.json"
    proposed_path.parent.mkdir(parents=True)
    proposed_path.write_text(json.dumps(red_event(), separators=(",", ":")))
    accepted_red = run_gate(
        git_repo,
        "validate-append",
        "--ledger",
        str(ledger),
        "--event",
        str(proposed_path),
    )

    assert accepted_red.returncode == 0, accepted_red.stderr
    assert accepted_red.stdout == "[repository-gate] next state: IMPLEMENTED\n"
    assert ledger.read_bytes() == ledger_before

    proposed_path.write_text(json.dumps(verified_event(events[4]), separators=(",", ":")))
    refused_verified = run_gate(
        git_repo,
        "validate-append",
        "--ledger",
        str(ledger),
        "--event",
        str(proposed_path),
    )

    assert refused_verified.returncode == 1
    assert "expected RED" in refused_verified.stderr
    assert ledger.read_bytes() == ledger_before


@pytest.mark.parametrize("follower", ["RED", "VERIFIED"])
def test_nonapproved_review_only_authorizes_immediate_red(
    git_repo: Path, follower: str
) -> None:
    events = valid_events(git_repo, "REVIEWED")
    events[5]["evidence"]["reviewers"][0]["disposition"] = "changes_requested"
    events[5]["evidence"]["reviewers"][0]["findings"] = [
        {"claim": "candidate behavior", "detail": "executable evidence required"}
    ]
    events.append(red_event() if follower == "RED" else verified_event(events[4]))
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    if follower == "RED":
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode == 1
        assert "ledger state order is invalid" in result.stderr.lower()


def test_mixed_review_dispositions_require_red(git_repo: Path):
    events = valid_events(git_repo, "REVIEWED")
    second = json.loads(json.dumps(events[5]["evidence"]["reviewers"][0]))
    second["reviewer"] = "second_reviewer"
    second["disposition"] = "changes_requested"
    second["findings"] = [{"claim": "gate enforced", "detail": "candidate must change"}]
    events[5]["evidence"]["reviewers"].append(second)
    ledger = write_ledger(git_repo, events)

    terminal = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert terminal.returncode == 0, terminal.stderr

    proposed_path = git_repo / "out" / "tests" / "mixed-review-recovery-event.json"
    proposed_path.parent.mkdir(parents=True)
    proposed_path.write_text(json.dumps(red_event(), separators=(",", ":")))
    recovery = run_gate(
        git_repo,
        "validate-append",
        "--ledger",
        str(ledger),
        "--event",
        str(proposed_path),
    )

    assert recovery.returncode == 0, recovery.stderr
    assert recovery.stdout == "[repository-gate] next state: IMPLEMENTED\n"


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


@pytest.mark.parametrize(
    ("freeze_before_red", "red_cycles"),
    [(True, 2), (False, 1)],
    ids=["frozen-candidate-two-recoveries", "implemented-one-recovery"],
)
def test_precommit_red_can_restart_implementation_cycles(
    git_repo: Path, freeze_before_red: bool, red_cycles: int
):
    events = valid_events(git_repo, "IMPLEMENTED")
    if freeze_before_red:
        events.append(candidate_event(git_repo))
    for _ in range(red_cycles):
        events.extend([red_event(), implemented_event()])
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("proposed_state", "expected_returncode"),
    [("DESIGNED", 0), ("RED", 1)],
)
def test_prospective_append_validates_state_before_writing(
    git_repo: Path, proposed_state: str, expected_returncode: int
) -> None:
    ledger = write_ledger(git_repo, valid_events(git_repo, "BASELINED"))
    ledger_before = ledger.read_bytes()
    proposed = designed_event() if proposed_state == "DESIGNED" else red_event()
    event_path = git_repo / "out" / "tests" / "prospective-event.json"
    event_path.parent.mkdir(parents=True)
    event_path.write_text(json.dumps(proposed, separators=(",", ":")))

    result = run_gate(
        git_repo,
        "validate-append",
        "--ledger",
        str(ledger),
        "--event",
        str(event_path),
    )

    assert result.returncode == expected_returncode, result.stderr
    assert ledger.read_bytes() == ledger_before
    if proposed_state == "RED":
        assert "expected DESIGNED" in result.stderr
    else:
        assert result.stdout == "[repository-gate] next state: RED\n"


@pytest.mark.parametrize(
    ("proposed_state", "commit_kind", "expected_returncode"),
    [
        ("COMMITTED", "actual", 0),
        ("COMMITTED", "malformed", 1),
        ("COMMITTED", "nonmatching", 1),
        ("RED", "actual", 0),
    ],
)
def test_prospective_transition_validates_after_candidate_is_committed(
    git_repo: Path, proposed_state: str, commit_kind: str, expected_returncode: int,
) -> None:
    previous_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=git_repo, text=True, capture_output=True, check=True,
    ).stdout.strip()
    stage(git_repo, "candidate.txt", b"candidate content\n")
    events = valid_events(git_repo, "VERIFIED")
    ledger = write_ledger(git_repo, events)
    ledger_before = ledger.read_bytes()
    subprocess.run(["git", "commit", "-qm", "candidate"], cwd=git_repo, check=True)
    actual_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=git_repo, text=True, capture_output=True, check=True,
    ).stdout.strip()
    candidate_tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=git_repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    proposed_commit = {
        "actual": actual_commit,
        "malformed": "not-a-commit",
        "nonmatching": previous_head,
    }[commit_kind]
    proposed = (
        event(
            "COMMITTED",
            {
                "commit": proposed_commit,
                "tree": candidate_tree,
                "candidate_tree": candidate_tree,
            },
        )
        if proposed_state == "COMMITTED"
        else red_event()
    )
    event_path = git_repo / "out" / "tests" / "prospective-committed.json"
    event_path.parent.mkdir(parents=True)
    event_path.write_text(json.dumps(proposed, separators=(",", ":")))

    standalone = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))
    assert standalone.returncode != 0
    assert "candidate staged diff hash is stale" in standalone.stderr

    result = run_gate(
        git_repo,
        "validate-append",
        "--ledger",
        str(ledger),
        "--event",
        str(event_path),
    )

    assert result.returncode == expected_returncode, result.stderr
    assert ledger.read_bytes() == ledger_before
    if expected_returncode == 0:
        expected_next = "CLOSED" if proposed_state == "COMMITTED" else "IMPLEMENTED"
        assert result.stdout == f"[repository-gate] next state: {expected_next}\n"


def test_prospective_append_validates_first_baseline_without_writing(
    git_repo: Path,
) -> None:
    ledger = (
        git_repo
        / ".github"
        / "memory"
        / "iterations"
        / f"{ITERATION_ID}-first.md"
    )
    ledger.parent.mkdir(parents=True)
    ledger.write_text(f"# Iteration {ledger.stem}\n\n")
    ledger_before = ledger.read_bytes()
    proposed = baseline_event() | {"iteration_id": ledger.stem}
    event_path = git_repo / "out" / "tests" / "prospective-event.json"
    event_path.parent.mkdir(parents=True)
    event_path.write_text(json.dumps(proposed, separators=(",", ":")))

    result = run_gate(
        git_repo,
        "validate-append",
        "--ledger",
        str(ledger),
        "--event",
        str(event_path),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "[repository-gate] next state: DESIGNED\n"
    assert ledger.read_bytes() == ledger_before


@pytest.mark.parametrize(
    "invalid_input", ["hostile-event", "wrong-iteration", "invalid-prefix"]
)
def test_prospective_append_rejects_invalid_input_without_disclosure(
    git_repo: Path, invalid_input: str
) -> None:
    hostile = "private-proposed-event-content"
    events = valid_events(git_repo, "BASELINED")
    proposed = designed_event()
    if invalid_input == "hostile-event":
        proposed["evidence"][hostile] = hostile
    elif invalid_input == "wrong-iteration":
        proposed["iteration_id"] = hostile
    else:
        events.append(red_event())
    ledger = write_ledger(git_repo, events)
    ledger_before = ledger.read_bytes()
    event_path = git_repo / "out" / "tests" / "prospective-event.json"
    event_path.parent.mkdir(parents=True)
    event_path.write_text(json.dumps(proposed, separators=(",", ":")))

    result = run_gate(
        git_repo,
        "validate-append",
        "--ledger",
        str(ledger),
        "--event",
        str(event_path),
    )

    assert result.returncode == 1
    assert hostile not in result.stdout + result.stderr
    assert ledger.read_bytes() == ledger_before


@pytest.mark.parametrize("boundary", ["duplicate-red", "committed"])
def test_red_cannot_restart_without_implementation_or_after_commit(
    git_repo: Path, boundary: str
):
    terminal = "IMPLEMENTED" if boundary == "duplicate-red" else "COMMITTED"
    events = valid_events(git_repo, terminal)
    events.extend([red_event(), red_event()] if boundary == "duplicate-red" else [red_event()])
    ledger = write_ledger(git_repo, events)

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(ledger))

    assert result.returncode == 1
    assert "state order" in result.stderr.lower()


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


def test_one_edge_recovery_rejects_request_drift(git_repo: Path) -> None:
    fixture = materialize_synthetic_request_mismatch_chain(git_repo)
    subprocess.run(
        ["git", "reset", "-q", "--", fixture["drift_manifest_path"]],
        cwd=git_repo,
        check=True,
    )

    result = run_gate(
        git_repo, "verify-ledger", "--ledger", str(fixture["drift_path"])
    )

    assert result.returncode == 1
    assert "request" in result.stderr.lower()


@pytest.mark.parametrize("cleared_context_valid", [True, False])
def test_recovery_v2_clears_every_predecessor_context(
    git_repo: Path, cleared_context_valid: bool
) -> None:
    fixture = materialize_synthetic_request_mismatch_chain(git_repo)
    root_manifest = fixture["root_manifest"]
    root_blob = fixture["root_blob"]
    root_id = root_manifest["predecessor_iteration_id"]
    successor_id = root_manifest["successor_iteration_id"]
    head = root_manifest["base_head"]
    baseline = recovery_v2_baseline(
        head=head,
        iteration_ids=[root_id, successor_id],
        chain=[
            recovery_chain_item(
                root_manifest,
                root_blob,
                state="present_untracked_exact_no_authority",
                baseline_sha256=hashlib.sha256(root_blob).hexdigest(),
            )
        ],
    )
    if not cleared_context_valid:
        baseline["cleared_context"].remove("review")
    successor_path, _raw = write_private_workflow(
        git_repo,
        successor_id,
        [event("BASELINED", baseline) | {"iteration_id": successor_id}],
    )
    subprocess.run(
        ["git", "reset", "-q", "--", fixture["drift_manifest_path"]],
        cwd=git_repo,
        check=True,
    )

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(successor_path))

    assert (result.returncode == 0) is cleared_context_valid, result.stderr


def test_finite_request_mismatch_quarantine_bootstraps_only_successor(
    git_repo: Path,
) -> None:
    fixture = materialize_synthetic_request_mismatch_chain(git_repo)

    predecessor_results = [
        run_gate(git_repo, "verify-ledger", "--ledger", str(fixture[key]))
        for key in ("root_path", "drift_path")
    ]
    successor_result = run_gate(
        git_repo, "verify-ledger", "--ledger", str(fixture["successor_path"])
    )

    assert all(result.returncode != 0 for result in predecessor_results)
    assert successor_result.returncode == 0, successor_result.stderr


def test_finite_invalid_transition_quarantine_bootstraps_only_successor(
    git_repo: Path,
) -> None:
    fixture = materialize_synthetic_invalid_transition_chain(git_repo)

    predecessor_result = run_gate(
        git_repo, "verify-ledger", "--ledger", str(fixture["invalid_path"])
    )
    successor_result = run_gate(
        git_repo, "verify-ledger", "--ledger", str(fixture["successor_path"])
    )

    assert predecessor_result.returncode != 0
    assert successor_result.returncode == 0, successor_result.stderr


def test_quarantine_executes_only_candidate_index_gate(git_repo: Path) -> None:
    fixture = materialize_synthetic_request_mismatch_chain(git_repo)
    stage(
        git_repo,
        "scripts/repository_gate.py",
        GATE.read_bytes() + b"\n# candidate-index mismatch\n",
    )

    result = run_gate(
        git_repo, "verify-ledger", "--ledger", str(fixture["successor_path"])
    )

    assert result.returncode == 1
    assert "executing gate differs from candidate index" in result.stderr.lower()


def test_committed_quarantine_manifest_is_immutable(git_repo: Path) -> None:
    fixture = materialize_synthetic_request_mismatch_chain(git_repo)
    subprocess.run(
        ["git", "commit", "-qm", "synthetic quarantine chain"], cwd=git_repo, check=True
    )
    manifest_path = git_repo / fixture["drift_manifest_path"]
    stage(
        git_repo,
        str(manifest_path.relative_to(git_repo)),
        manifest_path.read_bytes() + b"\n",
    )

    result = run_gate(
        git_repo, "verify-ledger", "--ledger", str(fixture["successor_path"])
    )

    assert result.returncode == 1
    assert "manifest is immutable" in result.stderr.lower()


@pytest.mark.parametrize(
    "materialize_chain",
    [
        materialize_synthetic_request_mismatch_chain,
        materialize_synthetic_invalid_transition_chain,
    ],
    ids=["request-mismatch", "invalid-transition"],
)
def test_committed_quarantine_chain_works_without_private_predecessors(
    git_repo: Path, materialize_chain,
) -> None:
    fixture = materialize_chain(git_repo)
    subprocess.run(
        ["git", "commit", "-qm", "synthetic quarantine chain"], cwd=git_repo, check=True
    )
    for predecessor in fixture["predecessor_paths"]:
        predecessor.unlink()
    clone = git_repo.parent / (git_repo.name + "-shared")
    try:
        subprocess.run(
            ["git", "clone", "-q", "--shared", str(git_repo), str(clone)], check=True
        )
        successor = (
            clone
            / ".github"
            / "memory"
            / "iterations"
            / fixture["successor_path"].name
        )
        successor.parent.mkdir(parents=True)
        successor.write_bytes(fixture["successor_raw"])

        result = run_gate(clone, "verify-ledger", "--ledger", str(successor))

        assert result.returncode == 0, result.stderr
    finally:
        shutil.rmtree(clone, ignore_errors=True)


@pytest.mark.skipif(
    not PRIVATE_PANEL_CHAIN_AVAILABLE,
    reason="private predecessor ledgers are intentionally absent from shared clones",
)
def test_exact_private_predecessors_remain_invalid_before_r4_manifest(
    git_repo: Path,
):
    """Exact local bytes remain an audit control, never a tracked test fixture."""
    ledgers = materialize_panel_quarantine_chain(git_repo)
    predecessor = ledgers["20260828-panel-agent-platform"]
    r1 = ledgers["20260828-panel-agent-platform-r1"]
    r2 = ledgers["20260828-panel-agent-platform-r2"]
    r3 = ledgers["20260828-panel-agent-platform-r3"]
    successor = ledgers["20260828-panel-agent-platform-r4"]
    assert hashlib.sha256(predecessor.read_bytes()).hexdigest() == ORIGINAL_PANEL_DIGEST
    assert hashlib.sha256(r1.read_bytes()).hexdigest() == R1_PANEL_DIGEST
    assert hashlib.sha256(r2.read_bytes()).hexdigest() == R2_PANEL_DIGEST
    assert hashlib.sha256(r3.read_bytes()).hexdigest() == R3_PANEL_DIGEST
    assert subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=git_repo, check=False
    ).returncode == 1, "both uncommitted manifests and the executing gate must be staged"

    predecessor_results = [
        run_gate(git_repo, "verify-ledger", "--ledger", str(path))
        for path in (predecessor, r1, r2, r3)
    ]
    successor_result = run_gate(git_repo, "verify-ledger", "--ledger", str(successor))
    discovery_result = run_gate(git_repo, "verify-ledger")
    successor_before = successor.read_bytes()
    proposed = implemented_event() | {"iteration_id": successor.stem}
    proposed_path = git_repo / "out" / "tests" / "r4-proposed-event.json"
    proposed_path.parent.mkdir(parents=True)
    proposed_path.write_text(json.dumps(proposed, separators=(",", ":")))
    prospective_result = run_gate(
        git_repo,
        "validate-append",
        "--ledger",
        str(successor),
        "--event",
        str(proposed_path),
    )

    assert all(result.returncode != 0 for result in predecessor_results), (
        "quarantine never makes either raw predecessor valid"
    )
    assert successor_result.returncode != 0
    assert discovery_result.returncode != 0
    assert prospective_result.returncode != 0
    assert successor.read_bytes() == successor_before


@pytest.mark.skipif(
    not PRIVATE_PANEL_CHAIN_AVAILABLE,
    reason="private predecessor ledgers are intentionally absent from shared clones",
)
def test_exact_local_quarantine_manifests_bind_first_failures() -> None:
    pattern = re.compile(
        rb"^```workflow-event[ \t]*$\n(.*?)\n^```[ \t]*(?:\n|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    root_raw = (PANEL_ITERATIONS / "20260828-panel-agent-platform.md").read_bytes()
    root_baseline = json.loads(next(pattern.finditer(root_raw)).group(1))["evidence"]
    root_request_sha256 = hashlib.sha256(root_baseline["request"].encode()).hexdigest()
    for iteration_id, manifest_path in (
        ("20260828-panel-agent-platform-r1", R1_REQUEST_MISMATCH_FIXTURE),
        ("20260828-panel-agent-platform-r2", R2_REQUEST_MISMATCH_FIXTURE),
    ):
        raw = (PANEL_ITERATIONS / f"{iteration_id}.md").read_bytes()
        text = raw.decode()
        failing = next(WORKFLOW_EVENT_PATTERN.finditer(text))
        separator_end = failing.end() + int(text[failing.end() :].startswith("\n"))
        baseline = json.loads(failing.group(1))["evidence"]
        manifest = json.loads(manifest_path.read_bytes())

        assert manifest["parser_failure_code"] == "recovery_request_mismatch"
        assert manifest["failing_event_ordinal"] == 1
        assert manifest["trusted_prefix_event_count"] == 0
        assert manifest["trusted_prefix_sha256"] == hashlib.sha256(b"").hexdigest()
        assert hashlib.sha256((failing.group(1) + "\n").encode()).hexdigest() == (
            manifest["failing_raw_block_sha256"]
        )
        assert hashlib.sha256(text[failing.start() : separator_end].encode()).hexdigest() == (
            manifest["failing_full_fence_sha256"]
        )
        assert manifest["request_sha256"] == root_request_sha256
        assert manifest["actual_request_sha256"] == hashlib.sha256(
            baseline["request"].encode()
        ).hexdigest()
        assert manifest["actual_request_sha256"] != manifest["request_sha256"]
        assert baseline["acceptance"] == root_baseline["acceptance"]
        assert manifest["acceptance_sha256"] == PANEL_ACCEPTANCE_SHA256

    r3_raw = (PANEL_ITERATIONS / "20260828-panel-agent-platform-r3.md").read_text()
    r3_matches = list(WORKFLOW_EVENT_PATTERN.finditer(r3_raw))
    r3_baseline = json.loads(r3_matches[0].group(1))["evidence"]
    assert r3_baseline["request"] == root_baseline["request"]
    assert r3_baseline["acceptance"] == root_baseline["acceptance"]
    assert r3_baseline["cleared_context"] == [
        "design", "red", "implementation", "candidate", "review",
        "verification", "commit", "closure", "approval",
    ]
    r3_manifest_blob = R3_INVALID_TRANSITION_FIXTURE.read_bytes()
    r3_manifest = json.loads(r3_manifest_blob)
    r3_failing = r3_matches[1]
    separator_end = r3_failing.end() + int(r3_raw[r3_failing.end() :].startswith("\n"))
    assert len(r3_manifest_blob) == 1000
    assert hashlib.sha256(r3_manifest_blob).hexdigest() == (
        "497d94c1d687fa32111cfefa1c5af71bf9d1e253da3fa5debe7f17a1b9cd9225"
    )
    assert r3_manifest["parser_failure_code"] == "invalid_state_transition"
    assert r3_manifest["failing_event_ordinal"] == 2
    assert r3_manifest["actual_state"] == "RED"
    assert r3_manifest["expected_state"] == "DESIGNED"
    assert "actual_request_sha256" not in r3_manifest
    assert hashlib.sha256((r3_failing.group(1) + "\n").encode()).hexdigest() == (
        r3_manifest["failing_raw_block_sha256"]
    )
    assert hashlib.sha256(
        r3_raw[r3_failing.start() : separator_end].encode()
    ).hexdigest() == r3_manifest["failing_full_fence_sha256"]
    assert hashlib.sha256(r3_matches[0].group(0).encode()).hexdigest() == (
        r3_manifest["trusted_prefix_sha256"]
    )
    assert r3_manifest["request_sha256"] == root_request_sha256
    assert r3_manifest["acceptance_sha256"] == PANEL_ACCEPTANCE_SHA256

    r4_raw = (PANEL_ITERATIONS / "20260828-panel-agent-platform-r4.md").read_text()
    r4_baseline = json.loads(next(WORKFLOW_EVENT_PATTERN.finditer(r4_raw)).group(1))["evidence"]
    assert r4_baseline["request"] == root_baseline["request"]
    assert r4_baseline["acceptance"] == root_baseline["acceptance"]
    assert r4_baseline["cleared_context"] == r3_baseline["cleared_context"]


@pytest.mark.parametrize(
    "abuse",
    [
        "wrong-ordinal",
        "equal-request",
        "wrong-root-request",
        "wrong-raw-hash",
        "wrong-fence-hash",
        "synthetic-prefix",
        "unknown-code",
        "wildcard-code",
        "runtime-config",
        "self-migration",
        "missing-predecessor",
        "worktree-only-manifest",
        "successor-request-drift",
        "acceptance-changed",
        "inherited-context-reused",
        "planned-manifest-mismatch",
        "fork",
        "cycle",
        "duplicate-successor",
    ],
)
def test_synthetic_quarantine_chain_rejects_every_abuse(
    git_repo: Path, abuse: str
) -> None:
    fixture = materialize_synthetic_request_mismatch_chain(git_repo)
    root_manifest_path = git_repo / fixture["root_manifest_path"]
    drift_manifest_path = git_repo / fixture["drift_manifest_path"]
    root_manifest = json.loads(root_manifest_path.read_bytes())
    drift_manifest = json.loads(drift_manifest_path.read_bytes())
    successor = fixture["successor_path"]

    field_mutations = {
        "wrong-ordinal": ("failing_event_ordinal", 2),
        "equal-request": ("actual_request_sha256", drift_manifest["request_sha256"]),
        "wrong-root-request": ("request_sha256", "0" * 64),
        "wrong-raw-hash": ("failing_raw_block_sha256", "0" * 64),
        "wrong-fence-hash": ("failing_full_fence_sha256", "0" * 64),
        "synthetic-prefix": ("trusted_prefix_sha256", "0" * 64),
        "unknown-code": ("parser_failure_code", "arbitrary_failure"),
        "wildcard-code": ("parser_failure_code", "*"),
    }
    if abuse in field_mutations:
        field, value = field_mutations[abuse]
        drift_manifest[field] = value
        stage(
            git_repo,
            str(drift_manifest_path.relative_to(git_repo)),
            compact_json_bytes(drift_manifest),
        )
    elif abuse in {"runtime-config", "self-migration"}:
        field = "failure_codes_path" if abuse == "runtime-config" else "migration"
        drift_manifest[field] = "runtime-authority"
        stage(
            git_repo,
            str(drift_manifest_path.relative_to(git_repo)),
            compact_json_bytes(drift_manifest),
        )
    elif abuse == "missing-predecessor":
        fixture["drift_path"].unlink()
    elif abuse == "worktree-only-manifest":
        subprocess.run(
            ["git", "reset", "-q", "--", str(drift_manifest_path.relative_to(git_repo))],
            cwd=git_repo,
            check=True,
        )
    elif abuse in {
        "successor-request-drift",
        "acceptance-changed",
        "inherited-context-reused",
        "planned-manifest-mismatch",
    }:
        text = successor.read_text()
        match = WORKFLOW_EVENT_PATTERN.search(text)
        assert match is not None
        envelope = json.loads(match.group(1))
        evidence = envelope["evidence"]
        if abuse == "successor-request-drift":
            evidence["request"] = SYNTHETIC_DRIFTED_REQUEST
        elif abuse == "acceptance-changed":
            evidence["acceptance"].append("expanded acceptance")
        elif abuse == "inherited-context-reused":
            evidence["cleared_context"].remove("review")
        else:
            evidence["recovery_chain"][-1]["manifest_sha256_planned"] = "0" * 64
        successor.write_text(
            text[: match.start(1)]
            + json.dumps(envelope, separators=(",", ":"))
            + text[match.end(1) :]
        )
    elif abuse == "fork":
        root_manifest["successor_iteration_id"] += "-fork"
        stage(
            git_repo,
            str(root_manifest_path.relative_to(git_repo)),
            compact_json_bytes(root_manifest),
        )
    elif abuse == "cycle":
        drift_manifest["successor_iteration_id"] = root_manifest["predecessor_iteration_id"]
        stage(
            git_repo,
            str(drift_manifest_path.relative_to(git_repo)),
            compact_json_bytes(drift_manifest),
        )
    else:
        root_manifest["successor_iteration_id"] = drift_manifest["successor_iteration_id"]
        stage(
            git_repo,
            str(root_manifest_path.relative_to(git_repo)),
            compact_json_bytes(root_manifest),
        )

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(successor))

    assert result.returncode != 0, f"quarantine abuse was accepted: {abuse}"


@pytest.mark.parametrize(
    "abuse",
    [
        "wrong-actual-state",
        "wrong-expected-state",
        "equal-states",
        "missing-actual-state",
        "unexpected-field",
        "wrong-root-request",
        "planned-size-mismatch",
    ],
)
def test_invalid_transition_quarantine_rejects_every_variant_abuse(
    git_repo: Path, abuse: str
) -> None:
    fixture = materialize_synthetic_invalid_transition_chain(git_repo)
    manifest_path = git_repo / fixture["invalid_manifest_path"]
    manifest = json.loads(manifest_path.read_bytes())
    successor = fixture["successor_path"]
    if abuse == "planned-size-mismatch":
        text = successor.read_text()
        match = WORKFLOW_EVENT_PATTERN.search(text)
        assert match is not None
        envelope = json.loads(match.group(1))
        envelope["evidence"]["recovery_chain"][-1]["manifest_size_planned"] += 1
        successor.write_text(
            text[: match.start(1)]
            + json.dumps(envelope, separators=(",", ":"))
            + text[match.end(1) :]
        )
    else:
        if abuse == "wrong-actual-state":
            manifest["actual_state"] = "IMPLEMENTED"
        elif abuse == "wrong-expected-state":
            manifest["expected_state"] = "IMPLEMENTED"
        elif abuse == "equal-states":
            manifest["actual_state"] = manifest["expected_state"]
        elif abuse == "missing-actual-state":
            del manifest["actual_state"]
        elif abuse == "unexpected-field":
            manifest["replacement_meaning"] = "arbitrary prose"
        else:
            manifest["request_sha256"] = "0" * 64
        stage(
            git_repo,
            str(manifest_path.relative_to(git_repo)),
            compact_json_bytes(manifest),
        )

    result = run_gate(git_repo, "verify-ledger", "--ledger", str(successor))

    assert result.returncode != 0, f"invalid-transition abuse was accepted: {abuse}"


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


def test_prospective_authorization_failure_is_finite_and_typed() -> None:
    module = load_gate_module()
    manifest = json.loads(
        (
            PANEL_QUARANTINE
            / "fb2c2203015e5c0c4188b5ed589321be4eddbe9bf19d6637378df456613ff364.json"
        ).read_bytes()
    )
    parsed = module._QuarantineManifest.model_validate(manifest)
    assert parsed.parser_failure_code == "prospective_authorization_failed"
    for mutation in ("*", "missing_prospective_authorization", "arbitrary_failure"):
        invalid = {**manifest, "parser_failure_code": mutation}
        with pytest.raises(ValueError):
            module._QuarantineManifest.model_validate(invalid)


def test_validate_bootstrap_is_the_integrated_gate_cli() -> None:
    source = GATE.read_text()
    assert 'subparsers.add_parser("validate-bootstrap")' in source
    assert "bootstrap_validator" not in source
    assert "prospective_authorization_failed" in source


BOOTSTRAP_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
BOOTSTRAP_FORBIDDEN_AUTHORITY = [
    "workflow_event",
    "product_source",
    "candidate",
    "review",
    "verification",
    "commit",
    "closure",
]
BOOTSTRAP_FAILURES = {
    "ordinary_baseline_schema_unsupported": (
        b"[repository-gate] FAIL: BASELINED evidence contains unsupported fields\n"
    ),
    "recovery_baseline_chain_invalid": (
        b"[repository-gate] FAIL: recovery BASELINED chain is invalid\n"
    ),
}


def bootstrap_old_gate_bytes() -> bytes:
    return b"""#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["validate-append"])
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--event", type=Path, required=True)
    arguments = parser.parse_args()
    event = json.loads(arguments.event.read_bytes())
    if arguments.ledger.read_bytes() != b"":
        print("[repository-gate] FAIL: replay prefix is invalid", file=sys.stderr)
        return 1
    listed = subprocess.run(
        ["git", "ls-files", "--", ".github/iteration-quarantine/*.json"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    if listed:
        message = "recovery BASELINED chain is invalid"
    else:
        message = "BASELINED evidence contains unsupported fields"
    print(f"[repository-gate] FAIL: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
"""


def bootstrap_canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode() + b"\n"


def bootstrap_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def bootstrap_git(
    root: Path,
    *arguments: str,
    input_bytes: bytes | None = None,
) -> bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        input=input_bytes,
        capture_output=True,
        check=True,
    )
    return result.stdout


def bootstrap_tree_diff_sha256(root: Path, base: str, tree: str) -> str:
    return bootstrap_hash(
        bootstrap_git(root, "diff", "--binary", "--no-ext-diff", base, tree)
    )


def bootstrap_decisions(core: dict[str, object]) -> list[dict[str, str]]:
    core_sha256 = bootstrap_hash(bootstrap_canonical(core))
    decisions = []
    for role in ("librarian", "validator"):
        payload = {
            "role": role,
            "decision": "approved",
            "control_core_sha256": core_sha256,
        }
        decisions.append(
            {**payload, "decision_sha256": bootstrap_hash(bootstrap_canonical(payload))}
        )
    return decisions


def bootstrap_record(core: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "control_type": "quarantine_bootstrap_repair",
        "core": core,
        "approvals": bootstrap_decisions(core),
    }


def bootstrap_manifest(
    *,
    predecessor_id: str,
    predecessor_sha256: str,
    predecessor_size: int,
    base_head: str,
    successor_id: str,
    request_sha256: str,
    acceptance_sha256: str,
    event_sha256: str,
    fence_sha256: str,
    baseline_tree: str,
    baseline_stderr_sha256: str,
    prospective_tree: str,
    prospective_stderr_sha256: str,
    gate_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "predecessor_path": f".github/memory/iterations/{predecessor_id}.md",
        "predecessor_iteration_id": predecessor_id,
        "predecessor_sha256": predecessor_sha256,
        "predecessor_size": predecessor_size,
        "base_head": base_head,
        "parser_failure_code": "prospective_authorization_failed",
        "failing_event_ordinal": 1,
        "failing_raw_block_sha256": event_sha256,
        "failing_full_fence_sha256": fence_sha256,
        "trusted_prefix_event_count": 0,
        "trusted_prefix_sha256": BOOTSTRAP_EMPTY_SHA256,
        "request_sha256": request_sha256,
        "acceptance_sha256": acceptance_sha256,
        "successor_iteration_id": successor_id,
        "baseline_snapshot_tree": baseline_tree,
        "baseline_snapshot_stderr_sha256": baseline_stderr_sha256,
        "prospective_candidate_tree": prospective_tree,
        "prospective_candidate_stderr_sha256": prospective_stderr_sha256,
        "prospective_gate_sha256": gate_sha256,
    }


def materialize_bootstrap_control(root: Path) -> dict[str, object]:
    old_gate = bootstrap_old_gate_bytes()
    (root / "scripts").mkdir()
    (root / "scripts/repository_gate.py").write_bytes(old_gate)
    (root / "AGENTS.md").write_text("baseline policy\n")
    (root / "tests").mkdir()
    (root / "tests/test_repository_gate.py").write_text("baseline tests\n")
    subprocess.run(
        ["git", "add", "AGENTS.md", "scripts/repository_gate.py", "tests/test_repository_gate.py"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "commit", "-qm", "bootstrap baseline"], cwd=root, check=True)
    base_head = bootstrap_git(root, "rev-parse", "HEAD").decode().strip()
    baseline_tree = bootstrap_git(root, "write-tree").decode().strip()

    predecessor_id = f"{ITERATION_ID}-bootstrap-r5"
    successor_id = f"{ITERATION_ID}-bootstrap-r6"
    request = "synthetic root request"
    acceptance = ["synthetic acceptance"]
    request_sha256 = bootstrap_hash(request.encode())
    acceptance_sha256 = bootstrap_hash(
        json.dumps(acceptance, separators=(",", ":")).encode()
    )
    event_payload = {
        "iteration_id": predecessor_id,
        "state": "BASELINED",
        "evidence": {"request": request, "acceptance": acceptance},
    }
    event_raw = bootstrap_canonical(event_payload)
    fence = b"```workflow-event\n" + event_raw + b"```\n"
    predecessor_raw = f"# Iteration {predecessor_id}\n\n".encode() + fence
    predecessor_path = (
        root / ".github" / "memory" / "iterations" / f"{predecessor_id}.md"
    )
    predecessor_path.parent.mkdir(parents=True)
    predecessor_path.write_bytes(predecessor_raw)
    predecessor_sha256 = bootstrap_hash(predecessor_raw)

    previous_id = f"{ITERATION_ID}-bootstrap-r4"
    previous_sha256 = "1" * 64
    delta_manifest = {
        "schema_version": 1,
        "predecessor_path": f".github/memory/iterations/{previous_id}.md",
        "predecessor_iteration_id": previous_id,
        "predecessor_sha256": previous_sha256,
        "predecessor_size": 1,
        "base_head": base_head,
        "parser_failure_code": "invalid_state_transition",
        "failing_event_ordinal": 1,
        "failing_raw_block_sha256": "2" * 64,
        "failing_full_fence_sha256": "3" * 64,
        "trusted_prefix_event_count": 0,
        "trusted_prefix_sha256": BOOTSTRAP_EMPTY_SHA256,
        "request_sha256": request_sha256,
        "acceptance_sha256": acceptance_sha256,
        "successor_iteration_id": predecessor_id,
        "actual_state": "RED",
        "expected_state": "DESIGNED",
    }
    delta_blob = bootstrap_canonical(delta_manifest)
    delta_path = f".github/iteration-quarantine/{previous_sha256}.json"
    stage(root, delta_path, delta_blob)
    prospective_tree = bootstrap_git(root, "write-tree").decode().strip()

    gate_sha256 = bootstrap_hash(old_gate)
    phase_results = {
        code: {
            "exit_code": 1,
            "error_code": code,
            "stdout_sha256": BOOTSTRAP_EMPTY_SHA256,
            "stderr_sha256": bootstrap_hash(message),
        }
        for code, message in BOOTSTRAP_FAILURES.items()
    }
    manifest = bootstrap_manifest(
        predecessor_id=predecessor_id,
        predecessor_sha256=predecessor_sha256,
        predecessor_size=len(predecessor_raw),
        base_head=base_head,
        successor_id=successor_id,
        request_sha256=request_sha256,
        acceptance_sha256=acceptance_sha256,
        event_sha256=bootstrap_hash(event_raw),
        fence_sha256=bootstrap_hash(fence),
        baseline_tree=baseline_tree,
        baseline_stderr_sha256=phase_results[
            "ordinary_baseline_schema_unsupported"
        ]["stderr_sha256"],
        prospective_tree=prospective_tree,
        prospective_stderr_sha256=phase_results[
            "recovery_baseline_chain_invalid"
        ]["stderr_sha256"],
        gate_sha256=gate_sha256,
    )
    manifest_blob = bootstrap_canonical(manifest)
    manifest_path = f".github/iteration-quarantine/{predecessor_sha256}.json"
    planned = [
        ("AGENTS.md", b"planned bootstrap policy\n", "present"),
        ("scripts/repository_gate.py", GATE.read_bytes(), "present"),
        ("tests/test_repository_gate.py", b"planned bootstrap tests\n", "present"),
        (manifest_path, manifest_blob, "absent"),
    ]
    for path, content, _state in planned:
        stage(root, path, content)
    control_path = f".github/iteration-bootstrap/{predecessor_sha256}.json"
    core = {
        "schema_version": 1,
        "failure_code": "prospective_authorization_failed",
        "predecessor": {
            "path": str(predecessor_path.relative_to(root)),
            "iteration_id": predecessor_id,
            "sha256": predecessor_sha256,
            "size": len(predecessor_raw),
            "event": {
                "ordinal": 1,
                "raw_sha256": bootstrap_hash(event_raw),
                "full_fence_sha256": bootstrap_hash(fence),
                "prefix_event_count": 0,
                "prefix_sha256": BOOTSTRAP_EMPTY_SHA256,
            },
        },
        "successor": {"iteration_id": successor_id, "single_successor": True},
        "lineage": {
            "root_request_sha256": request_sha256,
            "acceptance_sha256": acceptance_sha256,
        },
        "replay": {
            "base_commit": base_head,
            "gate_path": "scripts/repository_gate.py",
            "gate_sha256": gate_sha256,
            "baseline_snapshot": {
                "tree": baseline_tree,
                "staged_diff_sha256": bootstrap_tree_diff_sha256(
                    root, base_head, baseline_tree
                ),
                "result": phase_results["ordinary_baseline_schema_unsupported"],
            },
            "prospective_candidate": {
                "tree": prospective_tree,
                "staged_diff_sha256": bootstrap_tree_diff_sha256(
                    root, base_head, prospective_tree
                ),
                "result": phase_results["recovery_baseline_chain_invalid"],
            },
            "manifest_delta": {
                "path": delta_path,
                "sha256": bootstrap_hash(delta_blob),
                "size": len(delta_blob),
                "baseline_state": "absent",
                "prospective_state": "present_exact",
            },
        },
        "planned_blobs": [
            {
                "path": path,
                "baseline_state": state,
                "planned_sha256": bootstrap_hash(content),
                "planned_size": len(content),
            }
            for path, content, state in planned
        ],
        "control_envelope": {
            "path": control_path,
            "baseline_state": "absent",
            "canonicalization": "compact_json_sorted_ascii_lf_v1",
        },
        "scope": {
            "allowed_paths": [
                *[path for path, _content, _state in planned],
                control_path,
            ],
            "forbidden_authority": BOOTSTRAP_FORBIDDEN_AUTHORITY,
        },
    }
    record = bootstrap_record(core)
    stage(root, control_path, bootstrap_canonical(record))
    return {
        "record": record,
        "record_path": root / control_path,
        "ledger_path": predecessor_path,
        "manifest_path": root / manifest_path,
        "delta_path": root / delta_path,
        "successor_path": (
            root / ".github" / "memory" / "iterations" / f"{successor_id}.md"
        ),
        "planned_paths": [path for path, _content, _state in planned],
    }


def run_bootstrap(root: Path, fixture: dict[str, object]):
    return subprocess.run(
        [
            sys.executable,
            str(root / "scripts/repository_gate.py"),
            "validate-bootstrap",
            "--record",
            str(fixture["record_path"]),
            "--ledger",
            str(fixture["ledger_path"]),
        ],
        cwd=root,
        text=True,
        capture_output=True,
        env={"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
    )


def replace_bootstrap_record(
    root: Path,
    fixture: dict[str, object],
    record: dict[str, object],
) -> None:
    record["approvals"] = bootstrap_decisions(record["core"])
    relative = str(Path(fixture["record_path"]).relative_to(root))
    stage(root, relative, bootstrap_canonical(record))


def test_bootstrap_control_replays_actual_validate_append_idempotently(
    git_repo: Path,
) -> None:
    fixture = materialize_bootstrap_control(git_repo)

    first = run_bootstrap(git_repo, fixture)
    second = run_bootstrap(git_repo, fixture)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == "[repository-gate] bootstrap control valid\n"
    assert second.stdout == first.stdout


@pytest.mark.parametrize(
    ("location", "mutation"),
    [
        (("core", "predecessor", "event", "raw_sha256"), "0" * 64),
        (("core", "predecessor", "path"), ".github/memory/iterations/other.md"),
        (("core", "predecessor", "sha256"), "0" * 64),
        (("core", "predecessor", "size"), 1),
        (("core", "replay", "baseline_snapshot", "tree"), "0" * 40),
        (("core", "replay", "baseline_snapshot", "staged_diff_sha256"), "0" * 64),
        (("core", "replay", "prospective_candidate", "result", "stderr_sha256"), "0" * 64),
        (("core", "replay", "gate_sha256"), "0" * 64),
        (("core", "replay", "manifest_delta", "sha256"), "0" * 64),
        (("core", "replay", "manifest_delta", "baseline_state"), "present"),
        (("core", "successor", "single_successor"), False),
        (("core", "failure_code"), "*"),
        (("core", "scope", "allowed_paths"), ["AGENTS.md"]),
        (("core", "planned_blobs", 0, "planned_sha256"), "0" * 64),
    ],
    ids=[
        "event",
        "ledger-path",
        "ledger-sha",
        "ledger-size",
        "phase-tree",
        "phase-diff",
        "phase-result",
        "old-gate",
        "manifest-delta",
        "baseline-presence",
        "single-successor",
        "wildcard-failure",
        "allowed-paths",
        "planned-blob",
    ],
)
def test_bootstrap_control_rejects_bound_evidence_tamper(
    git_repo: Path,
    location: tuple[object, ...],
    mutation: object,
) -> None:
    fixture = materialize_bootstrap_control(git_repo)
    record = json.loads(bootstrap_canonical(fixture["record"]))
    target = record
    for key in location[:-1]:
        target = target[key]
    target[location[-1]] = mutation
    replace_bootstrap_record(git_repo, fixture, record)

    result = run_bootstrap(git_repo, fixture)

    assert result.returncode == 1


@pytest.mark.parametrize(
    ("container_path", "change"),
    [
        (("core",), "extra"),
        (("core", "scope"), "extra"),
        (("core", "planned_blobs", 0), "extra"),
        (("approvals", 0), "extra"),
        (("core",), "missing"),
        (("core", "scope"), "missing"),
        (("core", "planned_blobs", 0), "missing"),
        (("approvals", 0), "missing"),
    ],
)
def test_bootstrap_control_rejects_extra_or_missing_schema_fields(
    git_repo: Path,
    container_path: tuple[object, ...],
    change: str,
) -> None:
    fixture = materialize_bootstrap_control(git_repo)
    record = json.loads(bootstrap_canonical(fixture["record"]))
    target = record
    for key in container_path:
        target = target[key]
    if change == "extra":
        target["unexpected"] = "forbidden"
    else:
        target.pop(next(iter(target)))
    if container_path[0] == "core":
        record["approvals"] = bootstrap_decisions(record["core"])
    relative = str(Path(fixture["record_path"]).relative_to(git_repo))
    stage(git_repo, relative, bootstrap_canonical(record))

    result = run_bootstrap(git_repo, fixture)

    assert result.returncode == 1


def test_bootstrap_control_rejects_candidate_blob_drift(git_repo: Path) -> None:
    fixture = materialize_bootstrap_control(git_repo)
    stage(git_repo, fixture["planned_paths"][0], b"drifted candidate bytes\n")

    result = run_bootstrap(git_repo, fixture)

    assert result.returncode == 1


def test_bootstrap_control_rejects_extra_candidate_path(git_repo: Path) -> None:
    fixture = materialize_bootstrap_control(git_repo)
    stage(git_repo, "unexpected-governance.txt", b"candidate scope drift\n")

    result = run_bootstrap(git_repo, fixture)

    assert result.returncode == 1
    assert "candidate path set" in result.stderr


@pytest.mark.parametrize(
    "path",
    [
        "src/interact/unauthorized_product.py",
        "docs/unauthorized.md",
        ".github/memory/iterations/unauthorized.md",
        ".github/memory/unauthorized.md",
        "tests/test_unauthorized.py",
    ],
    ids=["product-source", "docs", "workflow-event", "memory", "other-test"],
)
def test_bootstrap_control_rejects_self_declared_path(
    git_repo: Path,
    path: str,
) -> None:
    fixture = materialize_bootstrap_control(git_repo)
    content = b"unauthorized candidate bytes\n"
    stage(git_repo, path, content)
    record = json.loads(bootstrap_canonical(fixture["record"]))
    record["core"]["planned_blobs"].append(
        {
            "path": path,
            "baseline_state": "absent",
            "planned_sha256": bootstrap_hash(content),
            "planned_size": len(content),
        }
    )
    record["core"]["scope"]["allowed_paths"].insert(-1, path)
    replace_bootstrap_record(git_repo, fixture, record)

    result = run_bootstrap(git_repo, fixture)

    assert result.returncode == 1
    assert "planned paths" in result.stderr


def test_bootstrap_control_rejects_executing_gate_index_drift(
    git_repo: Path,
) -> None:
    fixture = materialize_bootstrap_control(git_repo)
    drifted_gate = GATE.read_bytes() + b"\n# indexed drift\n"
    object_id = bootstrap_git(
        git_repo, "hash-object", "-w", "--stdin", input_bytes=drifted_gate
    ).decode().strip()
    subprocess.run(
        [
            "git",
            "update-index",
            "--add",
            "--cacheinfo",
            "100644",
            object_id,
            "scripts/repository_gate.py",
        ],
        cwd=git_repo,
        check=True,
    )
    record = json.loads(bootstrap_canonical(fixture["record"]))
    gate_item = next(
        item
        for item in record["core"]["planned_blobs"]
        if item["path"] == "scripts/repository_gate.py"
    )
    gate_item["planned_sha256"] = bootstrap_hash(drifted_gate)
    gate_item["planned_size"] = len(drifted_gate)
    replace_bootstrap_record(git_repo, fixture, record)

    result = run_bootstrap(git_repo, fixture)

    assert result.returncode == 1
    assert "executing gate differs" in result.stderr


def test_bootstrap_control_rejects_record_actual_path_mismatch(git_repo: Path) -> None:
    fixture = materialize_bootstrap_control(git_repo)
    wrong = git_repo / "out" / "tests" / "wrong-control.json"
    wrong.parent.mkdir(parents=True)
    wrong.write_bytes(Path(fixture["record_path"]).read_bytes())
    fixture["record_path"] = wrong

    result = run_bootstrap(git_repo, fixture)

    assert result.returncode == 1


def test_bootstrap_control_rejects_header_only_successor(git_repo: Path) -> None:
    fixture = materialize_bootstrap_control(git_repo)
    successor = Path(fixture["successor_path"])
    successor.write_text(f"# Iteration {successor.stem}\n")

    result = run_bootstrap(git_repo, fixture)

    assert result.returncode == 1


@pytest.mark.parametrize("committed_path", ["record_path", "manifest_path"])
def test_bootstrap_control_rejects_committed_authority(
    git_repo: Path,
    committed_path: str,
) -> None:
    fixture = materialize_bootstrap_control(git_repo)
    relative = str(Path(fixture[committed_path]).relative_to(git_repo))
    subprocess.run(["git", "commit", "-qm", "consume bootstrap", "--", relative], cwd=git_repo, check=True)

    result = run_bootstrap(git_repo, fixture)

    assert result.returncode == 1


def test_bootstrap_control_rejects_conflicting_control(git_repo: Path) -> None:
    fixture = materialize_bootstrap_control(git_repo)
    conflict_path = ".github/iteration-bootstrap/conflict.json"
    conflict_blob = Path(fixture["record_path"]).read_bytes()
    stage(
        git_repo,
        conflict_path,
        conflict_blob,
    )
    record = json.loads(bootstrap_canonical(fixture["record"]))
    record["core"]["planned_blobs"].append(
        {
            "path": conflict_path,
            "baseline_state": "absent",
            "planned_sha256": bootstrap_hash(conflict_blob),
            "planned_size": len(conflict_blob),
        }
    )
    record["core"]["scope"]["allowed_paths"].insert(-1, conflict_path)
    replace_bootstrap_record(git_repo, fixture, record)

    result = run_bootstrap(git_repo, fixture)

    assert result.returncode == 1
    assert "planned paths" in result.stderr


def test_bootstrap_control_rejects_conflicting_manifest(git_repo: Path) -> None:
    fixture = materialize_bootstrap_control(git_repo)
    conflict = json.loads(Path(fixture["manifest_path"]).read_bytes())
    conflict_sha = "9" * 64
    conflict["predecessor_sha256"] = conflict_sha
    conflict["predecessor_iteration_id"] = f"{ITERATION_ID}-other-r5"
    conflict["predecessor_path"] = (
        f".github/memory/iterations/{conflict['predecessor_iteration_id']}.md"
    )
    conflict_blob = bootstrap_canonical(conflict)
    conflict_path = f".github/iteration-quarantine/{conflict_sha}.json"
    stage(git_repo, conflict_path, conflict_blob)
    record = json.loads(bootstrap_canonical(fixture["record"]))
    record["core"]["planned_blobs"].append(
        {
            "path": conflict_path,
            "baseline_state": "absent",
            "planned_sha256": bootstrap_hash(conflict_blob),
            "planned_size": len(conflict_blob),
        }
    )
    record["core"]["scope"]["allowed_paths"].insert(-1, conflict_path)
    replace_bootstrap_record(git_repo, fixture, record)

    result = run_bootstrap(git_repo, fixture)

    assert result.returncode == 1
    assert "planned paths" in result.stderr


def test_bootstrap_control_validates_from_fresh_shared_clone(git_repo: Path) -> None:
    fixture = materialize_bootstrap_control(git_repo)
    candidate_tree = bootstrap_git(git_repo, "write-tree").decode().strip()
    clone = git_repo.parent / f"{git_repo.name}-bootstrap-clone"
    try:
        subprocess.run(
            ["git", "clone", "--shared", "--no-checkout", "-q", str(git_repo), str(clone)],
            check=True,
        )
        subprocess.run(["git", "read-tree", candidate_tree], cwd=clone, check=True)
        subprocess.run(["git", "checkout-index", "-a"], cwd=clone, check=True)
        ledger_relative = Path(fixture["ledger_path"]).relative_to(git_repo)
        clone_ledger = clone / ledger_relative
        clone_ledger.parent.mkdir(parents=True)
        clone_ledger.write_bytes(Path(fixture["ledger_path"]).read_bytes())
        clone_fixture = {
            **fixture,
            "record_path": clone / Path(fixture["record_path"]).relative_to(git_repo),
            "ledger_path": clone_ledger,
        }

        result = run_bootstrap(clone, clone_fixture)

        assert result.returncode == 0, result.stderr
    finally:
        shutil.rmtree(clone, ignore_errors=True)


def test_bootstrap_control_keeps_quarantined_predecessor_invalid(git_repo: Path) -> None:
    fixture = materialize_bootstrap_control(git_repo)

    result = subprocess.run(
        [
            sys.executable,
            str(git_repo / "scripts/repository_gate.py"),
            "verify-ledger",
            "--ledger",
            str(fixture["ledger_path"]),
        ],
        cwd=git_repo,
        text=True,
        capture_output=True,
        env={"PATH": os.environ["PATH"]},
        check=False,
    )

    assert result.returncode != 0
