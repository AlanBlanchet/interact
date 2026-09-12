from pathlib import Path

from interact.agents.events import AgentEvent
from interact.agents.protocol import (
    ConversationCommand,
    ConversationResponse,
    ConversationStreamEvent,
)
from interact.agents.registry import AgentRun


def test_type_generation_disables_external_catalog_discovery() -> None:
    """Codegen imports catalog modules; its launcher must make that import deterministic."""
    script = Path("clients/vscode/scripts/generate-types.sh").read_text()

    assert 'export LITELLM_LOCAL_MODEL_COST_MAP="True"' in script
    assert 'export OLLAMA_DISCOVERY="0"' in script
    assert 'CORE_SOURCE_DIR="$REPO_DIR/../interact-core"' in script
    assert 'UV_RUN+=(--no-sources)' in script
    assert 'installed interact-core detected' in script


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
