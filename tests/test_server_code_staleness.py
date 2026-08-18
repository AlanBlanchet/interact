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


def test_a_server_started_before_the_code_was_written_is_stale(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "thing.py").write_text("# edited just now\n")

    monkeypatch.setattr(reg, "_source_mtime", lambda: time.time())
    # Our own process started before that edit, by construction.
    assert reg.running_older_code(os.getpid())


def test_a_server_started_after_the_last_edit_is_current(monkeypatch):
    monkeypatch.setattr(reg, "_source_mtime", lambda: 0.0)  # source last touched at the epoch
    assert not reg.running_older_code(os.getpid())


def test_a_pid_that_is_gone_is_not_reported_as_stale(monkeypatch):
    monkeypatch.setattr(reg, "_source_mtime", lambda: time.time())
    assert not reg.running_older_code(2**31 - 1), "a dead pid is a pruning job, not a staleness one"


def test_doctor_flags_a_same_version_server_running_old_code(tmp_path, monkeypatch):
    """The case the version check cannot see: the version matches and the code does not."""
    monkeypatch.setattr(reg, "_runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(reg, "latest_version", lambda: "9.9.9")
    monkeypatch.setattr(reg, "_source_mtime", lambda: time.time())
    (tmp_path / "s.json").write_text(json.dumps({"pid": os.getpid(), "version": "9.9.9"}))

    stale = reg.stale_servers()

    assert [s["pid"] for s in stale] == [os.getpid()], (
        "a server on the current version but older code reported itself healthy"
    )
    assert stale[0].get("reason") == "code", stale[0]
