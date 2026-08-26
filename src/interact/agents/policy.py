"""How agents run here: profiles, toolsets, and which providers are switched on.

    ~/.interact/agents.json
    {
      "profiles":  {"eyes": "cap.vlm and gui.screenspot > 0.85 and price.in < 10"},
      "agents":    {"visual-critic": "@eyes", "ux-critic": "@eyes"},
      "toolsets":  {"vision": ["screenshot", "review_ui"], "browse": ["navigate", "@vision"]},
      "agent_tools": {"visual-critic": ["@browse"]},
      "providers": {"claude": true, "codex": false}
    }

Three asks, one shape. A PROFILE is a model rule written once and worn by many agents; a TOOLSET
is a set of tools named once instead of spelling `mcp__interact__…` at every call site; a
PROVIDER switch says whether interact drives agents through that vendor at all. Each is a NAME
standing for something you would otherwise repeat, so they share one file and one grammar rather
than three conventions to remember.

Everything is validated when the file is READ — an unknown profile, a toolset cycle — because the
alternative is discovering it at 3am when that one agent happens to spawn.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from interact.config import UserConfig


class PolicyError(ValueError):
    """A policy file that cannot be honoured. Raised at LOAD, naming what to fix."""


#: How the vendor CLIs address an MCP server's tools. interact's own tools are the ones anybody
#: is naming here, so the prefix is added rather than typed forty times.
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
    providers: dict[str, bool] = field(default_factory=dict)

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
            providers=dict(raw.get("providers") or {}),
        )
        policy.validate()
        return policy

    def validate(self) -> None:
        """Everything that can be wrong, found now rather than at spawn."""
        for agent, rule in self.agents.items():
            self.rule(rule, wearer=agent)  # raises on a profile that does not exist
        for name in self.toolsets:
            self.expand_toolset(name)  # raises on a cycle or an unknown reference

    @staticmethod
    def _looks_like_profile(rule: str) -> bool:
        """`@name` references a profile — the same sigil a toolset uses to reference another.

        A sigil rather than a heuristic: `ghost-profile` and `claude-sonnet-5` are the same
        SHAPE, so guessing would either mistake a typo'd profile for a model id (and discover it
        at 3am) or refuse a legitimate id. One character removes the whole question.
        """
        return rule.startswith("@")

    def criterion_for(self, agent: str) -> str | None:
        """What model rule this agent runs under: its profile's criterion, its own inline
        criterion, or a plain model id — whichever the file says. None when unmentioned."""
        rule = self.agents.get(agent)
        return None if rule is None else self.rule(rule, wearer=agent)

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
        # Already addressed in full (another server's tool, or somebody being explicit) — left
        # exactly as written, because guessing a prefix for somebody else's server is worse.
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


def _dedupe(names: list[str]) -> list[str]:
    """Order preserved — the file's order is the reader's order, and a set would scramble it."""
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out
