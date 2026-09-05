"""Executable acceptance contract for the public production repository layout."""

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RELOCATIONS = (
    ("src/interact", "packages/interact-local/src/interact"),
    ("vscode-extension", "clients/vscode"),
    ("docs", "site"),
)
PROTECTED = (
    ("tests/test_launch_replace.py", "tests/test_launch_replace.py", "f2988cfa38d45db3eb8085516993d19f24fffe71", "e33cfa619fd49aac58fa1821ab2fdf4dc39401c7"),
    ("tests/test_model_criteria.py", "tests/test_model_criteria.py", "1f57c63c056e8ca0166c1c44017881ca8a523c02", "d26854347bb40343d1273e6b72e1a1173ff31040"),
    ("tests/test_sandbox_lifecycle.py", "tests/test_sandbox_lifecycle.py", "3a8190328b5d7f1d2e15f89dd25b393dcea16b06", "326354751899891d6d2af5d49a42a5500b7227ca"),
    ("tests/test_sandbox_orphans.py", "tests/test_sandbox_orphans.py", "4ecc1f633b030d023a62feb60dacfa0db89457c9", "f30ab024a4fc52ae54f5daeb4eaa2adc3a9f0ac2"),
    ("tests/test_tools_desktop_launch.py", "tests/test_tools_desktop_launch.py", "84cb9fd10730d1bb45a28ff8966693a5c69aa519", "ac07b4419255dcc27f8177b71032dcdde5b26773"),
    ("vscode-extension/package.json", "clients/vscode/package.json", "ece923db43e5fa5c201c93ff29518a6b6113115b", "e1dcf183c7acc5d237ae3f1aafc5c43525de9591"),
    ("vscode-extension/src/extension.ts", "clients/vscode/src/extension.ts", "395783f171b56abb446e29b3f8049af26fb5c4a9", "06149758ae61a6b783979523df0b682d36a77d6e"),
    ("vscode-extension/src/reachable.test.ts", "clients/vscode/src/reachable.test.ts", "b8ee0a5e9a45e5342e19f4a5d7528f4433606091", "a0929cdd361a58055d6ebc2677ef3f2fdc0f5f97"),
)
PROMPT_CONTRACTS = ("PromptKey", "PromptRevision", "PromptChannelEntry", "PromptCatalogPage")


@pytest.mark.parametrize(("old", "new"), RELOCATIONS)
def test_public_products_have_one_physical_home(old: str, new: str) -> None:
    assert not (ROOT / old).exists(), f"obsolete public path remains: {old}"
    assert (ROOT / new).is_dir(), f"production path is absent: {new}"


@pytest.mark.parametrize(("old", "new", "index_blob", "working_blob"), PROTECTED)
def test_protected_bytes_survive_the_cutover(
    old: str, new: str, index_blob: str, working_blob: str
) -> None:
    indexed = subprocess.run(
        ["git", "rev-parse", f":{new}"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert indexed == index_blob, f"protected index blob changed during relocation: {old}"
    assert subprocess.run(
        ["git", "hash-object", str(ROOT / new)], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip() == working_blob, f"protected working patch changed during relocation: {old}"
    if old != new:
        assert not (ROOT / old).exists(), f"protected extension path was copied instead of moved: {old}"


def test_public_prompt_contracts_are_exported_to_schema_and_vscode() -> None:
    package_root = ROOT / "packages/interact-contracts/src"
    schema_path = ROOT / "packages/interact-contracts/schema/prompt-contracts.schema.json"
    typescript_path = ROOT / "clients/vscode/src/generated/promptContracts.ts"
    assert (package_root / "interact_contracts/prompts.py").is_file()
    assert schema_path.is_file()
    assert typescript_path.is_file()

    sys.path.insert(0, str(package_root))
    try:
        package = __import__("interact_contracts", fromlist=list(PROMPT_CONTRACTS))
    finally:
        sys.path.pop(0)
    assert all(getattr(package, name, None) is not None for name in PROMPT_CONTRACTS)
    definitions = json.loads(schema_path.read_text())["$defs"]
    assert set(PROMPT_CONTRACTS) <= definitions.keys()
    typescript = typescript_path.read_text()
    assert all(f"export interface {name}" in typescript for name in PROMPT_CONTRACTS)


def test_public_python_has_no_private_cloud_dependency() -> None:
    public_roots = (
        ROOT / "packages/interact-local/src",
        ROOT / "packages/interact-contracts/src",
    )
    assert all(root.is_dir() for root in public_roots)
    for root in public_roots:
        for source in root.rglob("*.py"):
            tree = ast.parse(source.read_text(), filename=str(source))
            imports = (
                node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
            )
            names = (
                alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
            )
            assert not any((name or "").split(".")[0] == "interact_cloud" for name in (*imports, *names))


def test_precommit_hook_targets_only_the_relocated_release_graph() -> None:
    hook = (ROOT / ".githooks/pre-commit").read_text()

    assert "vscode-extension/" not in hook
    assert "^src/interact/" not in hook
    assert "clients/vscode" in hook
    assert "packages/interact-local/src/interact" in hook
