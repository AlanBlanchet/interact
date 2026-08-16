"""Adapters for the agent CLIs interact can supervise.

**The legal boundary lives here.** interact builds an argv, spawns the vendor's own binary, and
reads its stdout. It never reads, stores, forwards or proxies a credential — the CLI
authenticates itself with the user's own login, on the user's own machine. Anthropic's terms
forbid third parties *routing requests through* Free/Pro/Max credentials, and an enforcement wave
in early 2026 hit tools that did; running the documented headless mode (`claude -p`, which
Anthropic markets for scripts and CI) is a different act entirely. Never add a "sign in with
Claude" flow, never read a credentials file, never expose an endpoint backed by a subscription.

Cross-provider work needs no bespoke protocol: every one of these CLIs is an MCP *client*, and
interact is an MCP *server*. Handing a spawned agent interact's own server config (``mcp_config``)
is what lets a Claude agent spawn a Codex agent — they meet on MCP, which is vendor-neutral.
"""

import json
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import ClassVar

from interact.agents.events import AgentEvent


class AgentProvider(ABC):
    """How to launch one vendor's agent CLI and read what it emits."""

    name: ClassVar[str]
    binary: ClassVar[str]
    #: False when the flags below were written from documentation but never exercised against a
    #: real binary — the adapter says so instead of pretending to be tested.
    verified: ClassVar[bool] = True
    caveat: ClassVar[str | None] = None

    def available(self) -> bool:
        """Is the CLI installed? (Being logged in is the CLI's business, never ours.)"""
        return shutil.which(self.binary) is not None

    @abstractmethod
    def command(self, task: str, *, cwd: str, model: str | None,
                mcp_config: str | None, run_id: str) -> list[str]:
        """The argv to spawn for this task."""

    @abstractmethod
    def parse(self, line: str) -> AgentEvent | None:
        """One stdout line → a normalised event, or None if the line carries nothing."""

    def discover(self) -> list[dict]:
        """Agent sessions this provider can see that interact did NOT spawn — the user's own
        interactive windows included. Optional; a provider with no such view returns []."""
        return []


class ClaudeCodeProvider(AgentProvider):
    """Claude Code, driven through its documented headless mode.

    Flags verified against `claude --version` 2.1.233. `--output-format stream-json` REQUIRES
    `--verbose`; without it the CLI refuses and the run emits nothing parseable.
    """

    name = "claude"
    binary = "claude"

    def command(self, task: str, *, cwd: str, model: str | None,
                mcp_config: str | None, run_id: str) -> list[str]:
        argv = [
            self.binary, "-p", task,
            "--output-format", "stream-json",
            "--verbose",  # mandatory companion to stream-json
            # Our run id IS the vendor's session id, so `claude --resume <run_id>` works and no
            # mapping table can go stale.
            "--session-id", run_id,
        ]
        if model:
            argv += ["--model", model]
        if mcp_config:
            argv += ["--mcp-config", mcp_config]
        return argv

    def parse(self, line: str) -> AgentEvent | None:
        line = line.strip()
        if not line:
            return None
        try:
            raw = json.loads(line)
        except ValueError:
            return None  # a non-JSON line (a warning on stdout) is noise, not an event
        if not isinstance(raw, dict):
            return None
        kind = raw.get("type", "")
        sid = raw.get("session_id")

        if kind == "system" and raw.get("subtype") == "init":
            tools = raw.get("tools") or []
            return AgentEvent(kind="started", session_id=sid, raw_type=kind,
                              text=f"session up in {raw.get('cwd', '?')} ({len(tools)} tools)")

        if kind == "assistant":
            msg = raw.get("message") or {}
            usage = msg.get("usage") or {}
            texts, tool = [], None
            for block in msg.get("content") or []:
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool = block.get("name")
            if tool:
                return AgentEvent(kind="tool", tool=tool, session_id=sid, raw_type=kind,
                                  input_tokens=usage.get("input_tokens"),
                                  output_tokens=usage.get("output_tokens"))
            return AgentEvent(kind="text", text="".join(texts), session_id=sid, raw_type=kind,
                              input_tokens=usage.get("input_tokens"),
                              output_tokens=usage.get("output_tokens"))

        if kind == "rate_limit_event":
            info = raw.get("rate_limit_info") or {}
            status = info.get("status", "?")
            which = info.get("rateLimitType", "")
            return AgentEvent(kind="rate_limit", session_id=sid, raw_type=kind,
                              text=f"{which or 'rate'} limit: {status}")

        if kind == "result":
            usage = raw.get("usage") or {}
            failed = bool(raw.get("is_error"))
            return AgentEvent(
                kind="error" if failed else "done",
                session_id=sid, raw_type=kind,
                text=str(raw.get("stop_reason") or raw.get("subtype") or ""),
                cost_usd=raw.get("total_cost_usd"),
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
            )

        return AgentEvent(kind="other", session_id=sid, raw_type=kind)

    def discover(self) -> list[dict]:
        """`claude agents --json` lists every live Claude session — including the user's own
        interactive windows, which interact never spawned. That is what makes the supervisor a
        view of the whole machine rather than only of its own children."""
        if not self.available():
            return []
        try:
            out = subprocess.run(
                [self.binary, "agents", "--json", "--all"],
                capture_output=True, text=True, timeout=20, check=True,
            ).stdout
            found = json.loads(out)
        except (OSError, subprocess.SubprocessError, ValueError):
            return []
        return found if isinstance(found, list) else []


class CodexProvider(AgentProvider):
    """OpenAI's Codex CLI (Apache-2.0), driven through its documented `codex exec` mode.

    UNVERIFIED: codex is not installed on the machine this adapter was written on, so the flags
    come from documentation and have never been exercised. It says so rather than quietly
    building a command that may be wrong — and note OpenAI has publicly declined to clarify how
    their consumer-subscription automation terms apply to scripted CLI use, so the Claude path is
    the one to lean on until that's settled.
    """

    name = "codex"
    binary = "codex"
    verified = False
    caveat = ("unverified: built from docs, never run against a real binary; and OpenAI has not "
              "clarified how consumer-subscription terms apply to scripted use")

    def command(self, task: str, *, cwd: str, model: str | None,
                mcp_config: str | None, run_id: str) -> list[str]:
        argv = [self.binary, "exec", task, "--json"]
        if model:
            argv += ["--model", model]
        return argv

    def parse(self, line: str) -> AgentEvent | None:
        line = line.strip()
        if not line:
            return None
        try:
            raw = json.loads(line)
        except ValueError:
            return None
        if not isinstance(raw, dict):
            return None
        return AgentEvent(kind="other", raw_type=str(raw.get("type", "")), text=line[:200])


PROVIDERS: dict[str, AgentProvider] = {p.name: p for p in (ClaudeCodeProvider(), CodexProvider())}


def provider_for(name: str) -> AgentProvider:
    try:
        return PROVIDERS[name]
    except KeyError:
        known = ", ".join(sorted(PROVIDERS))
        raise ValueError(f"unknown agent provider {name!r} — known providers: {known}") from None


def available_providers() -> list[AgentProvider]:
    """Only the CLIs actually installed — the set a spawn request can legitimately name."""
    return [p for p in PROVIDERS.values() if p.available()]
