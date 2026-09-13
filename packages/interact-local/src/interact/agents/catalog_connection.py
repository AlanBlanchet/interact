"""Explicit service connection for the server-owned agent catalog.

Connection settings and private preview sessions persist separately from catalog
content. Standard authentication uses the existing protected token-file reader.
"""

import fcntl
import hashlib
import ipaddress
import os
import stat
import tempfile
import warnings
from contextlib import contextmanager
from http.cookiejar import LWPCookieJar, LoadError
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from interact_core.accounts import Bootstrap
from pydantic import BaseModel, ConfigDict, model_validator

from interact.prompt_secret import read_prompt_token


class CatalogConnectionError(ValueError):
    """A catalog connection that cannot be used without changing its configuration."""


class CatalogAuthenticationError(CatalogConnectionError):
    """Authentication or workspace access was refused; cached access is forbidden."""


class CatalogConnection(BaseModel):
    """Validated connection settings, separate from replaceable catalog content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoint: str
    workspace_id: UUID | None = None
    auth_mode: Literal["preview", "token"]
    token_file: Path | None = None

    @model_validator(mode="after")
    def validate_connection(self) -> Self:
        try:
            parsed = urlsplit(self.endpoint)
            parsed.port
        except ValueError as error:
            raise ValueError("invalid catalog endpoint") from error
        if (
            parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
        ):
            raise ValueError("catalog endpoint must be an HTTP(S) origin without credentials")
        loopback = parsed.hostname == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            pass
        if self.auth_mode == "preview" and not loopback:
            raise ValueError("preview authentication requires an explicit loopback endpoint")
        if not loopback and parsed.scheme != "https":
            raise ValueError("remote catalog authentication requires HTTPS")
        if (self.auth_mode == "token") != (self.token_file is not None):
            raise ValueError("token authentication requires a token file; preview does not accept one")
        if self.token_file is not None and not self.token_file.is_absolute():
            raise ValueError("catalog token-file path must be absolute")
        return self

    @classmethod
    def path(cls) -> Path:
        # Circular layers: config.settings imports agents.providers for MEDIA_PROVIDERS;
        # providers imports catalog_connection for server-backed role discovery.
        from interact.config import UserConfig

        return UserConfig.PATH.parent / "agent-catalog-connection.json"

    @classmethod
    def load(cls, path: Path | None = None) -> Self | None:
        target = path if path is not None else cls.path()
        try:
            payload = target.read_bytes()
        except FileNotFoundError:
            return None
        if len(payload) > 16 * 1024:
            raise CatalogConnectionError("catalog connection exceeds its size limit")
        try:
            connection = cls.model_validate_json(payload)
        except ValueError as error:
            raise CatalogConnectionError("invalid catalog connection configuration") from error
        if connection.workspace_id is None:
            raise CatalogConnectionError("catalog connection has no selected workspace; sync again")
        return connection

    @staticmethod
    def replace_text(path: Path, payload: str) -> None:
        """Atomically replace one local document; a failed write keeps its predecessor."""
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def save(self, path: Path | None = None) -> None:
        if self.workspace_id is None:
            raise CatalogConnectionError("select a workspace before saving the catalog connection")
        self.replace_text(path if path is not None else self.path(), self.model_dump_json(indent=2))

    def connect(self, *, transport: httpx.BaseTransport | None = None) -> httpx.Client:
        headers = {"Origin": self.endpoint.rstrip("/")}
        if self.token_file is not None:
            headers["Authorization"] = f"Bearer {read_prompt_token(self.token_file)}"
        return httpx.Client(
            base_url=self.endpoint.rstrip("/"), headers=headers,
            timeout=5, follow_redirects=False, trust_env=False, transport=transport,
        )

    def authenticate(self, client: httpx.Client) -> Self:
        if self.auth_mode == "preview":
            with self.session_lock():
                if not client.cookies:
                    jar = LWPCookieJar(self.session_path())
                    try:
                        self.check_private_file(self.session_path())
                        # CookieJar's malformed-input warning includes the cookie line.
                        # Treat corruption as an empty session without exposing its contents.
                        with warnings.catch_warnings(record=True):
                            warnings.simplefilter("always")
                            jar.load(ignore_discard=True)
                    except FileNotFoundError:
                        pass
                    except LoadError:
                        jar.clear()
                        self.session_path().unlink(missing_ok=True)
                    client.cookies.update(jar)
                client.cookies.jar.clear_expired_cookies()
                if not client.cookies:
                    self.request(client, "POST", "/v1/auth/local-preview")
                resolved = self.resolve_workspace(client)
                jar = LWPCookieJar()
                for cookie in client.cookies.jar:
                    jar.set_cookie(cookie)
                payload = "#LWP-Cookies-2.0\n" + jar.as_lwp_str(ignore_discard=True)
                self.replace_text(self.session_path(), payload)
                if resolved != self:
                    self.replace_text(resolved.session_path(), payload)
                return resolved
        return self.resolve_workspace(client)

    def session_path(self) -> Path:
        identity = f"{self.endpoint.rstrip('/')}\n{self.auth_mode}\n{self.workspace_id}"
        key = hashlib.sha256(identity.encode()).hexdigest()
        return self.path().parent / "agent-catalog-sessions" / f"{key}.cookies"

    @staticmethod
    def check_private_file(path: Path) -> None:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise CatalogConnectionError("catalog session file must be private and owned by the current user")
        if info.st_size > 64 * 1024:
            raise LoadError("catalog session exceeds its size limit")

    @contextmanager
    def session_lock(self):
        path = self.session_path()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = path.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise CatalogConnectionError("catalog session directory must be private and owned by the current user")
        descriptor = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def resolve_workspace(self, client: httpx.Client) -> Self:
        # Token consumers can explicitly select their workspace. They need no cookie bootstrap.
        if self.workspace_id is not None:
            return self
        try:
            bootstrap = Bootstrap.model_validate_json(self.request(client, "GET", "/v1/bootstrap"))
        except ValueError as error:
            if isinstance(error, CatalogConnectionError):
                raise
            raise CatalogConnectionError("invalid catalog workspace bootstrap") from error
        return self.model_copy(update={"workspace_id": bootstrap.current_workspace_id})

    def request(self, client: httpx.Client, method: Literal["GET", "POST"], path: str) -> bytes:
        with client.stream(method, path) as response:
            workspace_refused = response.status_code == 404 and path.startswith("/v1/workspaces/")
            if response.status_code in {401, 403} or workspace_refused:
                if self.auth_mode == "preview":
                    self.session_path().unlink(missing_ok=True)
                    client.cookies.clear()
                raise CatalogAuthenticationError(
                    f"catalog access refused (HTTP {response.status_code}); cached access is disabled"
                )
            if response.status_code < 200 or response.status_code >= 300:
                raise CatalogConnectionError(f"catalog request failed (HTTP {response.status_code})")
            payload = bytearray()
            for chunk in response.iter_bytes():
                payload.extend(chunk)
                if len(payload) > 16 * 1024 * 1024:
                    raise CatalogConnectionError("catalog response exceeds its size limit")
            return bytes(payload)
