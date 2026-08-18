"""A server can be running OLD CODE while reporting a current version.

`interact doctor` is the project's delivery gate — "a fix isn't live until the running instance
runs it" — and it decided staleness purely by comparing the version a server loaded against the
version in the tree. But the project deliberately does NOT bump on every change ("bump once when
cutting a release"), so every fix between releases leaves the running servers frozen on old code
while the version string still matches. The gate reports all clear at exactly the moment it is
most needed: right after a fix lands.

A process cannot be running code that was written after it started, so the start time answers
this without any version bookkeeping.
"""

import json
import os
import time

from interact import server_registry as reg


# --- code-reviewer: ask the ARTIFACT, not the process ---
#
# Comparing a server's start time to the CHECKER's source tree is wrong whenever they are not the
# same tree: the registry recorded only {pid, version}, so a doctor run from an editable checkout
# judged a server that may be running an entirely different install. It also needed /proc, absent
# on macOS and Windows, and mtimes a `git checkout` or a reproducible wheel can move either way.
#
# A server knows exactly what it loaded, so it records that at startup and staleness becomes a
# comparison between two facts about ONE tree.


def test_a_server_records_the_source_it_loaded(tmp_path, monkeypatch):
    src = tmp_path / "pkg"
    src.mkdir()
    (src / "a.py").write_text("x")
    monkeypatch.setattr(reg, "_runtime_dir", lambda: tmp_path / "rt")
    monkeypatch.setattr(reg, "_source_root", lambda: src)

    path = reg.register_server()

    assert path is not None
    rec = json.loads(path.read_text())
    assert rec["source_root"] == str(src)
    assert rec["source_mtime"] >= (src / "a.py").stat().st_mtime


def test_a_server_whose_own_tree_moved_on_is_stale(tmp_path, monkeypatch):
    src = tmp_path / "pkg"
    src.mkdir()
    (src / "a.py").write_text("x")
    monkeypatch.setattr(reg, "_runtime_dir", lambda: tmp_path / "rt")
    monkeypatch.setattr(reg, "_source_root", lambda: src)
    monkeypatch.setattr(reg, "latest_version", lambda: reg.installed_version())
    reg.register_server()

    (src / "a.py").write_text("edited after it started")  # a fix lands
    os.utime(src / "a.py", (time.time() + 5, time.time() + 5))

    stale = reg.stale_servers()
    assert [s["reason"] for s in stale] == ["code"], stale


def test_a_server_on_a_DIFFERENT_tree_is_judged_against_its_own(tmp_path, monkeypatch):
    """The bug the recorded root removes: two checkouts, and the doctor in one was judging the
    server in the other against the wrong source."""
    theirs, ours = tmp_path / "theirs", tmp_path / "ours"
    for d in (theirs, ours):
        d.mkdir()
        (d / "a.py").write_text("x")
    monkeypatch.setattr(reg, "_runtime_dir", lambda: tmp_path / "rt")
    monkeypatch.setattr(reg, "_source_root", lambda: theirs)
    monkeypatch.setattr(reg, "latest_version", lambda: reg.installed_version())
    reg.register_server()

    # OUR tree churns; the server running THEIRS is untouched by it.
    os.utime(ours / "a.py", (time.time() + 60, time.time() + 60))
    monkeypatch.setattr(reg, "_source_root", lambda: ours)

    assert reg.stale_servers() == [], "judged against the checker's tree instead of its own"
