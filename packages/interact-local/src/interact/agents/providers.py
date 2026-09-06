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

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Protocol

from interact.agents.events import AgentEvent
from interact.agents.profiles import overlay_for
from interact.models import Model
from interact.processes import run_isolated_process

#: A transcript is read by a human, and a 50k-char tool result is not read — it is scrolled past,
#: while bloating every refresh that parses the file. Keep the head, say what was cut.
_CLIP = 2000
def _safe_process_detail(value: str) -> str:
    """One redacted diagnostic line; child output must never become a credential log."""
    value = re.sub(
        r"(?i)(api[_-]?key|auth[_-]?token|authorization|bearer)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        value,
    )
    value = re.sub(
        r"(?:[A-Za-z]:)?[/\\][^\s:]*media-jobs[/\\]job-[^\s:/\\]+(?:[/\\][^\s:]*)?",
        "[media-stage]",
        value,
    )
    return _clip(value.replace("\x00", ""), 500)


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


@dataclass(frozen=True)
class PermissionMode:
    """One answer to "how much may this agent do on its own?".

    Supervising a team is largely this decision, made per member: the researcher may read, the
    one refactoring may write, the one you have not watched yet plans and touches nothing. It is
    a per-run choice rather than a global setting because a team is heterogeneous by design.
    """

    id: str
    label: str
    detail: str
    #: True for a mode that acts without asking. Offered — refusing to expose it only pushes
    #: people to a terminal where the choice is invisible to the panel — but never rendered as an
    #: unremarkable option beside the others.
    unrestricted: bool = False


@dataclass(frozen=True)
class _MediaResult:
    text: str
    input_tokens: int
    output_tokens: int
    reported_cost_usd: float | None


@dataclass
class _MediaProcessFailure(Exception):
    message: str
    events: tuple[AgentEvent, ...] = ()
    exit_code: int | None = None
    stderr_bytes: int | None = None
    stderr_sha256: str | None = None
    timeout_phase: str | None = None
    elapsed_seconds: float | None = None

    def __str__(self) -> str:
        return self.message


class _MediaProcessTimeout(_MediaProcessFailure, TimeoutError):
    pass


def _failure_event_facts(events: list[AgentEvent]) -> tuple[AgentEvent, ...]:
    """Retain accounting/session facts without retaining provider text or tool payloads."""
    return tuple(
        AgentEvent(
            kind="other",
            session_id=event.session_id,
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
            cost_usd=event.cost_usd,
        )
        for event in events
        if event.session_id is not None
        or event.input_tokens is not None
        or event.output_tokens is not None
        or event.cost_usd is not None
    )


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
    auth_home_env: ClassVar[tuple[str, ...]] = ()

    def available(self) -> bool:
        """Is the CLI installed? (Being logged in is the CLI's business, never ours.)"""
        return shutil.which(self.binary) is not None

    def executable(self) -> str:
        """Resolved executable path, so PATH cannot change between auth preflight and execution."""
        found = shutil.which(self.binary)
        if found is None:
            raise FileNotFoundError(f"{self.name} CLI is not installed")
        return str(Path(found).resolve())

    def subscription_env(
        self, base: dict[str, str] | None = None, *, temp_dir: Path | None = None
    ) -> dict[str, str]:
        """Minimal environment for a subscription-authenticated child.

        In particular, API keys, auth-token overrides and base URLs are absent.  This makes an
        existing API key unable to silently take precedence over the user's Claude.ai/ChatGPT
        subscription and keeps unrelated credentials out of child tools and diagnostics.
        """
        source = os.environ if base is None else base
        exact = {
            "HOME", "PATH", "USER", "LOGNAME", "SHELL", "LANG", "TERM",
            "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
            "http_proxy", "https_proxy", "no_proxy", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
            "XDG_CACHE_HOME",
        }
        exact.update(self.auth_home_env)
        env = {
            key: value
            for key, value in source.items()
            if key in exact or key.startswith("LC_")
        }
        if temp_dir is not None:
            env["TMPDIR"] = str(temp_dir)
        return env

    def auth_command(self) -> list[str]:
        """Non-interactive command reporting how this CLI is authenticated."""
        raise NotImplementedError

    def accepts_subscription_auth(self, stdout: str, stderr: str) -> bool:
        """True only for the vendor's consumer-subscription login, never API-backed auth."""
        raise NotImplementedError

    async def subscription_authenticated(
        self, env: dict[str, str], *, timeout: float = 10
    ) -> bool:
        """Run the CLI's own auth-status command without reading a credential store."""
        argv = self.auth_command()
        try:
            returncode, stdout_bytes, stderr_bytes = await run_isolated_process(
                argv, cwd=Path.cwd(), env=env, timeout=timeout
            )
        except (OSError, TimeoutError):
            return False
        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")
        return returncode == 0 and self.accepts_subscription_auth(stdout, stderr)

    #: Catalog providers whose models this CLI runs through its OWN login — no API key in our env.
    native_providers: frozenset[str] = frozenset()

    def can_run(self, model: Model, env: dict[str, str]) -> bool:
        """Whether this CLI can be pointed at `model` at all — the pool a criterion chooses from.
        A criterion once picked the cheapest VLM in the whole catalog, a Gemini id, and handed it
        to the claude binary. Native = yes; anything else = no, unless a subclass knows a route."""
        return model.provider in self.native_providers

    def model_id_for(self, model: Model) -> str:
        """What a resolved criterion hands on: a bare id for a native model, `provider/id` for one
        that must be routed, so `resolve_model`'s overlay fires."""
        return model.id if model.provider in self.native_providers else f"{model.provider}/{model.id}"

    @abstractmethod
    def command(self, task: str, *, cwd: str, model: str | None, mcp_config: str | None,
                run_id: str, agent: str | None = None,
                permission_mode: str | None = None,
                allowed_tools: list[str] | None = None) -> list[str]:
        """The argv to spawn for this task. ``agent`` names a definition the CLI resolves itself
        (Claude Code reads ~/.claude/agents/<name>.md), so a run can BE 'visual-critic'."""

    def permission_modes(self) -> list[PermissionMode]:
        """How much autonomy this CLI can be told to grant, or empty when we have not VERIFIED
        its flag against a real binary.

        Empty is the honest default. A guessed flag either fails the spawn or — the bad case —
        is accepted with a meaning we assumed, so the agent runs with permissions nobody chose.
        """
        return []

    def _permission_flag(self, mode: str | None) -> list[str]:
        """``--permission-mode <mode>`` when one was chosen, after checking it is one of ours.

        The value arrives from a tool caller and ends up on a command line, so an unknown one is
        refused at the edge rather than passed through: a caller could otherwise smuggle a second
        flag in through this field. No mode means no flag at all — the person's own CLI default
        must stay reachable, and overriding it silently would be its own defect.
        """
        if mode is None:
            return []
        if mode not in {m.id for m in self.permission_modes()}:
            known = ", ".join(m.id for m in self.permission_modes()) or "none"
            raise ValueError(
                f"{mode!r} is not a permission mode {self.name!r} accepts (known: {known})")
        return ["--permission-mode", mode]

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
    native_providers = frozenset({"anthropic"})
    media_model_field = "claude_media_model"
    auth_home_env = ("CLAUDE_CONFIG_DIR",)
    no_extra_usage_guidance = (
        "in Claude Settings → Usage, keep Usage credits disabled, ensure prepaid balance is zero, "
        "and turn auto-reload off"
    )

    def can_run(self, model: Model, env: dict[str, str]) -> bool:
        if super().can_run(model, env):
            return True
        # Claude Code honours ANTHROPIC_BASE_URL, so a provider interact knows the endpoint of
        # (ollama) is reachable too — when that provider is actually available here.
        return bool(overlay_for(f"{model.provider}/{model.id}", env)) and model.is_available()
    binary = "claude"
    session_media_kinds = frozenset({"image", "video"})
    can_resume = True

    def auth_command(self) -> list[str]:
        return [self.executable(), "auth", "status"]

    def media_help_text(self) -> str:
        """Installed parser vocabulary only; this never authenticates or starts a model turn."""
        completed = subprocess.run(
            [self.executable(), "--help"], capture_output=True, text=True, timeout=10, check=False
        )
        if completed.returncode:
            raise RuntimeError("Claude CLI help is unavailable")
        return completed.stdout

    def accepts_subscription_auth(self, stdout: str, stderr: str) -> bool:
        try:
            status = json.loads(stdout)
        except ValueError:
            return False
        return bool(
            isinstance(status, dict)
            and status.get("loggedIn") is True
            and status.get("authMethod") == "claude.ai"
        )

    def supports_session_media(self, media_kind: str) -> bool:
        return media_kind in self.session_media_kinds

    async def media_isolation_args(
        self, env: dict[str, str], *, cwd: Path, timeout: float
    ) -> tuple[str, ...]:
        return ()

    async def run_media_process(
        self,
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        stdin: bytes | None = None,
    ) -> list[AgentEvent]:
        started = time.monotonic()
        try:
            returncode, stdout_bytes, stderr_bytes = await run_isolated_process(
                argv, cwd=cwd, env=env, timeout=timeout, stdin=stdin
            )
        except TimeoutError as exc:
            raise _MediaProcessTimeout(
                f"{self.name} media session timed out after {timeout:g}s",
                timeout_phase="provider_media",
                elapsed_seconds=time.monotonic() - started,
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"{self.name} CLI could not start: {exc.strerror or exc}") from exc
        events = [
            event
            for line in stdout_bytes.decode(errors="replace").splitlines()
            if (event := self.parse(line))
        ]
        facts = _failure_event_facts(events)
        failure_kwargs = {
            "events": facts,
            "stderr_bytes": len(stderr_bytes),
            "stderr_sha256": hashlib.sha256(stderr_bytes).hexdigest(),
            "elapsed_seconds": time.monotonic() - started,
        }
        if returncode:
            raise _MediaProcessFailure(
                f"{self.name} media session exited {returncode}",
                exit_code=returncode,
                **failure_kwargs,
            )
        errors = [event for event in events if event.kind in ("error", "rate_limit")]
        if errors:
            category = "subscription quota or rate limit" if errors[-1].kind == "rate_limit" else "provider reported failure"
            raise _MediaProcessFailure(f"{self.name} media session failed: {category}", **failure_kwargs)
        if not any(event.kind == "done" for event in events):
            raise _MediaProcessFailure(
                f"{self.name} media session exited without a final result", **failure_kwargs
            )
        if not any(
            (event.kind == "text" or event.final_text) and event.text.strip()
            for event in events
        ):
            raise _MediaProcessFailure(
                f"{self.name} media session returned no final message", **failure_kwargs
            )
        return events

    async def media_cli_version(
        self, env: dict[str, str], *, cwd: Path, timeout: float
    ) -> str:
        try:
            returncode, stdout, _ = await run_isolated_process(
                [self.executable(), "--version"], cwd=cwd, env=env, timeout=timeout
            )
        except (OSError, TimeoutError):
            return "unavailable"
        line = stdout.decode(errors="replace").splitlines()[0].strip() if stdout else ""
        if returncode or re.fullmatch(r"[A-Za-z0-9 ._+()/-]{1,120}", line) is None:
            return "unavailable"
        return line

    def media_result(self, events: list[AgentEvent]) -> _MediaResult:
        terminal = next(event for event in reversed(events) if event.kind == "done")
        text = terminal.text if terminal.final_text else next(
            event.text for event in reversed(events)
            if event.kind == "text" and event.text.strip()
        )
        return _MediaResult(
            text=text,
            input_tokens=terminal.input_tokens or 0,
            output_tokens=terminal.output_tokens or 0,
            reported_cost_usd=terminal.cost_usd,
        )

    def media_command(
        self,
        *,
        cwd: Path,
        model: str | None,
        media_paths: list[Path],
        schema_path: Path | None,
        schema_json: str | None,
        mcp_config: Path,
        settings_path: Path,
        isolation_args: tuple[str, ...] = (),
    ) -> list[str]:
        argv = [
            self.executable(), "-p",
            "--output-format", "stream-json", "--verbose",
            "--safe-mode", "--no-session-persistence",
            "--permission-mode", "dontAsk",
            "--mcp-config", str(mcp_config), "--strict-mcp-config",
            "--settings", str(settings_path),
        ]
        if media_paths:
            if any(any(char in str(path) for char in "*?[](){},") for path in media_paths):
                raise ValueError("Claude media staging path contains permission-rule metacharacters")
            rules = ",".join(f"Read({path})" for path in media_paths)
            argv += ["--tools", "Read", "--allowedTools", rules]
        else:
            argv += ["--tools", ""]
        if model:
            argv += ["--model", model]
        if schema_json:
            argv += ["--json-schema", schema_json]
        return argv

    #: Read off `claude --help` on the INSTALLED binary (2.1.233), not from memory of the docs —
    #: which would have produced "default" and missed auto/manual/dontAsk entirely.
    _MODES: ClassVar[tuple[PermissionMode, ...]] = (
        PermissionMode("plan", "Plan only",
                       "works out an approach and touches nothing"),
        PermissionMode("manual", "Ask every time",
                       "you approve each action before it happens"),
        PermissionMode("auto", "Ask when it matters",
                       "handles the routine, asks about the rest"),
        PermissionMode("acceptEdits", "May edit files",
                       "file changes go through, other actions still ask"),
        PermissionMode("dontAsk", "Stop asking",
                       "no prompts; declines what it is not allowed to do"),
        PermissionMode("bypassPermissions", "No restrictions",
                       "acts without asking, including outside the workspace",
                       unrestricted=True),
    )

    def permission_modes(self) -> list[PermissionMode]:
        return list(self._MODES)

    def command(self, task: str, *, cwd: str, model: str | None, mcp_config: str | None,
                run_id: str, agent: str | None = None,
                permission_mode: str | None = None,
                allowed_tools: list[str] | None = None) -> list[str]:
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
        # A TOOLSET, expanded. Absent means unrestricted — an allow-list nobody asked for would
        # silently take tools away from every agent that never mentioned one.
        if allowed_tools:
            argv += ["--allowedTools", ",".join(allowed_tools)]
        argv += self._permission_flag(permission_mode)
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
            texts, thinking, tool, tool_input, tool_id = [], [], None, "", ""
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
                    tool_id = str(block.get("id") or "")
            if tool:
                return AgentEvent(kind="tool", tool=tool, tool_input=tool_input, tool_id=tool_id,
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
                                      tool_id=str(block.get("tool_use_id") or ""),
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
            structured = raw.get("structured_output")
            has_final = structured is not None or bool(raw.get("result"))
            detail = json.dumps(structured) if structured is not None else str(
                raw.get("result") or raw.get("stop_reason") or raw.get("subtype") or ""
            )
            return AgentEvent(
                kind="error" if failed else "done",
                session_id=sid, raw_type=kind,
                text=detail,
                cost_usd=raw.get("total_cost_usd"),
                input_tokens=_prompt_tokens(usage),
                output_tokens=usage.get("output_tokens"),
                final_text=has_final,
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

    The general agent adapter remains unverified.
    """

    name = "codex"
    native_providers = frozenset({"openai", "chatgpt"})
    binary = "codex"
    verified = False
    caveat = "unverified: the general agent adapter has not been exercised end-to-end"

    def app_server_command(self) -> list[str]:
        """The installed local-session protocol entry point, resolved before spawning."""
        return [self.executable(), "app-server", "--listen", "stdio://"]

    def auth_command(self) -> list[str]:
        return [self.executable(), "login", "status"]

    def accepts_subscription_auth(self, stdout: str, stderr: str) -> bool:
        status = f"{stdout}\n{stderr}".strip().lower()
        return "logged in using chatgpt" in status and "api key" not in status

    def command(self, task: str, *, cwd: str, model: str | None, mcp_config: str | None,
                run_id: str, agent: str | None = None,
                permission_mode: str | None = None,
                allowed_tools: list[str] | None = None) -> list[str]:
        # No permission_modes() here: Codex has sandbox and approval flags, but this adapter's
        # own `verified = False` says these flags were never exercised against a real binary, and
        # a guessed autonomy setting is the last thing to ship on an unverified adapter.
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
        kind = str(raw.get("type", ""))
        if kind == "thread.started":
            return AgentEvent(kind="started", session_id=raw.get("thread_id"), raw_type=kind)
        if kind in ("turn.failed", "error"):
            error = raw.get("error") or {}
            text = error.get("message", "") if isinstance(error, dict) else str(error)
            return AgentEvent(kind="error", raw_type=kind, text=_clip(text or line))
        if kind == "item.completed":
            item = raw.get("item") or {}
            item_type = item.get("type") if isinstance(item, dict) else None
            if item_type == "agent_message":
                return AgentEvent(kind="text", raw_type=kind, text=str(item.get("text") or ""))
            if item_type == "command_execution":
                failed = item.get("status") == "failed" or bool(item.get("exit_code"))
                return AgentEvent(
                    kind="error" if failed else "tool_result",
                    raw_type=kind,
                    text=_clip(str(item.get("aggregated_output") or item.get("status") or "")),
                )
        if kind == "turn.completed":
            usage = raw.get("usage") or {}
            return AgentEvent(
                kind="done",
                raw_type=kind,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
            )
        return AgentEvent(kind="other", raw_type=kind, text=_clip(line, 200))


class _MediaSessionProvider(Protocol):
    name: str
    binary: str
    native_providers: frozenset[str]
    media_model_field: str
    no_extra_usage_guidance: str

    def available(self) -> bool: ...
    def executable(self) -> str: ...
    def model_id_for(self, model: Model) -> str: ...
    def can_run(self, model: Model, env: dict[str, str]) -> bool: ...
    def supports_session_media(self, media_kind: str) -> bool: ...
    def subscription_env(
        self, base: dict[str, str] | None = None, *, temp_dir: Path | None = None
    ) -> dict[str, str]: ...
    async def subscription_authenticated(
        self, env: dict[str, str], *, timeout: float = 10
    ) -> bool: ...
    async def media_isolation_args(
        self, env: dict[str, str], *, cwd: Path, timeout: float
    ) -> tuple[str, ...]: ...
    async def media_cli_version(
        self, env: dict[str, str], *, cwd: Path, timeout: float
    ) -> str: ...
    def media_command(
        self, *, cwd: Path, model: str | None, media_paths: list[Path],
        schema_path: Path | None, schema_json: str | None, mcp_config: Path,
        settings_path: Path, isolation_args: tuple[str, ...] = (),
    ) -> list[str]: ...
    async def run_media_process(
        self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float,
        stdin: bytes | None = None,
    ) -> list[AgentEvent]: ...
    def media_result(self, events: list[AgentEvent]) -> _MediaResult: ...


_claude = ClaudeCodeProvider()
PROVIDERS: dict[str, AgentProvider] = {p.name: p for p in (_claude, CodexProvider())}
MEDIA_PROVIDERS: dict[str, _MediaSessionProvider] = {_claude.name: _claude}


def provider_for(name: str) -> AgentProvider:
    try:
        return PROVIDERS[name]
    except KeyError:
        known = ", ".join(sorted(PROVIDERS))
        raise ValueError(f"unknown agent provider {name!r} — known providers: {known}") from None


def available_providers() -> list[AgentProvider]:
    """Only the CLIs actually installed — the set a spawn request can legitimately name."""
    return [p for p in PROVIDERS.values() if p.available()]
