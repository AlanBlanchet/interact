"""Build acceptance for the post-split public Python distribution."""

import os
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_build_configuration_targets_only_the_new_python_packages() -> None:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert configuration["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "packages/interact-local/src/interact",
    ]
    assert configuration["project"]["scripts"]["interact"] == "interact.cli:main"


def test_root_wheel_contains_only_the_local_public_import_and_cli(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        check=True,
        env=os.environ | {"UV_OFFLINE": "1", "PYTHONDONTWRITEBYTECODE": "1"},
    )
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
