"""Compile exact committed prompt sources into verified provider projections."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys


MANIFEST_NAME = "projection-manifest.json"
_OUTPUT_ROOTS = ("agents", "skills", "rules")
_OUTPUT_FILES = ("AGENTS.md", "instructions.md", "org.json")
_PASSTHROUGH_ROOTS = ("hooks",)


def compile_prompt_projection(
    repository: Path,
    commit: str,
    projection_root: Path,
    installed_root: Path,
    generator_path: str = "generate.py",
) -> Path:
    """Compile twice from one Git commit, publishing only byte-identical outputs."""
    if projection_root.exists():
        raise ValueError("projection destination already exists")
    projection_root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if projection_root.parent.is_symlink() or not projection_root.parent.is_dir():
        raise ValueError("projection parent is not a safe directory")
    resolved_commit = _git(repository, "rev-parse", f"{commit}^{{commit}}").strip()
    entries = _source_entries(repository, resolved_commit)
    generator = _safe_path(generator_path)
    if generator.as_posix() not in entries:
        raise ValueError("generator is absent from committed source")
    work_roots = (
        projection_root.parent / f".{projection_root.name}.compile-a",
        projection_root.parent / f".{projection_root.name}.compile-b",
    )
    if any(path.exists() for path in work_roots):
        raise ValueError("compiler workspace already exists")
    try:
        for root in work_roots:
            _materialize(repository, entries, root)
            result = subprocess.run(
                [sys.executable, generator.as_posix()], cwd=root, capture_output=True,
                env={"PATH": os.environ["PATH"], "_GENERATE_YAML_BOOTSTRAP": "1"},
                timeout=30,
            )
            if result.returncode:
                raise ValueError("committed prompt generator failed")
            _normalize_output_modes(root)
            _copy_passthrough_outputs(root, entries)
        first = _compiled_outputs(work_roots[0])
        second = _compiled_outputs(work_roots[1])
        if first != second:
            raise ValueError("prompt generator is not deterministic")
        projection_root.mkdir(mode=0o755)
        for relative, (mode, content) in first.items():
            destination = projection_root / relative
            destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            destination.write_bytes(content)
            destination.chmod(mode)
        return _write_manifest(
            repository, resolved_commit, projection_root, installed_root, generator, first
        )
    finally:
        for root in work_roots:
            if root.exists():
                shutil.rmtree(root)


def stage_projection_install(
    projection_root: Path, installed_root: Path, staging_root: Path
) -> Path:
    """Verify a projection manifest and prepare private files without switching consumers."""
    if staging_root.exists():
        raise ValueError("install staging destination already exists")
    manifest = json.loads((projection_root / MANIFEST_NAME).read_text(encoding="utf-8"))
    staging_root.mkdir(mode=0o700)
    try:
        for output in manifest["outputs"]:
            relative = _safe_path(output["path"])
            source = projection_root / relative
            if source.is_symlink() or not source.is_file():
                raise ValueError("projection output is not a regular file")
            content = source.read_bytes()
            if hashlib.sha256(content).hexdigest() != output["sha256"]:
                raise ValueError("projection output digest changed")
            destination = staging_root / relative
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            destination.write_bytes(content)
            destination.chmod(0o600)
        return staging_root
    except Exception:
        shutil.rmtree(staging_root)
        raise


def install_prompt_projection(
    projection_root: Path, home: Path, vscode_root: Path, state_path: Path,
    adoption_path: Path | None = None,
) -> None:
    """Transactionally switch only manifest-owned provider consumer files."""
    outputs = _validated_manifest_outputs(projection_root)
    state = _installed_document(state_path)
    targets, mergeable, hook_groups = _consumer_payloads(
        outputs, home, vscode_root, state.get("hook_groups", {})
    )
    previous = {Path(target): digest for target, digest in state.get("managed", {}).items()}
    adoption = _adoption_manifest(adoption_path)
    adopted_directories = _adopted_directories(targets, adoption, home, vscode_root)
    for target in set(targets) | set(previous):
        if any(directory in target.parents for directory in adopted_directories):
            continue
        if not target.exists():
            continue
        if target.is_symlink():
            declared = adoption.get(target)
            if declared is None or os.readlink(target) != declared[0] or hashlib.sha256(
                target.read_bytes()
            ).hexdigest() != declared[1]:
                raise ValueError("legacy symlink does not match adoption manifest")
            continue
        if not target.is_file():
            raise ValueError("managed prompt target is not a regular file")
        current = hashlib.sha256(target.read_bytes()).hexdigest()
        expected = previous.get(target)
        if expected is None and target not in mergeable:
            raise ValueError("unmanaged prompt target collision")
        if expected is not None and current != expected and target not in mergeable:
            raise ValueError("managed prompt target changed locally")
    transaction = state_path.parent / ".prompt-install-transaction"
    if transaction.exists():
        raise ValueError("prompt install transaction already exists")
    transaction.mkdir(mode=0o700, parents=True)
    backups: dict[Path, Path] = {}
    installed: list[Path] = []
    try:
        for index, directory in enumerate(sorted(adopted_directories, key=lambda path: len(path.parts))):
            backup = transaction / f"adopted-{index}"
            os.replace(directory, backup)
            backups[directory] = backup
            directory.mkdir(mode=0o700)
        for index, target in enumerate(sorted(set(targets) | set(previous), key=str)):
            _require_safe_parent(target, home, vscode_root)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if target.exists():
                backup = transaction / f"backup-{index}"
                os.replace(target, backup)
                backups[target] = backup
            payload = targets.get(target)
            if payload is not None:
                staged = transaction / f"new-{index}"
                staged.write_bytes(payload[0])
                staged.chmod(payload[1])
                os.replace(staged, target)
                installed.append(target)
        state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        state_staged = transaction / "state"
        state_staged.write_text(json.dumps({
            "managed": {
                str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(targets, key=str)
            },
            "source_commit": json.loads(
                (projection_root / MANIFEST_NAME).read_text(encoding="utf-8")
            )["source_commit"],
            "hook_groups": hook_groups,
            "version": 1,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        state_staged.chmod(0o600)
        os.replace(state_staged, state_path)
    except Exception:
        for target in installed:
            if target.exists():
                target.unlink()
        for target, backup in backups.items():
            if backup.exists():
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
                os.replace(backup, target)
        raise
    finally:
        if transaction.exists():
            shutil.rmtree(transaction)


def _validated_manifest_outputs(projection_root: Path) -> dict[str, Path]:
    manifest = json.loads((projection_root / MANIFEST_NAME).read_text(encoding="utf-8"))
    declared: dict[str, tuple[str, int, str]] = {}
    for output in manifest.get("outputs", []):
        relative = _safe_path(output["path"]).as_posix()
        if relative in declared or relative.casefold() in {key.casefold() for key in declared}:
            raise ValueError("projection manifest output collision")
        declared[relative] = (output["sha256"], output["size"], output["mode"])
    actual = _compiled_outputs(projection_root)
    if set(actual) != set(declared):
        raise ValueError("projection manifest output set changed")
    for relative, (mode, content) in actual.items():
        digest, size, declared_mode = declared[relative]
        if (hashlib.sha256(content).hexdigest(), len(content), f"{mode:04o}") != (
            digest, size, declared_mode
        ):
            raise ValueError("projection manifest output identity changed")
    return {relative: projection_root / relative for relative in actual}


def _consumer_payloads(
    outputs: dict[str, Path], home: Path, vscode_root: Path,
    prior_hook_groups: dict[str, list[object]],
) -> tuple[dict[Path, tuple[bytes, int]], set[Path], dict[str, list[object]]]:
    targets: dict[Path, tuple[bytes, int]] = {}
    hook_scripts = {
        PurePosixPath(relative).name
        for relative in outputs
        if relative.startswith("hooks/") and relative.endswith(".sh")
    }
    for relative, source in outputs.items():
        path = PurePosixPath(relative)
        destinations: tuple[Path, ...]
        if relative == "AGENTS.md":
            destinations = (home / "AGENTS.md",)
        elif relative == "instructions.md":
            destinations = (
                home / "CLAUDE.md", home / ".claude" / "CLAUDE.md",
                vscode_root / "alan.instructions.md",
            )
        elif relative == "org.json":
            destinations = (home / ".claude" / "org.json",)
        elif len(path.parts) == 2 and path.parts[0] == "agents":
            destinations = (
                home / ".claude" / "agents" / path.name,
                vscode_root / f"{path.stem}.agent.md",
            )
        elif len(path.parts) == 3 and path.parts[0] == "skills" and path.name == "SKILL.md":
            name = path.parts[1]
            destinations = (
                home / ".claude" / "skills" / name / "SKILL.md",
                home / ".codex" / "skills" / name / "SKILL.md",
                vscode_root / f"{name}.skill.instructions.md",
            )
        elif len(path.parts) == 2 and path.parts[0] == "rules":
            destinations = (
                home / ".claude" / "rules" / path.name,
                vscode_root / f"{path.stem}.instructions.md",
            )
        elif len(path.parts) == 2 and path.parts[0] == "hooks" and path.suffix == ".sh":
            destinations = (home / ".claude" / "hooks" / path.name,)
        elif relative in {"hooks/hooks.json", "hooks/turn-end-asks.md"}:
            continue
        else:
            raise ValueError("projection output has no consumer mapping")
        for destination in destinations:
            if destination in targets:
                raise ValueError("prompt consumer target collision")
            targets[destination] = (source.read_bytes(), 0o700 if path.suffix == ".sh" else 0o600)
    settings = home / ".claude" / "settings.json"
    settings_bytes, hook_groups = _merged_hook_settings(
        outputs, settings, hook_scripts, prior_hook_groups
    )
    targets[settings] = (settings_bytes, 0o600)
    return targets, {settings}, hook_groups


def _merged_hook_settings(
    outputs: dict[str, Path], settings: Path, managed_scripts: set[str],
    prior_hook_groups: dict[str, list[object]],
) -> tuple[bytes, dict[str, list[object]]]:
    fragment = json.loads(outputs["hooks/hooks.json"].read_text(encoding="utf-8"))
    prompt = outputs["hooks/turn-end-asks.md"].read_text(encoding="utf-8").rstrip("\n")
    fragment["hooks"]["Stop"][0]["hooks"][0]["prompt"] = prompt
    current = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
    hooks = current.setdefault("hooks", {})
    for event, additions in fragment["hooks"].items():
        retained = []
        for group in hooks.get(event, []):
            commands = group.get("hooks", []) if isinstance(group, dict) else []
            owned = group in prior_hook_groups.get(event, []) or group in additions or any(
                PurePosixPath(str(hook.get("command", ""))).name in managed_scripts
                for hook in commands if isinstance(hook, dict)
            )
            if not owned:
                retained.append(group)
        hooks[event] = retained + additions
    if "statusLine" in fragment:
        current["statusLine"] = fragment["statusLine"]
    return (json.dumps(current, indent=2, sort_keys=True) + "\n").encode(), fragment["hooks"]


def _installed_document(path: Path) -> dict:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise ValueError("prompt install state is not a regular file")
    return json.loads(path.read_text(encoding="utf-8"))


def _adoption_manifest(path: Path | None) -> dict[Path, tuple[str, str]]:
    if path is None or not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise ValueError("adoption manifest is not a regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("version") != 1:
        raise ValueError("adoption manifest version is unsupported")
    return {
        Path(target): (record["symlink_target"], record["sha256"])
        for target, record in value.get("targets", {}).items()
    }


def _adopted_directories(
    targets: dict[Path, tuple[bytes, int]], adoption: dict[Path, tuple[str, str]],
    home: Path, vscode_root: Path,
) -> set[Path]:
    adopted: set[Path] = set()
    roots = (home, vscode_root)
    for target in targets:
        for parent in target.parents:
            if parent in roots:
                break
            if not parent.is_symlink():
                continue
            declared = adoption.get(parent)
            if (declared is None or os.readlink(parent) != declared[0]
                    or _directory_digest(parent) != declared[1]):
                raise ValueError("legacy directory symlink does not match adoption manifest")
            adopted.add(parent)
            break
    return adopted


def _directory_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise ValueError("legacy adoption directory contains an unsafe entry")
        if path.is_file():
            relative = path.relative_to(directory).as_posix().encode()
            content = path.read_bytes()
            digest.update(relative + b"\0" + content)
    return digest.hexdigest()


def _require_safe_parent(target: Path, home: Path, vscode_root: Path) -> None:
    roots = tuple(root.resolve() for root in (home, vscode_root))
    resolved_parent = target.parent.resolve()
    if not any(resolved_parent == root or root in resolved_parent.parents for root in roots):
        raise ValueError("prompt consumer target escapes its root")


def write_projection_manifest(
    repository: Path,
    projection_root: Path,
    installed_root: Path,
    generator_path: str,
) -> Path:
    """Bind an existing regular-file projection to the repository's current commit."""
    commit = _git(repository, "rev-parse", "HEAD^{commit}").strip()
    generator = _safe_path(generator_path)
    outputs = _compiled_outputs(projection_root)
    return _write_manifest(repository, commit, projection_root, installed_root, generator, outputs)


def _source_entries(repository: Path, commit: str) -> dict[str, tuple[int, str]]:
    result = _git_bytes(repository, "ls-tree", "-rz", "--full-tree", commit)
    entries: dict[str, tuple[int, str]] = {}
    folded: set[str] = set()
    for record in filter(None, result.split(b"\0")):
        metadata, raw_path = record.split(b"\t", 1)
        mode_text, kind, blob = metadata.decode("ascii").split()
        try:
            path = _safe_path(raw_path.decode("utf-8"))
        except (UnicodeError, ValueError) as error:
            raise ValueError("unsafe committed source path") from error
        key = path.as_posix().casefold()
        if key in folded or kind != "blob" or mode_text not in {"100644", "100755"}:
            raise ValueError("unsafe committed source entry")
        folded.add(key)
        entries[path.as_posix()] = (int(mode_text[-3:], 8), blob)
    return entries


def _materialize(repository: Path, entries: dict[str, tuple[int, str]], root: Path) -> None:
    root.mkdir(mode=0o700)
    for value, (mode, blob) in entries.items():
        destination = root / value
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination.write_bytes(_git_bytes(repository, "show", blob))
        destination.chmod(mode)


def _compiled_outputs(root: Path) -> dict[str, tuple[int, bytes]]:
    candidates = [root / name for name in _OUTPUT_FILES]
    for directory in (*_OUTPUT_ROOTS, *_PASSTHROUGH_ROOTS):
        location = root / directory
        if location.exists():
            candidates.extend(location.rglob("*"))
    outputs: dict[str, tuple[int, bytes]] = {}
    folded: set[str] = set()
    for path in sorted(candidates):
        if path.is_symlink() or (path.exists() and not path.is_file() and not path.is_dir()):
            raise ValueError("compiled projection contains a non-regular output")
        if not path.is_file():
            continue
        relative = _safe_path(path.relative_to(root).as_posix())
        key = relative.as_posix().casefold()
        if key in folded:
            raise ValueError("compiled projection has a case-fold collision")
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode not in {0o600, 0o644, 0o755}:
            raise ValueError("compiled projection has an unsafe mode")
        folded.add(key)
        outputs[relative.as_posix()] = (mode, path.read_bytes())
    if not outputs:
        raise ValueError("prompt generator produced no projection")
    return outputs


def _normalize_output_modes(root: Path) -> None:
    """Remove ambient umask from generated regular-file projection modes."""
    candidates = [root / name for name in _OUTPUT_FILES]
    for directory in _OUTPUT_ROOTS:
        location = root / directory
        if location.exists():
            candidates.extend(location.rglob("*"))
    for path in candidates:
        if path.is_symlink():
            raise ValueError("compiled projection contains a non-regular output")
        if path.is_file():
            path.chmod(0o644)


def _copy_passthrough_outputs(root: Path, entries: dict[str, tuple[int, str]]) -> None:
    """Retain committed hook sources that are installed without generation."""
    for relative in entries:
        path = PurePosixPath(relative)
        if path.parts[0] not in _PASSTHROUGH_ROOTS:
            continue
        output = root / relative
        if output.is_symlink() or not output.is_file():
            raise ValueError("passthrough projection output is not a regular file")
        output.chmod(0o755 if output.suffix == ".sh" else 0o644)


def _write_manifest(
    repository: Path,
    commit: str,
    projection_root: Path,
    _installed_root: Path,
    generator: PurePosixPath,
    outputs: dict[str, tuple[int, bytes]],
) -> Path:
    tree = _git(repository, "rev-parse", f"{commit}^{{tree}}").strip()
    timestamp = _git(repository, "show", "-s", "--format=%cI", commit).strip()
    generator_blob = _git(repository, "rev-parse", f"{commit}:{generator.as_posix()}").strip()
    generator_bytes = _git_bytes(repository, "show", generator_blob)
    manifest = {
        "generator": {
            "blob": generator_blob,
            "path": generator.as_posix(),
            "sha256": hashlib.sha256(generator_bytes).hexdigest(),
        },
        "outputs": [
            {
                "consumers": _consumer_kinds(relative),
                "mode": f"{mode:04o}",
                "path": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
            for relative, (mode, content) in sorted(outputs.items())
        ],
        "source_commit": commit,
        "source_timestamp": timestamp,
        "source_tree": tree,
        "version": 1,
    }
    destination = projection_root / MANIFEST_NAME
    destination.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    destination.chmod(0o600)
    return destination


def _consumer_kinds(relative: str) -> tuple[str, ...]:
    path = PurePosixPath(relative)
    if relative == "AGENTS.md":
        return ("home-agents",)
    if relative == "instructions.md":
        return ("home-claude", "claude-claude", "vscode-instructions")
    if relative == "org.json":
        return ("claude-org",)
    if len(path.parts) == 2 and path.parts[0] == "agents":
        return ("claude-agent", "vscode-agent")
    if len(path.parts) == 3 and path.parts[0] == "skills":
        return ("claude-skill", "codex-skill", "vscode-skill")
    if len(path.parts) == 2 and path.parts[0] == "rules":
        return ("claude-rule", "vscode-rule")
    if len(path.parts) == 2 and path.parts[0] == "hooks" and path.suffix == ".sh":
        return ("claude-hook",)
    if relative in {"hooks/hooks.json", "hooks/turn-end-asks.md"}:
        return ("claude-settings-merge",)
    raise ValueError("projection output has no consumer mapping")


def _safe_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("unsafe repository path")
    return path


def _git(repository: Path, *arguments: str) -> str:
    return _git_bytes(repository, *arguments).decode("utf-8")


def _git_bytes(repository: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments], capture_output=True, timeout=30
    )
    if result.returncode:
        raise ValueError("Git prompt source operation failed")
    return result.stdout
