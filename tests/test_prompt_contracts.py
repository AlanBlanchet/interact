import hashlib
import io
import json
import os
import sqlite3
import stat
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import interact_contracts
from pydantic import ValidationError

from interact.prompt_cache import _PromptCache
from interact.prompt_client import _PromptClient
from interact_contracts import PromptCatalogPage, PromptChannelEntry, PromptKey, PromptRevision


def test_file_manifest_content_matches_its_declared_digest() -> None:
    root = Path(__file__).resolve().parents[1] / "prompts"
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["version"] == 1
    for entry in manifest["prompts"]:
        content = (root / entry["path"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == entry["digest"]
        PromptKey.model_validate(entry["key"])


def test_contracts_reject_invalid_identity_and_content() -> None:
    with pytest.raises(ValidationError):
        PromptKey(namespace="Tenant/Secret", slug="system")
    content = "bounded prompt"
    with pytest.raises(ValidationError):
        PromptRevision(
            key=PromptKey(namespace="interact", slug="system"), revision=uuid4(),
            digest="0" * 64, content=content, source_commit="abc", created_at=datetime.now(UTC),
        )


def test_public_contracts_include_immutable_execution_prompt_binding() -> None:
    assert hasattr(interact_contracts, "PromptExecutionRef")


def test_cache_scopes_catalog_and_exact_revision_by_account(tmp_path: Path) -> None:
    key = PromptKey(namespace="interact", slug="system")
    records = []
    for account in ("tenant-a", "tenant-b"):
        content = f"bounded prompt for {account}"
        digest = hashlib.sha256(content.encode()).hexdigest()
        revision_id = uuid4()
        revision = PromptRevision(
            key=key, revision=revision_id, digest=digest, content=content,
            source_commit="abc", created_at=datetime.now(UTC),
        )
        page = PromptCatalogPage(
            entries=(PromptChannelEntry(
                key=key, channel="stable", revision=revision_id, digest=digest, lock_version=1,
            ),), server_timestamp=datetime.now(UTC),
        )
        records.append((account, content, digest, revision, page))
    cache = _PromptCache(tmp_path / "prompts.sqlite3")
    try:
        for account, _, _, revision, page in records:
            cache.apply(account, page, (revision,))
        for account, content, digest, _, page in records:
            assert cache.catalog(account) == page
            assert cache.resolve(account, key, "stable", digest) == content
            foreign_digest = next(row[2] for row in records if row[0] != account)
            with pytest.raises(LookupError):
                cache.resolve(account, key, "stable", foreign_digest)
    finally:
        cache.close()
    with sqlite3.connect(tmp_path / "prompts.sqlite3") as database:
        for table in ("revisions", "channels"):
            columns = {row[1] for row in database.execute(f"PRAGMA table_info({table})")}
            assert "account" in columns


@pytest.mark.parametrize("preexisting", [False, True], ids=["new", "insecure-existing"])
def test_cache_database_is_private(tmp_path: Path, preexisting: bool) -> None:
    path = tmp_path / "prompts.sqlite3"
    if preexisting:
        sqlite3.connect(path).close()
        path.chmod(0o666)

    cache = _PromptCache(path)
    cache.close()

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_cache_rejects_path_substitution_before_sqlite_uses_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "prompts.sqlite3"
    foreign = tmp_path / "foreign.sqlite3"
    real_connect = sqlite3.connect

    def substitute(database: Path):
        path.rename(tmp_path / "owned.sqlite3")
        foreign.touch()
        os.link(foreign, path)
        return real_connect(database)

    monkeypatch.setattr(sqlite3, "connect", substitute)
    with pytest.raises(OSError, match="changed before SQLite opened it"):
        _PromptCache(path)


def test_cache_owner_check_is_portable_when_getuid_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(os, "getuid")
    cache = _PromptCache(tmp_path / "prompts.sqlite3")
    cache.close()


def test_cache_validates_revision_identity_and_applies_catalog_delta(tmp_path: Path) -> None:
    key = PromptKey(namespace="interact", slug="system")
    content = "bounded prompt"
    digest = hashlib.sha256(content.encode()).hexdigest()
    revision = PromptRevision(
        key=key, revision=uuid4(), digest=digest, content=content,
        source_commit="abc", created_at=datetime.now(UTC),
    )
    entry = PromptChannelEntry(
        key=key, channel="stable", revision=revision.revision, digest=digest, lock_version=1,
    )
    cache = _PromptCache(tmp_path / "prompts.sqlite3")
    try:
        mismatch = entry.model_copy(update={"revision": uuid4()})
        with pytest.raises(ValueError, match="matching verified revision"):
            cache.apply("tenant", PromptCatalogPage(entries=(mismatch,), server_timestamp=datetime.now(UTC)), (revision,))
        page = PromptCatalogPage(
            entries=(entry,), cursor="next-page", server_timestamp=datetime.now(UTC),
        )
        cache.apply("tenant", page, (revision,))
        assert cache.catalog("tenant").cursor == "next-page"
        cache.apply("tenant", PromptCatalogPage(
            entries=(), removed=(key,), cursor="done", server_timestamp=datetime.now(UTC),
        ), ())
        assert cache.catalog("tenant").entries == ()
        assert cache.catalog("tenant").cursor == "done"
    finally:
        cache.close()


def test_prompt_sync_failure_never_mutates_an_empty_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*_args, **_kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    cache = _PromptCache(tmp_path / "prompts.sqlite3")
    try:
        with pytest.raises(urllib.error.URLError):
            _PromptClient("http://127.0.0.1:1", "unavailable").sync("tenant", cache)
        with pytest.raises(LookupError, match="not cached"):
            cache.catalog("tenant")
    finally:
        cache.close()


def test_prompt_client_caps_untrusted_http_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = io.BytesIO(b"x" * (_PromptClient._MAX_RESPONSE_BYTES + 1))
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: response)
    cache = _PromptCache(tmp_path / "prompts.sqlite3")
    try:
        with pytest.raises(ValueError, match="size limit"):
            _PromptClient("http://127.0.0.1:1", "synthetic").sync("tenant", cache)
    finally:
        cache.close()
