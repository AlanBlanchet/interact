"""How agents run here: profiles, toolsets, paradigms, and which providers are switched on.

    ~/.interact/agents.json
    {
      "profiles":  {"eyes": "cap.vlm and gui.screenspot > 0.85 and price.in < 10"},
      "agents":    {"visual-critic": "@eyes", "ux-critic": "@eyes"},
      "toolsets":  {"vision": ["screenshot", "review_ui"], "browse": ["navigate", "@vision"]},
      "agent_tools": {"visual-critic": ["@browse"]},
      "paradigms": {"tester": [{"paradigm": "coding", "as": "system_prompt"}]},
      "providers": {"claude": true, "codex": false}
    }

Four asks, one shape. A PROFILE is a model rule written once, worn by many agents; a TOOLSET is a
set of tools named once instead of spelling `mcp__interact__…` at every call site; a PARADIGM
assignment is instruction content written once and PROJECTED per agent, choosing whether that
agent carries it always (`system_prompt`) or loads it on demand (`skill`) — same content,
different altitude per agent; a PROVIDER switch says whether interact drives agents through that
vendor at all. Each is a NAME standing for something you'd otherwise repeat, so they share one
file and one grammar instead of four conventions to remember.

Everything is validated when the file is READ — unknown profile, toolset cycle, unknown
projection kind — because the alternative is discovering it at 3am when that agent spawns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from interact.config import UserConfig

#: The two altitudes a paradigm can be projected at for one agent. Closed on purpose: a third
#: spelling ("prompt", "sticky-note") is a typo, silent until spawn.
ParadigmProjection = Literal["skill", "system_prompt"]
_PROJECTIONS: tuple[ParadigmProjection, ...] = ("skill", "system_prompt")


@dataclass(frozen=True)
class ParadigmAssignment:
    """One paradigm, worn by one agent, at one altitude."""

    paradigm: str
    projection: ParadigmProjection


class PolicyError(ValueError):
    """A policy file that cannot be honoured. Raised at LOAD, naming what to fix."""


#: How vendor CLIs address an MCP server's tools. interact's own tools are the ones named here,
#: so the prefix is added rather than typed forty times.
TOOL_PREFIX = "mcp__interact__"


def policy_path() -> Path:
    """Where the policy lives: beside `config.env`, the one store every front end shares.

    NOT under the debug dir: a box that relocates its dumps (`INTERACT_DEBUG_DIR`) would drag the
    policy along — the CLI once looked for `<repo>/out/agents.json` while the panel wrote
    `~/.interact/agents.json`: one fact in two files, and a choice that never bit. The extension
    computes the same path on its own (`agentModels.ts`); `tests/test_paths.py` holds the two together.
    """
    return UserConfig.PATH.parent / "agents.json"


@dataclass
class Policy:
    profiles: dict[str, str] = field(default_factory=dict)
    agents: dict[str, str] = field(default_factory=dict)
    toolsets: dict[str, list[str]] = field(default_factory=dict)
    agent_tools: dict[str, list[str]] = field(default_factory=dict)
    paradigms: dict[str, list[ParadigmAssignment]] = field(default_factory=dict)
    providers: dict[str, bool] = field(default_factory=dict)
    defaults: dict[str, str] = field(default_factory=dict)
    reasoning: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "Policy":
        """Read the policy, or an empty one. A missing file is not an error — most people never
        write one, and interact's defaults must work with nothing configured at all."""
        path = Path(path) if path is not None else policy_path()
        try:
            raw = json.loads(path.read_text())
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as err:
            raise PolicyError(f"{path} is not readable policy: {err}") from err
        if not isinstance(raw, dict):
            raise PolicyError(f"{path} must hold an object")
        policy = cls(
            profiles=dict(raw.get("profiles") or {}),
            agents=dict(raw.get("agents") or {}),
            toolsets={k: list(v) for k, v in (raw.get("toolsets") or {}).items()},
            agent_tools={k: list(v) for k, v in (raw.get("agent_tools") or {}).items()},
            paradigms=_parse_paradigms(raw.get("paradigms") or {}, path),
            providers=dict(raw.get("providers") or {}),
            defaults=dict(raw.get("defaults") or {}),
            reasoning=dict(raw.get("reasoning") or {}),
        )
        policy.validate()
        return policy

    def validate(self) -> None:
        """Everything that can be wrong, found now rather than at spawn."""
        if self.defaults.get("model"):
            self.rule(self.defaults["model"], wearer="default")
        efforts = {"minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
        for agent, effort in {"default": self.defaults.get("reasoning", "medium"),
                              **self.reasoning}.items():
            if effort not in efforts:
                raise PolicyError(f"agent {agent!r} has unsupported reasoning {effort!r}")
        for agent, rule in self.agents.items():
            self.rule(rule, wearer=agent)  # raises on a profile that does not exist
        for name in self.toolsets:
            self.expand_toolset(name)  # raises on a cycle or an unknown reference
        # The projection kind is validated by `_parse_paradigms` at load, ahead of here — content
        # existence is a separate, offline-unavailable check (`agents.paradigms.plan_projections`).

    @staticmethod
    def _looks_like_profile(rule: str) -> bool:
        """`@name` references a profile — the same sigil a toolset uses to reference another.

        A sigil, not a heuristic: `ghost-profile` and `claude-sonnet-5` are the same SHAPE, so
        guessing would either mistake a typo'd profile for a model id (discovering it at 3am) or
        refuse a legitimate id. One character removes the whole question.
        """
        return rule.startswith("@")

    def criterion_for(self, agent: str) -> str | None:
        """What model rule this agent runs under: its profile's criterion, its own inline
        criterion, or a plain model id — whichever the file says. None when unmentioned."""
        rule = self.agents.get(agent, self.defaults.get("model"))
        return None if rule is None else self.rule(rule, wearer=agent)

    def reasoning_for(self, agent: str) -> str:
        """Explicit role effort, independent of the parent session's effort."""
        return self.reasoning.get(agent, self.defaults.get("reasoning", "medium"))

    def rule(self, text: str, *, wearer: str | None = None) -> str:
        """`@name` → that profile's criterion; anything else is returned as written.

        A profile is a NAME for a model rule, so it is honoured wherever a model may be named —
        the `agents` map here, `--model @eyes` on the CLI, the panel's picker. An unknown one is
        refused naming the typo and what exists; `wearer` is the agent wearing it, when there is one.
        """
        if not self._looks_like_profile(text):
            return text
        if text[1:] in self.profiles:
            return self.profiles[text[1:]]
        known = ", ".join(sorted(self.profiles)) or "none defined"
        if wearer:
            raise PolicyError(f"agent {wearer!r} wears profile {text!r}, which does not exist (have: {known})")
        raise PolicyError(f"profile {text!r} does not exist (have: {known})")

    def expand_toolset(self, name: str, _seen: tuple[str, ...] = ()) -> list[str]:
        """A toolset's tools, fully prefixed, with `@other-set` references expanded in place."""
        if name in _seen:
            raise PolicyError(f"toolset cycle: {' -> '.join([*_seen, name])}")
        members = self.toolsets.get(name)
        if members is None:
            raise PolicyError(f"toolset {name!r} does not exist")
        out: list[str] = []
        for member in members:
            out.extend(self._expand_member(member, (*_seen, name)))
        return _dedupe(out)

    def _expand_member(self, member: str, seen: tuple[str, ...]) -> list[str]:
        if member.startswith("@"):
            return self.expand_toolset(member[1:], seen)
        # Already addressed in full (another server's tool, or somebody being explicit) — left as
        # written: guessing a prefix for somebody else's server is worse.
        if member.startswith("mcp__") or "__" in member:
            return [member]
        return [f"{TOOL_PREFIX}{member}"]

    def tools_for(self, agent: str) -> list[str]:
        """The tools this agent may use, or [] when the policy does not restrict it."""
        members = self.agent_tools.get(agent)
        if not members:
            return []
        out: list[str] = []
        for member in members:
            out.extend(self._expand_member(member, ()))
        return _dedupe(out)

    def provider_active(self, provider: str) -> bool:
        """Whether interact drives agents through this vendor.

        Unmentioned means ON: a provider whose CLI is installed and whose key is set is one the
        person meant to use, and a policy file nobody wrote must never silently disable anything.
        """
        return bool(self.providers.get(provider, True))

    def set_provider_active(self, provider: str, active: bool, path: Path | None = None) -> None:
        """Flip a provider on or off and write it back, so the CLI and the panel's toggle are
        reading and writing the same one fact."""
        path = Path(path) if path is not None else policy_path()
        try:
            raw = json.loads(path.read_text())
        except FileNotFoundError:
            raw = {}
        except (OSError, ValueError) as err:
            # The file holds profiles and toolsets somebody typed. One missing comma must not let
            # a provider switch flatten it: refuse, name the file, write nothing.
            raise PolicyError(f"{path} is not readable policy ({err}); fix it — nothing was written") from err
        if not isinstance(raw, dict):
            raise PolicyError(f"{path} must hold an object — nothing was written")
        raw.setdefault("providers", {})[provider] = bool(active)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(raw, indent=2) + "\n")
        self.providers[provider] = bool(active)

    def assign_paradigm(
        self, agent: str, paradigm: str, projection: ParadigmProjection, path: Path | None = None,
    ) -> None:
        """Give `agent` a paradigm at one altitude — SAME read-modify-write shape as
        `set_provider_active`, so a choice made anywhere reads back identically everywhere.

        Re-assigning a paradigm already on this agent REPLACES its projection in place rather
        than appending a second, contradictory entry; a new paradigm is appended, order kept —
        assignment order is the order a system prompt's fragments are concatenated in.
        """
        if projection not in _PROJECTIONS:
            raise PolicyError(
                f"{projection!r} is not a paradigm projection — write one of {_PROJECTIONS}"
            )
        path = Path(path) if path is not None else policy_path()
        try:
            raw = json.loads(path.read_text())
        except FileNotFoundError:
            raw = {}
        except (OSError, ValueError) as err:
            raise PolicyError(f"{path} is not readable policy ({err}); fix it — nothing was written") from err
        if not isinstance(raw, dict):
            raise PolicyError(f"{path} must hold an object — nothing was written")
        entries = raw.setdefault("paradigms", {}).setdefault(agent, [])
        entry = {"paradigm": paradigm, "as": projection}
        for existing in entries:
            if existing.get("paradigm") == paradigm:
                existing["as"] = projection
                break
        else:
            entries.append(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(raw, indent=2) + "\n")
        self.paradigms[agent] = [
            ParadigmAssignment(paradigm=e["paradigm"], projection=e["as"]) for e in entries
        ]


def _parse_paradigms(
    raw: dict[str, list[dict[str, str]]], path: Path,
) -> dict[str, list[ParadigmAssignment]]:
    """Turn the raw `paradigms` object into typed assignments, refusing an unknown projection
    kind HERE — at load — rather than at the spawn that silently gets no instructions at all."""
    out: dict[str, list[ParadigmAssignment]] = {}
    for agent, entries in raw.items():
        assignments = []
        for entry in entries:
            projection = entry.get("as")
            if projection not in _PROJECTIONS:
                raise PolicyError(
                    f"{path}: {agent!r} is assigned paradigm {entry.get('paradigm')!r} "
                    f"as {projection!r} — write one of {_PROJECTIONS}"
                )
            assignments.append(ParadigmAssignment(paradigm=entry["paradigm"], projection=projection))
        out[agent] = assignments
    return out


def _dedupe(names: list[str]) -> list[str]:
    """Order preserved — the file's order is the reader's order, and a set would scramble it."""
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out
