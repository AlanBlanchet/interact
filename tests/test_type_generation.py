import os
import shutil
import subprocess
from pathlib import Path

import pytest

from interact.agents.events import AgentEvent
from interact.agents.protocol import (
    ConversationCommand,
    ConversationResponse,
    ConversationStreamEvent,
)
from interact.agents.registry import AgentRun


@pytest.mark.parametrize("sibling", [False, True], ids=["released-core", "editable-core"])
def test_type_generation_disables_external_catalog_discovery(tmp_path, sibling) -> None:
    """Codegen imports catalog modules; its launcher must make that import deterministic."""
    repo = tmp_path / "public"
    script = repo / "clients/vscode/scripts/generate-types.sh"
    script.parent.mkdir(parents=True)
    shutil.copyfile("clients/vscode/scripts/generate-types.sh", script)
    core = tmp_path / "interact-core"
    if sibling:
        core.mkdir()
        (core / "pyproject.toml").touch()
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    capture = tmp_path / "invocation"
    uv = binary_dir / "uv"
    uv.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$LITELLM_LOCAL_MODEL_COST_MAP" "$OLLAMA_DISCOVERY" "$@" '
        '> "$CODEGEN_CAPTURE"\nexit 1\n'
    )
    uv.chmod(0o700)
    result = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True,
        env=os.environ | {"PATH": f"{binary_dir}:{os.environ['PATH']}",
                          "CODEGEN_CAPTURE": str(capture)},
    )
    assert result.returncode == 0, result.stderr
    assert "pydantic-to-typescript not installed; skipping" in result.stderr
    expected = ["True", "0", "run", "--directory", str(repo)]
    if sibling:
        expected += ["--with-editable", str(repo / ".." / "interact-core")]
    assert capture.read_text().splitlines() == expected + ["python", "-c", "import pydantic2ts"]


def test_generation_emits_exhaustive_runtime_decoders_from_python_wire_union() -> None:
    """Every Python wire variant must be accepted/rejected by generated executable validation."""
    generated = Path("clients/vscode/src/generated/types.ts").read_text()
    for model in (
        ConversationCommand, ConversationResponse, ConversationStreamEvent, AgentRun, AgentEvent,
    ):
        assert model.__name__ in generated
        assert f"decode{model.__name__}" in generated
    client = Path("clients/vscode/src/conversationClient.ts").read_text()
    assert "function isResponse" not in client
    assert "function isEvent" not in client
