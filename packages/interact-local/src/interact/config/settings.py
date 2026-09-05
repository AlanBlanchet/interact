import functools
import glob
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode

from interact.agents.providers import MEDIA_PROVIDERS
from interact.data import PackageData
from interact.models import CircuitBreaker, Model, ModelChain, ModelRole

DEFAULT_LIMIT = 50
LOG_MAXLEN = 1000


def _safe_dir_name(name: str) -> str:
    """A filesystem-safe directory name (collapse anything outside [A-Za-z0-9._-] to '_')."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_-. ") or "default"


def _session_custom_title(session_id: str, home: str) -> str | None:
    """The user-set title of a Claude Code session, read from its transcript under
    ``~/.claude/projects`` — the same store ``scan_client_errors.py`` reads. The session id is
    unique, so a glob finds the file regardless of how Claude slugs the project dir. Only the small
    ``custom-title`` lines are parsed (cheap string pre-filter), and the LAST one wins (renames)."""
    matches = glob.glob(str(Path(home) / ".claude" / "projects" / "*" / f"{session_id}.jsonl"))
    if not matches:
        return None
    custom = None
    try:
        with open(matches[0], encoding="utf-8") as f:
            for line in f:
                if '"custom-title"' in line:
                    try:
                        custom = json.loads(line).get("customTitle") or custom
                    except ValueError:
                        pass
    except OSError:
        return None
    return custom


@functools.lru_cache(maxsize=16)
def _resolve_session_name(session_id: str, project_dir: str, cwd: str, home: str) -> str:
    """Resolve the calling session's log-folder name (pure function of its inputs, so lru_cache is
    safe + keyed by env): the Claude session's custom-title, else the project/cwd dir basename, else
    'default'. Cached because the title means re-reading a (large) transcript."""
    title = _session_custom_title(session_id, home) if session_id else None
    base = Path(project_dir or cwd).name if (project_dir or cwd) else ""
    return _safe_dir_name(title or base or "default")


def caller_session_name() -> str:
    """The name of the Claude Code session driving interact, for separating logs per session: its
    user-set custom-title (e.g. 'Aino') when resolvable, else the CLAUDE_PROJECT_DIR / cwd basename,
    else 'default'. The dir basename and the session title can differ — the title is the authoritative
    one the user sees (and set), so it wins."""
    return _resolve_session_name(
        os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
        os.environ.get("CLAUDE_PROJECT_DIR", ""),
        os.getcwd(),
        str(Path.home()),
    )

# The "sovereign" GLM-4.5V models the low/medium quality tiers prefer (MIT, open-weight,
# self-hostable) — a strong open VLM, cheap/private, the right default when peak frontier accuracy
# isn't needed. Tried in order; the FIRST whose API key is present wins, so EITHER a z.ai key
# (ZAI_API_KEY → first-party `zai/`) or a Novita key (NOVITA_API_KEY → reseller `novita/`) lights up
# GLM with zero config. An explicit INTERACT_TIER_SOVEREIGN_MODEL overrides the whole list (e.g. a
# self-hosted endpoint id). z.ai is preferred — it's GLM's first-party API.
_SOVEREIGN_MODELS = ("zai/glm-4.5v", "novita/zai-org/glm-4.5v")
_DEFAULT_SOVEREIGN_MODEL = _SOVEREIGN_MODELS[0]  # preferred default (also a back-compat alias)

# Quality tiers for the UI tools (review_ui/verify_ui quality=...): the agent picks by STAKES, not
# by model name — low = quick glance, critical = final pre-ship sign-off. interact maps the tier to
# a model (sovereign for low/medium, best-available frontier for high/critical) + extra rigor.
QUALITY_TIERS = ("low", "medium", "high", "critical")


def _default_media_provider_order() -> tuple[str, ...]:
    """Registry order is the one default; adding a real provider makes it configurable at once."""
    return tuple(MEDIA_PROVIDERS)


@dataclass(frozen=True)
class SkippedModel:
    """A stronger model the walk passed over, and why it could not be used."""

    model: str
    reason: str


@dataclass(frozen=True)
class ModelWalk:
    """What a role resolved to, and what it stepped over getting there."""

    role: str
    chosen: str
    pinned: bool
    skipped: list[SkippedModel]


class Config(BaseSettings):
    model_config = {"env_prefix": "INTERACT_"}

    image_model: str = ""
    video_model: str = ""
    component_model: str = ""
    audio_model: str = ""
    # Generic media execution. Backend selects the transport; billing decides whether interact may
    # call a metered API. Vendor CLIs can consume account credits after plan allowance, so session
    # execution additionally requires an explicit operator attestation that those credits are off.
    media_backend: Literal["auto", "session", "api"] = "auto"
    media_billing: Literal["session_only", "api_allowed"] = "session_only"
    media_session_no_extra_usage_confirmed_for: Annotated[tuple[str, ...], NoDecode] = ()
    media_provider_order: Annotated[tuple[str, ...], NoDecode] = Field(
        default_factory=_default_media_provider_order
    )
    media_timeout: int = 120
    media_max_items: int = 16
    media_max_total_bytes: int = 50 * 1024 * 1024
    media_max_context_chars: int = 32 * 1024
    prompt_endpoint: str = ""
    prompt_account: str = ""
    prompt_token: str = ""
    prompt_cache: Path = Path.home() / ".interact" / "prompts.sqlite3"
    claude_media_model: str = ""
    # Fallback model chains (comma-separated litellm ids) tried, in order, when the primary
    # model errors. Empty → the bundled per-role recommendations are used as the defaults.
    image_fallbacks: str = ""
    component_fallbacks: str = ""
    video_fallbacks: str = ""
    audio_fallbacks: str = ""
    # The model the low/medium quality tiers prefer (see QUALITY_TIERS). Empty → GLM-4.5V default
    # (_DEFAULT_SOVEREIGN_MODEL). Override with INTERACT_TIER_SOVEREIGN_MODEL (e.g. a local id).
    tier_sovereign_model: str = ""
    headless: bool = True
    slow_mo: int = 0
    browser_type: Literal["chromium", "firefox", "webkit"] = "chromium"
    viewport_width: int = 1280
    viewport_height: int = 720
    # When set, browser sessions persist their profile (cookies, localStorage, login) on disk under
    # <browser_profile_dir>/<session> instead of the default ephemeral context that starts logged
    # out every launch. Lets an authenticated flow run through the reliable DOM-ref path (log in
    # once, stay logged in across restarts) rather than the flaky desktop-window VLM path (#43).
    # Each session gets its own subdir — Playwright locks a user-data-dir to one running context.
    # Override with INTERACT_BROWSER_PROFILE_DIR.
    browser_profile_dir: Path | None = None
    screenshot_dump_dir: Path | None = None  # explicit per-run override of the dump base
    # Base dir for interact's local output: the usage log (debug_dir/usage.jsonl) and per-session debug
    # dumps (debug_dir/sessions/…). Default ~/.interact/out — kept in an `out/` folder so the root stays clean
    # (just config.env + out/) instead of being scattered with timestamped dump dirs. Override with
    # INTERACT_DEBUG_DIR (e.g. a project's out/ when working locally). screenshot_dump_dir wins if set.
    debug_dir: Path = Path.home() / ".interact" / "out"
    video_fps: int = 5
    video_duration: float = 3.0
    # Cost cap for video understanding: a recording is sampled down to at most this many frames
    # (evenly spaced) before going to the VLM, so spend is bounded by frame count, not clip
    # length — enough frames to follow what happened (UI flow, gameplay), without paying per second.
    video_max_frames: int = 12
    max_tokens: int | None = None
    wait_timeout: int = 10000
    # Auto-close a browser session whose browser has sat idle (no tool call) this many seconds,
    # freeing its Chromium + driver; it re-opens lazily on next use (a non-default session starts
    # fresh — cookies/login are not preserved across the close). 0 disables. Override with
    # INTERACT_SESSION_IDLE_TTL.
    session_idle_ttl: int = 900
    # Same idea for the nested sandbox — but its Xephyr is a VISIBLE window on the user's desktop,
    # which annoys per idle-minute in a way an invisible headless browser doesn't, so it defaults
    # shorter. An abandoned sandbox auto-closes (the next launch_app respawns one); a live recording
    # blocks reaping. 0 disables. Override with INTERACT_SANDBOX_IDLE_TTL.
    sandbox_idle_ttl: int = 300
    # Refresh the live model catalog (OpenRouter) and benchmark scores (Artificial Analysis) in
    # the background when the server starts, so the dashboard shows current prices and rankings
    # instead of whatever was cached. Set false to keep interact from reaching those APIs at all —
    # the panels then serve the last cache and say how old it is. Override with
    # INTERACT_REFRESH_LIVE_DATA.
    refresh_live_data: bool = True
    vlm_max_dim: int = 1280
    vlm_min_dim: int = 768
    detection_max_retries: int = 3  # judge-driven re-detection passes to recover missed elements
    # Desktop target: "local" drives the real session (uinput, system-wide);
    # "nested" runs an isolated Xephyr display (xdotool into it) — for tests / a VM-like
    # sandbox that never touches the user's real windows or cursor.
    desktop_target: Literal["local", "nested"] = "local"
    nested_display: int = 99
    nested_size: str = "1280x800"
    # When the target is "nested": run the X server visible (Xephyr, default — watch the
    # agent) or headless in the background (Xvfb — for CI / servers, no window).
    nested_headless: bool = False

    @field_validator(
        "debug_dir", "screenshot_dump_dir", "browser_profile_dir", "prompt_cache", mode="after"
    )
    @classmethod
    def _expand_user(cls, value: Path | None) -> Path | None:
        """Expand ``~`` once, here at the boundary where the value enters.

        These fields are free text everywhere they're set — the config TUI, the VS Code settings
        UI, a hand-edited ``config.env`` — and their descriptions advertise ``~/.interact/out``,
        so users type a tilde. Without this, ``INTERACT_DEBUG_DIR=~/.interact`` becomes a literal
        ``Path("~/.interact")`` and every write lands in a ``./~/.interact`` dir relative to
        wherever the server happened to start.
        """
        if value is None:
            return value
        try:
            return value.expanduser()
        except RuntimeError as exc:  # "~nosuchuser/out" — pydantic only wraps ValueError
            raise ValueError(f"cannot expand '~' in {value}: {exc}") from exc

    @field_validator(
        "media_provider_order", "media_session_no_extra_usage_confirmed_for", mode="before"
    )
    @classmethod
    def _parse_media_provider_list(cls, value, info) -> tuple[str, ...]:
        if isinstance(value, str):
            providers = tuple(part.strip() for part in value.split(",") if part.strip())
        elif isinstance(value, (tuple, list)):
            providers = tuple(str(part).strip() for part in value if str(part).strip())
        else:
            raise ValueError("media provider order must be a comma-separated list")
        if not providers and info.field_name == "media_provider_order":
            raise ValueError("media provider order cannot be empty")
        if len(set(providers)) != len(providers):
            raise ValueError(f"{info.field_name} contains a duplicate")
        unknown = [name for name in providers if name not in MEDIA_PROVIDERS]
        if unknown:
            raise ValueError(f"unsupported media provider: {', '.join(unknown)}")
        return providers

    @field_validator(
        "media_timeout", "media_max_items", "media_max_total_bytes", "media_max_context_chars"
    )
    @classmethod
    def _positive_media_limit(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be greater than zero")
        return value

    @model_validator(mode="after")
    def _check_dim_bounds(self):
        if self.vlm_min_dim > self.vlm_max_dim:
            raise ValueError(
                f"vlm_min_dim ({self.vlm_min_dim}) must be <= vlm_max_dim ({self.vlm_max_dim})"
            )
        if self.media_backend == "api" and self.media_billing == "session_only":
            raise ValueError("media backend 'api' conflicts with session_only billing")
        return self

    @property
    def usage_log(self) -> Path:
        """The one global VLM-usage log, at ``<debug_dir>/usage.jsonl`` (relocates with debug_dir)."""
        return self.debug_dir / "usage.jsonl"

    def session_log_dir(self) -> Path:
        """Per-caller output root: ``<debug_dir>/sessions/<session>/<date>``. The dir is organised BY
        SESSION (not a flat 'logs' pile): ``<session>`` is the calling client's name — a Claude Code
        session's custom-title (e.g. 'Aino'), else the VS Code / project / cwd basename, else 'default'
        — and ``<date>`` is today. Every dump interact writes for a run lands here, dated."""
        return self.debug_dir / "sessions" / caller_session_name() / datetime.now().strftime("%Y-%m-%d")

    def media_workspace_root(self) -> Path:
        """User-owned root for temporary artifacts shared by every media transport."""
        return self.session_log_dir()

    def media_model_for(self, provider: str) -> str:
        """Configured model for one registered subscription CLI, or blank for its default."""
        try:
            field = MEDIA_PROVIDERS[provider].media_model_field
        except KeyError:
            raise ValueError(f"unknown media provider: {provider}") from None
        return str(getattr(self, field))

    def media_sessions_enabled(self) -> bool:
        return self.media_backend != "api"

    def media_api_enabled(self) -> bool:
        return self.media_backend != "session" and self.media_billing == "api_allowed"

    def require_media_session_confirmation(self, providers: tuple[str, ...]) -> None:
        """Fail closed for candidate providers lacking a provider-scoped operator confirmation."""
        confirmed = set(self.media_session_no_extra_usage_confirmed_for)
        missing = tuple(provider for provider in providers if provider not in confirmed)
        if not missing:
            return
        instructions = "; ".join(
            f"{provider}: {MEDIA_PROVIDERS[provider].no_extra_usage_guidance}"
            for provider in missing
        )
        raise RuntimeError(
            f"session media is blocked for unconfirmed provider(s) {', '.join(missing)}. "
            f"{instructions}; then list only those confirmed providers in "
            "media.noExtraUsageConfirmedFor. interact cannot inspect these account settings or "
            "eliminate the race if they change later"
        )

    def model_for(self, role: ModelRole) -> str:
        if role == "video":
            return self.video_model
        if role == "component":
            return self.component_model
        if role == "audio":
            return self.audio_model
        return self.image_model

    def resolve_model(
        self, role: ModelRole, override: str = "", breaker: CircuitBreaker | None = None
    ) -> str:
        """Single resolution site for a role's model id — the boundary where "which model"
        is decided once, so nothing downstream ever runs with an empty id (the bug behind the
        "[Vision not configured]" returns: the auto path left ``model_for`` empty and that ``""``
        flowed all the way into the VLM call). Precedence:

        1. an explicit per-call ``override`` (the agent's ``model=`` argument),
        2. else the configured pin, IF it can actually run (its key is present),
        3. else the first available model in the role's preference chain — strongest first,
           skipping circuit-broken ones,
        4. else the pin, or failing that the chain's top preference, so a missing key becomes a
           clear downstream auth error naming the model the person asked for, never an empty-id
           silent no-op.

        Step 2 used to return the pin unconditionally. The reasoning was that a bad pin should
        surface a clear auth error rather than be silently swapped — but honouring an unusable
        pin honours nothing: the error arrived from deep inside a vendor call, and no work got
        done. Falling through to a model that CAN run is strictly more useful, and it is not
        silent — ``interact doctor`` prints "⚠ key missing" beside the pin. It also matters
        because the VS Code extension used to bake catalog defaults into the environment, which
        made every user look "pinned" and disabled the walk entirely.

        Raises if the catalog is empty (no models.json and no litellm) — fail loud here, at the
        one resolution site, not by leaking a sentinel for deeper code to re-validate.
        """
        if override:
            return override
        configured = self.model_for(role)
        chain = self.chain_for(role)
        # Honoured unless we can PROVE it cannot run. `key_missing` is deliberately narrower
        # than `not is_available()`: the latter is also true for any id outside the catalog — a
        # self-hosted endpoint, a local runner — and overriding one of those would be auto-
        # selection quietly discarding a choice somebody made.
        if configured and not Model.from_litellm_id(configured).key_missing():
            return configured
        active = chain.active(breaker)
        if active is not None:
            return active.id
        if configured:
            return configured  # nothing can run: name what they asked for, not a substitute
        if chain.preferences:
            return chain.preferences[0].id
        raise RuntimeError(f"no model available for role {role!r}: empty model catalog")

    def explain_model(self, role: ModelRole) -> ModelWalk:
        """Which model this role picks, and what it passed over on the way.

        The chosen id alone cannot answer "are we using the best model we have" — that reads the
        same whether the walk found the strongest available or whether a stale default was
        returned without any walk at all, which is exactly what used to happen. The skipped list
        is the evidence, and it distinguishes a key somebody could ADD from a provider interact
        will not drive at all.
        """
        chain = self.chain_for(role)
        pinned = self.model_for(role)
        skipped: list[SkippedModel] = []
        for model in chain.preferences:
            if model.id == pinned or model.is_available():
                return ModelWalk(role=role, chosen=model.id, pinned=bool(pinned), skipped=skipped)
            keys = Model._provider_keys.get(model.provider)
            if keys:
                absent = [k for k in keys if not os.environ.get(k)]
                reason = "no " + ", ".join(absent)
            elif keys is not None:
                # Declares no API keys: subscription CLI media runs through the separate session
                # transport, not through this LiteLLM model-selection walk.
                reason = "subscription provider — available through media.backend=session"
            else:
                reason = "unknown provider"
            skipped.append(SkippedModel(model=model.id, reason=reason))
        return ModelWalk(role=role, chosen="", pinned=bool(pinned), skipped=skipped)

    def resolve_quality_model(self, quality: str) -> str:
        """Map a quality tier to a model PREFERENCE (the "choose the model for me" literal). low/medium
        prefer a sovereign self-host GLM (private, cheap); high/critical fall through to the normal
        best-available resolution. Returns "" when the tier implies normal resolution OR no sovereign
        candidate is reachable — a graceful preference layered on resolve_model, never a hard pin that
        errors on a missing key. Pass the result as the per-call override.

        An explicit tier_sovereign_model is the only candidate (honour the user's pin); otherwise each
        _SOVEREIGN_MODELS id is tried in order and the FIRST whose key is present wins — so a z.ai key
        (`zai/`) and a Novita key (`novita/`) both light up GLM with no configuration."""
        if quality not in ("low", "medium"):
            return ""
        candidates = (self.tier_sovereign_model,) if self.tier_sovereign_model else _SOVEREIGN_MODELS
        for candidate in candidates:
            if candidate and Model.from_litellm_id(candidate).is_available():
                return candidate
        return ""

    @functools.cached_property
    def _recommendations(self) -> dict[str, list[str]]:
        return PackageData.models_data().get("recommendations", {})

    def fallbacks_for(self, role: ModelRole) -> list[str]:
        """User-configured fallback model ids for a role (empty → use bundled defaults)."""
        raw = getattr(self, f"{role}_fallbacks", "") or ""
        return [model.strip() for model in raw.split(",") if model.strip()]

    def chain_for(self, role: ModelRole) -> ModelChain:
        """Build a model fallback chain for a role (image, component, video): the configured
        primary, then user-configured fallbacks if any, else the bundled recommendations."""
        configured = self.model_for(role)
        recommendations = self.fallbacks_for(role) or self._recommendations.get(role, [])
        return ModelChain.from_config(role, configured, recommendations)
