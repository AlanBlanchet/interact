"""Private type ownership contracts for the media session router."""

from dataclasses import is_dataclass

from interact.vision.session import _SessionFailureFact


def test_session_failure_fact_is_one_frozen_typed_shape() -> None:
    assert is_dataclass(_SessionFailureFact)
    assert _SessionFailureFact.__dataclass_params__.frozen
    assert set(_SessionFailureFact.__annotations__) >= {
        "provider", "status", "reason", "exit_code", "stderr_bytes",
        "stderr_sha256", "timeout_phase", "elapsed_seconds", "cli_version",
    }
