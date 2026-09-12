"""Persisted, front-end-agnostic user settings at ``~/.interact/config.env``.

The VS Code extension stores model choices and API keys in its settings UI and
secret store, then injects them as ``INTERACT_*`` / ``*_API_KEY`` env vars when it
spawns the server. Clients without such a UI (Claude Code, Cursor, Codex, Zed, …)
have no equivalent — so ``interact config`` writes here, and ``interact mcp``
applies it to the environment before the server starts. Configure once, and every
client that launches ``interact mcp`` picks it up.

Format is a plain ``KEY=VALUE`` env file (no external dependency to parse it). The
file is chmod ``600`` because it may hold ``*_API_KEY`` secrets.
"""

import os
import re
from pathlib import Path

from interact.config.schema import by_key

# An already-environment-shaped name: all-caps, digits/underscores, no dots or dashes. A friendly
# setting key is always dotted (group.field), so this only matches real env vars.
_ENV_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]*")

# Shell metacharacters that make a raw `KEY=value` line break (or execute) when the file is
# SOURCED — `KEY=cap.vlm and aa.intelligence >= 40` once ran `and` as a command on every source.
# Quoting at write time keeps the value intact for both readers: pydantic/python-dotenv strip the
# quotes, bash keeps the value whole instead of executing it.
_NEEDS_QUOTE_RE = re.compile(r"[^\w@%+=:,./-]")


def _quote_if_needed(value: str) -> str:
    """Single-quote a value containing characters bash would act on."""
    if _NEEDS_QUOTE_RE.search(value):
        return "'" + value.replace("'", "'\\''") + "'"
    return value


def _unquote(value: str) -> str:
    """Strip ONE level of single quotes the writer may have added.

    The file is one store with two readers — python-dotenv/pydantic (which
    strip quotes themselves) and `source` (which needs them). Reading through
    this class must return the value as SET, never the quoted form, or a
    criterion written with spaces parses as `'cap.vlm…` and fails.
    """
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("'\\'", "'")
    return value


class UserConfig:
    """The ``~/.interact/config.env`` store: read / set / unset / apply."""

    PATH = Path.home() / ".interact" / "config.env"
    _process_interact_env: dict[str, str] | None = None

    @classmethod
    def process_interact_env(cls) -> dict[str, str]:
        """The host/launcher's INTERACT_* values before this class applies config.env."""
        if cls._process_interact_env is None:
            cls._process_interact_env = {
                name: value
                for name, value in os.environ.items()
                if name.startswith("INTERACT_")
            }
        return dict(cls._process_interact_env)

    @classmethod
    def normalize_key(cls, key: str) -> str:
        """Map a friendly key to its environment-variable name.

        ``image.model`` / ``image-model`` → ``INTERACT_IMAGE_MODEL``; a key already in env form —
        ``OPENAI_API_KEY``, ``AWS_ACCESS_KEY_ID``, ``AZURE_API_BASE``, any ``INTERACT_*`` — is kept
        verbatim. The env-shape guard runs on the RAW key: after ``.replace(".", "_")`` a friendly
        key like ``image.model`` becomes ``IMAGE_MODEL``, indistinguishable from a real env var,
        so a provider cred whose name doesn't end in ``_API_KEY`` (AWS/Azure/Vertex) must be
        recognised BEFORE that rewrite — else it's stored under a dead ``INTERACT_*`` alias no SDK
        reads, and the provider silently never authenticates.
        """
        if _ENV_NAME_RE.fullmatch(key):
            return key
        setting = by_key(key)
        if setting is not None:
            return setting.env
        env = key.replace(".", "_").replace("-", "_").upper()
        if env.startswith("INTERACT_") or env.endswith("_API_KEY"):
            return env
        return f"INTERACT_{env}"

    @classmethod
    def read(cls) -> dict[str, str]:
        if not cls.PATH.exists():
            return {}
        out: dict[str, str] = {}
        for line in cls.PATH.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, _, value = stripped.partition("=")
            out[name.strip()] = _unquote(value.strip())
        return out

    @classmethod
    def get(cls, key: str) -> str | None:
        return cls.read().get(cls.normalize_key(key))

    @classmethod
    def set(cls, key: str, value: str) -> str:
        data = cls.read()
        env = cls.normalize_key(key)
        data[env] = value
        cls._write(data)
        return env

    @classmethod
    def unset(cls, key: str) -> bool:
        data = cls.read()
        env = cls.normalize_key(key)
        existed = data.pop(env, None) is not None
        if existed:
            cls._write(data)
        return existed

    @classmethod
    def apply(cls) -> None:
        """Load persisted settings into ``os.environ`` without overriding live vars."""
        cls.process_interact_env()
        for name, value in cls.read().items():
            os.environ.setdefault(name, value)

    @classmethod
    def _write(cls, data: dict[str, str]) -> None:
        cls.PATH.parent.mkdir(parents=True, exist_ok=True)
        body = "".join(
            f"{name}={_quote_if_needed(value)}\n" for name, value in sorted(data.items())
        )
        cls.PATH.write_text(body)
        cls.PATH.chmod(0o600)
