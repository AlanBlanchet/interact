#!/usr/bin/env python3
"""Materialize the current developer's agent/prompt customizations into this repo's overlay.

VS Code discovers workspace-level customizations from four `.github/` subfolders:
  .github/agents/             <name>.agent.md
  .github/instructions/       <name>.instructions.md
  .github/prompts/            <name>.prompt.md
  .github/skills/             <name>/SKILL.md

Those folders are gitignored — they are per-developer, never committed. Any developer who
clones interact points this script at THEIR OWN prompts store and gets their own set; the
default points at each user's live VS Code prompt folder (already synced from their own
source of truth, so a `skillshare`-style store only enters the picture via --source):

  python scripts/sync_prompts.py                       # from ~/.config/Code/User/prompts
  python scripts/sync_prompts.py --source repo/agents  # a specific folder of <name>.md
  python scripts/sync_prompts.py --source repo/agents --ext .md

  # an ai-prompts checkout (Anthropic-standard layout) maps by extension:
  python scripts/sync_prompts.py --source ~/dev/ai-prompts/agents --ext .md --into agents
  python scripts/sync_prompts.py --source ~/dev/ai-prompts/rules  --ext .md --into instructions

--dry-run reports what would land without writing. A manifest is always written to
.github/agents/.sync-prompts.json so librarian/others can re-materialize exactly the same
overlay after editing the source store. Re-running re-syncs: symlinks are re-pointed,
copies are overwritten from the source of truth, and overlay entries with no source
counterpart are pruned (safety: pruning happens only on a non-dry run).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OVERLAY_DIRS = ("agents", "instructions", "prompts", "skills")
_MANIFEST = REPO_ROOT / ".github" / "agents" / ".sync-prompts.json"

# Default per-developer source: this machine's VS Code user prompt folder.
_DEFAULT_SOURCE = Path.home() / ".config" / "Code" / "User" / "prompts"

# Route a VS Code flat file name (<name>.<layer>.<ext>) to its overlay folder + final name.
# Returns (overlay_dir, final_rel_name) or None to keep the file where the layer says.
_FLAT_ROUTES = {
    "agent": ("agents", lambda stem, ext: f"{stem}.agent.md"),
    "skill": ("skills", lambda stem, ext: f"{stem}/SKILL.md"),
    "prompt": ("prompts", lambda stem, ext: f"{stem}.prompt.md"),
    "instructions": ("instructions", lambda stem, ext: f"{stem}.instructions.md"),
}


def _route(src: Path, *, into: str | None, ext: str) -> tuple[str, str] | None:
    """Map one source file to (overlay subfolder, relative name). None → skip."""
    if src.suffix != ext:
        return None
    if into:  # uniform folder for a uniform source (e.g. agents/ → .github/agents/)
        return into, f"{src.stem}.{_overlay_ext(into)}" if into != "skills" else f"{src.stem}/SKILL.md"
    # Flat VS Code prompts dir: <name>.<layer>.<ext> (layer possibly multi-part, e.g. skill.instructions).
    parts = src.stem.split(".")
    layer = parts[-1] if len(parts) > 1 else None
    name = parts[0]
    if layer in _FLAT_ROUTES:
        overlay, render = _FLAT_ROUTES[layer]
        return overlay, render(src.stem[: -len(layer) - 1], ext)
    if len(parts) > 2 and parts[-2:] == ["skill", "instructions"]:  # <name>.skill.instructions.md
        return "instructions", f"{name}.skill.instructions.md"
    return None  # a flat file with no recognizable layer → skipped, not guessed


def _overlay_ext(overlay: str) -> str:
    return {"agents": "agent.md", "prompts": "prompt.md", "instructions": "instructions.md"}[overlay]


def _materialize(src: Path, dst: Path, mode: str, *, dry: bool) -> str:
    """Link (or copy) one file. Returns the action taken for the report."""
    action = "link" if mode == "symlink" else "copy"
    if dry:
        return f"would-{action}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        if dst.is_symlink() and dst.resolve() == src.resolve():
            return "ok"
        dst.unlink()
    if mode == "symlink":
        dst.symlink_to(src.resolve())
    else:
        shutil.copy2(src, dst)
    return action


def sync(source: Path, *, into: str | None, ext: str, mode: str, dry: bool) -> int:
    if not source.is_dir():
        print(f"ERROR: source {source} is not a directory", file=sys.stderr)
        return 1
    files = sorted(p for p in source.iterdir() if p.is_file() and p.suffix == ext)
    if not files:
        print(f"ERROR: no *{ext} files under {source}", file=sys.stderr)
        return 1

    kept: list[Path] = []
    report: list[str] = []
    for src in files:
        routed = _route(src, into=into, ext=ext)
        if routed is None:
            report.append(f"skip    {src.name}")
            continue
        overlay, rel = routed
        dst = REPO_ROOT / ".github" / overlay / rel
        kept.append(dst)
        report.append(f"{_materialize(src, dst, mode, dry=dry):>10}  .github/{overlay}/{rel} <- {src.name}")

    if not dry:
        # Prune overlay entries with no source counterpart (only folders we actually touched).
        touched = {p.relative_to(REPO_ROOT).parts[1] for p in kept} if kept else set()
        for overlay in touched:
            odir = REPO_ROOT / ".github" / overlay
            for existing in sorted(odir.rglob("*")):
                if existing.is_file() and existing not in kept and existing.name != _MANIFEST.name:
                    existing.unlink()

    for line in report:
        print(line)
    print(f"\n{'would materialize' if dry else 'materialized'} {len(kept)}/{len(files)} files from {source}")
    if not dry:
        _MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        _MANIFEST.write_text(
            json.dumps(
                {"source": str(source), "into": into, "ext": ext, "mode": mode,
                 "files": [str(p.relative_to(REPO_ROOT)) for p in kept]},
                indent=2,
            )
            + "\n"
        )
        print(f"manifest: {_MANIFEST.relative_to(REPO_ROOT)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, default=_DEFAULT_SOURCE,
                    help=f"folder of <name>.md files to materialize (default: {_DEFAULT_SOURCE})")
    ap.add_argument("--ext", default=".md", help="source file extension to include (default: .md)")
    ap.add_argument("--into", choices=OVERLAY_DIRS, default=None,
                    help="uniform overlay folder for a uniform source (agents/instructions/prompts/skills); "
                         "omit for a VS Code flat prompts dir, where each file's own suffix routes it")
    ap.add_argument("--mode", choices=("symlink", "copy"), default="symlink",
                    help="symlink stays live-linked to the source (default); copy snapshots it")
    ap.add_argument("--dry-run", action="store_true", help="report what would land, write nothing")
    args = ap.parse_args()
    return sync(args.source, into=args.into, ext=args.ext, mode=args.mode, dry=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
