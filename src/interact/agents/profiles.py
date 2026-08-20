"""Per-agent model routing — deciding what an agent runs on BEFORE it is called.

Alan: "why couldn't we mix? Can't we control the env that an agent (or sub-agent) spawns in by
activating / deactivating what the agent can do before called? Even for other providers?"

Yes, and his framing is the safe one. The tempting shape is an ``env`` dict on the spawn tool:
four lines, total flexibility. It is also a model-reachable path to ``LD_PRELOAD``, ``PATH`` and
key exfiltration — the same escalation shape this codebase already refuses once, where a model may
not select an unrestricted permission mode for the agent it spawns. A capability a model can grant
itself is not a capability the operator controls.

So the operator names a PROFILE in their own config, and a profile resolves to a fixed,
allow-listed set of variables. There is no input to this module that produces a key outside
``ALLOWED_ENV`` — not a crafted model id, not a newline, not a profile value written to look like
an assignment. Flexibility lives in WHICH profiles exist; the blast radius does not move.

    # ~/.interact/config.env
    INTERACT_PROFILE_CHEAP=ollama/deepseek-v4-flash
    INTERACT_PROFILE_SHARP=anthropic/claude-opus-4-6

Routing works for any provider whose CLI reads a base URL from the environment. Ollama serves an
Anthropic-compatible ``/v1/messages``, which is why an unmodified Claude Code — and every agent
definition file you already have — runs against it untouched.
"""

from __future__ import annotations

import re

PROFILE_PREFIX = "INTERACT_PROFILE_"

#: The ONLY variables a profile may set. Deliberately tiny and deliberately boring: every entry
#: selects a model or an endpoint, and none of them can load code, change what binary runs, or
#: redirect an import. Adding to this list is a security decision, not a convenience one.
ALLOWED_ENV = frozenset({
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_MODEL",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
})

#: Where each provider's endpoint is read FROM — the operator's own environment, never the caller's
#: model string. A model id says WHICH model; it never says where to send the credentials.
_BASE_FROM: dict[str, tuple[str, ...]] = {
    "ollama": ("OLLAMA_API_BASE", "OLLAMA_HOST"),
}

#: A model id we will act on: provider, slash, then a plain name. Anything else routes nowhere.
_MODEL = re.compile(r"^([a-z0-9_-]{1,32})/([A-Za-z0-9._:-]{1,64})$")


def profiles_from(env: dict[str, str]) -> dict[str, str]:
    """The profiles the OPERATOR has defined, lower-cased by name."""
    return {
        k[len(PROFILE_PREFIX):].lower(): v.strip()
        for k, v in env.items()
        if k.startswith(PROFILE_PREFIX) and v.strip()
    }


def _base_url(provider: str, env: dict[str, str]) -> str | None:
    for key in _BASE_FROM.get(provider, ()):
        raw = (env.get(key) or "").strip()
        if not raw:
            continue
        # Ollama's own convention is scheme-less ("box.lan:11434"), so add the scheme it means.
        return raw if "://" in raw else f"http://{raw}"
    return "http://localhost:11434" if provider == "ollama" else None


def overlay_for(model: str, env: dict[str, str]) -> dict[str, str]:
    """The environment overlay that points a vendor CLI at ``model``.

    Returns an EMPTY overlay for anything it does not positively recognise — an unprefixed model
    (the vendor's own default, nothing to redirect), a malformed id, or a provider with no known
    endpoint. Refusing to act is always safe here; guessing an endpoint would send the operator's
    credentials somewhere nobody chose.
    """
    match = _MODEL.match((model or "").strip())
    if not match:
        return {}
    provider, name = match.group(1), match.group(2)
    base = _base_url(provider, env)
    if not base:
        return {}
    out = {"ANTHROPIC_BASE_URL": base, "ANTHROPIC_MODEL": name}
    # Claude Code warns `unrecognized_model` and assumes a 200k window for anything it does not
    # ship; saying so explicitly keeps a local model from being handed a context it cannot hold.
    window = (env.get("INTERACT_PROFILE_CONTEXT") or "").strip()
    if window.isdigit():
        out["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = window
    assert set(out) <= ALLOWED_ENV  # structural, not defensive: the set is fixed above
    return out
