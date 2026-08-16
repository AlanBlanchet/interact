"""Extension manifest must expose only ``interact.*`` keys."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

EXT_ROOT = Path(__file__).resolve().parents[1] / "vscode-extension"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((EXT_ROOT / "package.json").read_text())


@pytest.fixture(scope="module")
def extension_ts() -> str:
    return (EXT_ROOT / "src" / "extension.ts").read_text()


def test_commands_use_interact_namespace(manifest):
    cmds = {c["command"] for c in manifest["contributes"]["commands"]}
    assert "interact.openDashboard" in cmds
    assert "interact.selectModel" in cmds
    assert "interact.manageApiKeys" in cmds
    assert not any(c.startswith("interactMcp.") for c in cmds), cmds


def test_configuration_keys_use_interact_namespace(manifest):
    props = manifest["contributes"]["configuration"]["properties"]
    assert props, "expected configuration properties to be declared"
    for key in props:
        assert key.startswith("interact."), key
        assert not key.startswith("interactMcp."), key


# Settings the extension owns that have no Python counterpart (UI-only, never sent to the server).
_EXTENSION_ONLY = {"interact.projectPath", "interact.display.currency"}


def test_every_python_setting_is_registered(manifest):
    """package.json's configuration block is HAND-maintained (nothing generates it), so it drifts
    from ``config/schema.py`` silently — an unregistered key just never appears in the VS Code
    settings UI. This is the check that catches it."""
    from interact.config import SETTINGS

    declared = set(manifest["contributes"]["configuration"]["properties"])
    expected = {f"interact.{s.key}" for s in SETTINGS}
    assert not (expected - declared), f"in schema.py but not package.json: {sorted(expected - declared)}"
    assert not (declared - expected - _EXTENSION_ONLY), (
        f"in package.json but not schema.py: {sorted(declared - expected - _EXTENSION_ONLY)}"
    )


def test_debug_dir_default_matches_python(manifest, monkeypatch):
    """The manifest default is what the dashboard resolves the usage log against when the user
    never touched the setting — it must be Python's ``Config.debug_dir``, or the panel reads a
    file nothing writes (see tests/test_paths.py)."""
    from interact.config import Config

    monkeypatch.delenv("INTERACT_DEBUG_DIR", raising=False)  # assert the DEFAULT, not a dev override
    prop = manifest["contributes"]["configuration"]["properties"]["interact.debug.dir"]
    default = Config().debug_dir  # derived, not a 4th hand-typed copy of the same path
    assert prop["default"] == "~/" + default.relative_to(Path.home()).as_posix()


def test_activates_on_startup(manifest):
    assert "onStartupFinished" in manifest.get("activationEvents", [])


@pytest.mark.parametrize(
    "needle",
    [
        "$(eye) Interact",
        "statusBar.show()",
        "interact.openDashboard",
    ],
)
def test_extension_ts_has_status_bar_wiring(extension_ts, needle):
    assert needle in extension_ts, f"missing {needle!r} in extension.ts"


_BENCH_RE = re.compile(r"bench|grounding|eval", re.I)


def test_no_benchmark_run_commands(manifest):
    """Benchmark/grounding runs are developer-only CLIs — never user-facing commands."""
    cmds = [c["command"] for c in manifest["contributes"]["commands"]]
    offenders = [c for c in cmds if _BENCH_RE.search(c)]
    assert not offenders, f"commands trigger paid evals: {offenders}"


def test_dashboard_has_no_run_grounding_bench():
    text = (EXT_ROOT / "src" / "dashboard.ts").read_text()
    assert "runGroundingBench" not in text
