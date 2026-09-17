"""`_sandbox_death_diagnostics` must name WHY the sandbox was recreated when a self-heal happened
under a caller, not just report the FRESH backend's (necessarily healthy) status (#141)."""

from interact.server import sandbox, targets


class _HealthyBackend:
    """Stands in for the fresh sandbox `_get_sandbox` already self-healed — `is_alive` is True,
    so `display_health()`/`last_app_output()` alone say nothing about the PREVIOUS one's death."""

    def display_health(self) -> str:
        return ""

    def last_app_output(self, limit: int = 800) -> str:
        return ""


def test_diagnostics_lead_with_the_recorded_replace_reason(monkeypatch):
    monkeypatch.setattr(
        sandbox, "last_replace_reason", lambda: "The sandbox Xephyr :99 is DOWN (SIGKILL)"
    )
    msg = targets._sandbox_death_diagnostics(_HealthyBackend())
    assert "recreated automatically" in msg
    assert "SIGKILL" in msg


def test_diagnostics_fall_back_to_current_health_when_never_replaced(monkeypatch):
    """No respawn happened — must fall through to the fresh backend's own health/output, not
    claim a replacement that never occurred."""
    monkeypatch.setattr(sandbox, "last_replace_reason", lambda: None)
    msg = targets._sandbox_death_diagnostics(_HealthyBackend())
    assert "recreated automatically" not in msg
    assert msg == ""
