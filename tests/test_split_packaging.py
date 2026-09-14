"""Build acceptance for the post-split public Python distribution."""

import os
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def build_cache():
    """Build tools use the runner's cache; per-test HOME isolates user settings."""
    return subprocess.run(["uv", "cache", "dir"], check=True, capture_output=True, text=True).stdout.strip()


def test_root_build_configuration_targets_only_the_new_python_packages() -> None:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert configuration["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/interact",
    ]
    assert configuration["project"]["scripts"]["interact"] == "interact.cli:main"


def test_root_wheel_contains_only_the_local_public_import_and_cli(tmp_path: Path, build_cache: str) -> None:
    source = tmp_path / "source"
    source.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE", ".gitignore"):
        shutil.copyfile(ROOT / name, source / name)
    shutil.copytree(ROOT / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__"))
    result = subprocess.run(
        ["uv", "build", "--wheel", "--cache-dir", build_cache, "--out-dir", str(tmp_path)],
        cwd=source,
        capture_output=True,
        text=True,
        env=os.environ | {"UV_OFFLINE": "1", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    wheel, = tmp_path.glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert any(name.startswith("interact/") for name in names)
        assert not any(name.startswith("interact_core/") for name in names)
        entry_points, = (name for name in names if name.endswith(".dist-info/entry_points.txt"))
        assert "interact = interact.cli:main" in archive.read(entry_points).decode()
        metadata_name, = (name for name in names if name.endswith(".dist-info/METADATA"))
        assert re.search(r"^Requires-Dist: interact-core\s*@ git\+https://github\.com/AlanBlanchet/interact-core\.git@[0-9a-f]{40}$", archive.read(metadata_name).decode(), re.MULTILINE)
    subprocess.run(
        [sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import interact", str(wheel)],
        cwd=tmp_path,
        check=True,
    )
