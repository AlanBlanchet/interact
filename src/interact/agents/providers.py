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
from pathlib import Path
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import ClassVar

from interact.agents.events import AgentEvent


#: A transcript is read by a human, and a 50k-char tool result is not read — it is scrolled past,
#: while bloating every refresh that parses the file. Keep the head, say what was cut.
_CLIP = 2000


def _clip(text: str, limit: int = _CLIP) -> str:
    text = text.strip()
    return text if len(text) <= limit else f"{text[:limit]}… (+{len(text) - limit} chars)"


def _summarise_input(value) -> str:
    """The tool's arguments as one readable line. A dict is rendered key=value with its most
    telling field first — the command, the path, the pattern — because that is what identifies
    the call at a glance."""
    if value is None:
        return ""
    if not isinstance(value, dict):
        return _clip(str(value), 300)
    lead = ("command", "file_path", "path", "pattern", "url", "query", "prompt")
    keys = [k for k in lead if k in value] + [k for k in value if k not in lead]
    return _clip(" ".join(f"{k}={value[k]!r}" for k in keys[:4]), 300)


class AgentProvider(ABC):
    """How to launch one vendor's agent CLI and read what it emits."""

    name: ClassVar[str]
    binary: ClassVar[str]
    #: Can a finished/running session be CONTINUED with a new message? This is what makes
    #: agent-to-agent messaging possible without inventing a mailbox: the recipient keeps its
    #: own context instead of being handed a cold summary of it.
    can_resume: ClassVar[bool] = False
    #: False when the flags below were written from documentation but never exercised against a
    #: real binary — the adapter says so instead of pretending to be tested.
    verified: ClassVar[bool] = True
    caveat: ClassVar[str | None] = None

    def available(self) -> bool:
        """Is the CLI installed? (Being logged in is the CLI's business, never ours.)"""
        return shutil.which(self.binary) is not None

    @abstractmethod
    def command(self, task: str, *, cwd: str, model: str | None, mcp_config: str | None,
                run_id: str, agent: str | None = None) -> list[str]:
        """The argv to spawn for this task. ``agent`` names a definition the CLI resolves itself
        (Claude Code reads ~/.claude/agents/<name>.md), so a run can BE 'visual-critic'."""

    def definition_path(self, agent: str) -> Path | None:
        """The file holding a definition's system prompt, or None when this CLI has no such
        concept. A link to it is what makes "what IS this agent" answerable from a panel."""
        return None

    def valid_definition(self, agent: str) -> bool:
        """Whether ``agent`` names a definition this CLI actually has.

        Checked at the edge, because the value arrives from a tool caller and ends up as a
        filesystem path that the VS Code panel offers as a clickable link — so a name like
        ``../../x`` would walk out of the definitions directory into something a person clicks.
        A CLI with no definitions concept accepts nothing, which is correct: there is nothing for
        the name to resolve to.
        """
        if not agent or "/" in agent or "\\" in agent or agent.startswith("."):
            return False  # absolute: this becomes a path, and a path is what must not escape
        known = self.agent_definitions()
        # Enumeration is ADVISORY. A CLI that cannot list its definitions — none installed yet, a
        # layout we do not know how to read — must not thereby reject every name: that would turn
        # a hardening check into an outage. Unknown is only an error when we can prove it unknown.
        return agent in known if known else True

    def agent_definitions(self) -> list[str]:
        """Names this CLI can resolve as ``agent=``, sorted. Empty when it has no such concept.

        A caller — often an agent, which cannot ask a follow-up question — has no other way to
        learn which definitions exist, so a capability nobody can enumerate is unusable.
        """
        return []

    @abstractmethod
    def parse(self, line: str) -> AgentEvent | None:
        """One stdout line → a normalised event, or None if the line carries nothing."""

    def resume_command(self, run_id: str, message: str) -> list[str]:
        """The argv that delivers ``message`` into an existing session."""
        raise NotImplementedError(f"{type(self).__name__} cannot resume a session")

    def discover(self) -> list[dict]:
        """Agent sessions this provider can see that interact did NOT spawn — the user's own
        interactive windows included. Optional; a provider with no such view returns []."""
        return []


#: `system` subtypes that describe the HARNESS rather than the agent — token accounting and hook
#: lifecycle. They outnumbered the real steps in the activity view, burying the transparency the
#: panel exists for. Only known noise is dropped; an unrecognised subtype still comes through as
#: `other`, so a vendor adding an event cannot vanish silently.
_HARNESS_BOOKKEEPING = frozenset({"thinking_tokens", "hook_started", "hook_response"})

#: The parts of a prompt Claude reports separately. `input_tokens` alone is only the UNCACHED
#: remainder — a run whose 102k prompt was fully cached reports 2 there — so "context" has to sum
#: all three or it claims a number nobody would recognise.
_PROMPT_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def _prompt_tokens(usage: dict) -> int | None:
    """The whole prompt the model saw, or None when the vendor reported no usage at all (zero
    would render as a measurement of an empty context rather than as an absence)."""
    parts = [usage.get(f) for f in _PROMPT_FIELDS]
    known = [p for p in parts if isinstance(p, int)]
    return sum(known) if known else None


class ClaudeCodeProvider(AgentProvider):
    """Claude Code, driven through its documented headless mode.

    Flags verified against `claude --version` 2.1.233. `--output-format stream-json` REQUIRES
    `--verbose`; without it the CLI refuses and the run emits nothing parseable.
    """

    name = "claude"
    binary = "claude"
    can_resume = True

    def command(self, task: str, *, cwd: str, model: str | None, mcp_config: str | None,
                run_id: str, agent: str | None = None) -> list[str]:
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
        if agent:
            argv += ["--agent", agent]
        if mcp_config:
            argv += ["--mcp-config", mcp_config]
        return argv

    def definition_path(self, agent: str) -> Path | None:
        path = Path.home() / ".claude" / "agents" / f"{agent}.md"
        return path if path.exists() else None

    def agent_definitions(self) -> list[str]:
        """Claude Code resolves ``--agent <name>`` against ``~/.claude/agents/<name>.md``."""
        try:
            return sorted(p.stem for p in (Path.home() / ".claude" / "agents").glob("*.md"))
        except OSError:
            return []

    def resume_command(self, run_id: str, message: str) -> list[str]:
        """Continue an existing session. Our run_id IS Claude Code's session id (we set it at
        spawn), so the recipient answers with its full context intact and the reply lands in the
        same transcript — which is what makes the exchange readable afterwards."""
        return [
            self.binary, "-p", message,
            "--resume", run_id,
            "--output-format", "stream-json",
            "--verbose",
        ]

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

        if kind == "system" and raw.get("subtype") in _HARNESS_BOOKKEEPING:
            return None  # about the harness's own machinery, not about what the agent did

        if kind == "system" and raw.get("subtype") == "task_started":
            return AgentEvent(kind="spawn", session_id=sid, raw_type=kind,
                              text=str(raw.get("description") or raw.get("agent_type") or "subagent"))

        if kind == "system" and raw.get("subtype") == "init":
            tools = raw.get("tools") or []
            return AgentEvent(kind="started", session_id=sid, raw_type=kind,
                              text=f"session up in {raw.get('cwd', '?')} ({len(tools)} tools)")

        if kind == "assistant":
            msg = raw.get("message") or {}
            usage = msg.get("usage") or {}
            texts, thinking, tool, tool_input = [], [], None, ""
            prompt_tokens = _prompt_tokens(usage)
            for block in msg.get("content") or []:
                btype = block.get("type")
                if btype == "text":
                    texts.append(block.get("text", ""))
                elif btype == "thinking":
                    thinking.append(block.get("thinking", ""))
                elif btype == "tool_use":
                    tool = block.get("name")
                    tool_input = _summarise_input(block.get("input"))
            if tool:
                return AgentEvent(kind="tool", tool=tool, tool_input=tool_input,
                                  session_id=sid, raw_type=kind,
                                  input_tokens=prompt_tokens,
                                  output_tokens=usage.get("output_tokens"))
            if thinking and not any(t.strip() for t in texts):
                return AgentEvent(kind="thinking", text=_clip("".join(thinking)),
                                  session_id=sid, raw_type=kind)
            return AgentEvent(kind="text", text="".join(texts), session_id=sid, raw_type=kind,
                              input_tokens=prompt_tokens,
                              output_tokens=usage.get("output_tokens"))

        if kind == "user":
            # Tool results come back as a USER turn — that is the other half of a transcript.
            msg = raw.get("message") or {}
            for block in msg.get("content") or []:
                if block.get("type") == "tool_result":
                    body = block.get("content")
                    if isinstance(body, list):
                        body = " ".join(b.get("text", "") for b in body if isinstance(b, dict))
                    return AgentEvent(kind="tool_result", text=_clip(str(body or "")),
                                      session_id=sid, raw_type=kind)
                # Text on a `user` line is what was ASKED of the agent — the other half of the
                # conversation. Unnamed, an activity view shows only the agent talking.
                if block.get("type") == "text":
                    return AgentEvent(kind="prompt", text=_clip(str(block.get("text") or "")),
                                      session_id=sid, raw_type=kind)
            return AgentEvent(kind="other", session_id=sid, raw_type=kind)

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

    def command(self, task: str, *, cwd: str, model: str | None, mcp_config: str | None,
                run_id: str, agent: str | None = None) -> list[str]:
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
