"""Model metadata that is CURRENT, and that says how current it is.

The shipped ``data/models.json`` is a snapshot: context windows and prices age silently, and a
user reading them has no way to tell whether they stopped being true months ago. This fetches
OpenRouter's public catalog — a plain unauthenticated GET, no signup, no per-user key — and falls
back to LiteLLM's MIT-licensed static file, which is already a dependency.

Why not Artificial Analysis: its free tier requires a per-user key and its terms are "internal
use only and no redistribution", so an open-source tool can neither bundle a key nor ship its
scores. Nothing here needs a credential.

The invariant worth stating: **the catalog always carries its source and its age.** Serving stale
data is fine when the network is down; serving it as though it were live is the bug being fixed.
"""

import json
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import httpx

#: How long a fetched catalog is considered current. Model catalogs move in days, not minutes, and
#: every refetch is a network call on someone's editor startup — so this is deliberately long.
TTL_SECONDS = 12 * 60 * 60

_OPENROUTER_URL = "https://openrouter.ai/api/v1/models"
_FETCH_TIMEOUT = 6.0


@dataclass(frozen=True)
class ModelInfo:
    """What a caller actually needs to choose or price a model."""

    id: str
    name: str = ""
    context_length: int | None = None
    input_cost_per_token: float | None = None
    output_cost_per_token: float | None = None
    input_modalities: tuple[str, ...] = ()


@dataclass(frozen=True)
class Catalog:
    """Models plus the provenance a UI must show alongside them."""

    models: list[ModelInfo]
    source: str  # "openrouter" | "litellm" | "bundled"
    fetched_at: float

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.fetched_at)

    @property
    def is_live(self) -> bool:
        """True only for data fetched from the network within its TTL. A UI that shows a price
        should show this too — otherwise it repeats the problem this module exists to fix."""
        return self.source == "openrouter" and self.age_seconds <= TTL_SECONDS

    def describe(self) -> str:
        return f"{len(self.models)} models · {self.source} · {describe_age(self.age_seconds)}"


def describe_age(seconds: float) -> str:
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def cache_path() -> Path:
    """Beside the agent registry, on the same fixed path — the CLI and the extension both read
    it, so it must not move with ``INTERACT_DEBUG_DIR``."""
    return Path.home() / ".interact" / "out" / "model_catalog.json"


def _num(value) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _from_openrouter(payload: dict) -> list[ModelInfo]:
    out: list[ModelInfo] = []
    for raw in payload.get("data") or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue  # a malformed entry must not lose the rest of the catalog
        pricing = raw.get("pricing") or {}
        arch = raw.get("architecture") or {}
        out.append(ModelInfo(
            id=str(raw["id"]),
            name=str(raw.get("name") or raw["id"]),
            context_length=raw.get("context_length") if isinstance(raw.get("context_length"), int) else None,
            input_cost_per_token=_num(pricing.get("prompt")),
            output_cost_per_token=_num(pricing.get("completion")),
            input_modalities=tuple(arch.get("input_modalities") or ()),
        ))
    return out


def _from_litellm() -> list[ModelInfo]:
    """LiteLLM ships the same facts as a static MIT-licensed map, and it is already a dependency —
    so the offline path needs no vendored copy of our own."""
    try:
        import litellm

        data = getattr(litellm, "model_cost", None) or {}
    except Exception:
        return []
    out: list[ModelInfo] = []
    for model_id, raw in data.items():
        if not isinstance(raw, dict):
            continue
        modalities = ["text"]
        if raw.get("supports_vision"):
            modalities.append("image")
        if raw.get("supports_audio_input"):
            modalities.append("audio")
        out.append(ModelInfo(
            id=str(model_id),
            name=str(model_id),
            context_length=raw.get("max_input_tokens") if isinstance(raw.get("max_input_tokens"), int) else None,
            input_cost_per_token=_num(raw.get("input_cost_per_token")),
            output_cost_per_token=_num(raw.get("output_cost_per_token")),
            input_modalities=tuple(modalities),
        ))
    return out


def _read_cache() -> Catalog | None:
    try:
        raw = json.loads(cache_path().read_text())
        models = [ModelInfo(
            id=m["id"], name=m.get("name", ""),
            context_length=m.get("context_length"),
            input_cost_per_token=m.get("input_cost_per_token"),
            output_cost_per_token=m.get("output_cost_per_token"),
            input_modalities=tuple(m.get("input_modalities") or ()),
        ) for m in raw["models"]]
    except Exception:
        return None  # a truncated or hand-edited cache is not worth a crash
    if not models:
        return None
    return Catalog(models=models, source=raw.get("source", "openrouter"),
                   fetched_at=float(raw.get("fetched_at", 0)))


def _write_cache(catalog: Catalog) -> None:
    try:
        path = cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "source": catalog.source,
            "fetched_at": catalog.fetched_at,
            "models": [vars(m) | {"input_modalities": list(m.input_modalities)} for m in catalog.models],
        }))
    except OSError:
        pass  # caching is an optimisation; failing to cache must never fail the call


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    """The freshest catalog available, never raising.

    Order: a cache still inside its TTL, then a live fetch, then a STALE cache, then LiteLLM's
    static map. The last two are marked not-live, so a caller can say so rather than presenting
    aged numbers as current.
    """
    cached = _read_cache()
    if cached is not None and cached.age_seconds <= TTL_SECONDS:
        return cached

    try:
        response = httpx.get(_OPENROUTER_URL, timeout=_FETCH_TIMEOUT)
        response.raise_for_status()
        models = _from_openrouter(response.json())
        if models:
            fresh = Catalog(models=models, source="openrouter", fetched_at=time.time())
            _write_cache(fresh)
            return fresh
    except Exception:
        pass  # offline, rate-limited, or the shape changed — fall through, never raise

    if cached is not None:
        return cached  # stale beats nothing, and `is_live` already says it is stale
    return Catalog(models=_from_litellm(), source="litellm", fetched_at=0.0)
