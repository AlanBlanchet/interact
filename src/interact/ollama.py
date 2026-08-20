"""Ask the running Ollama daemon what is actually pulled.

``models.json`` carries a baked list of Ollama models, scraped when someone last regenerated the
catalog. A baked snapshot cannot know what a user pulled five minutes ago — which is the whole
failure mode: somebody pays for Ollama Cloud, pulls a model, and interact cannot see it, because
the model they paid for postdates the snapshot. That is a design flaw, not a missing row, and no
amount of re-scraping fixes it.

So the daemon is asked directly. ``GET /api/tags`` is the inventory (10 ms on loopback) and
``POST /api/show`` is the per-model capability read — the only honest source for whether a model
does vision, because a cloud model reports no ``families`` and its name says nothing.

Four properties this must have, in order:

* **Silent when absent.** A user with no Ollama sees no error, no warning and no delay. The
  no-daemon path is a bare TCP probe (measured: ~0.1 ms on loopback when nothing listens), taken
  BEFORE any HTTP client exists — building one costs ~35 ms of SSL-context setup, which is the
  real cost this avoids, not the connection refusal. The timeouts below only bound a host that
  ACCEPTS and then stalls, and the cloud endpoint is only ever tried when a key exists, so
  someone who does not use Ollama never pays a wide-area round trip. Silent is not MUTE, though:
  every swallowed failure is logged at DEBUG, or a real bug here would be indistinguishable from
  the absent daemon this is built to tolerate.
* **Cheap on repeat.** ``/api/show`` costs a round trip to ollama.com for a cloud model (~200 ms
  measured), so answers are cached by DIGEST. A digest changes when a model is re-pulled, so the
  cache self-invalidates on exactly the event that makes it wrong, and never otherwise.
* **Honest about what it does not know.** A model whose ``/api/show`` fails — upstream retirement
  is a real case, seen in the wild — is still listed (it IS pulled) with NO capabilities, rather
  than being guessed into the vision pool by its name.
* **Careful with the key.** ``OLLAMA_API_KEY`` is a paid credential and the endpoint is
  user-supplied, so it is sent only where it cannot leak: loopback, or TLS. See :func:`_headers`.

Everything the daemon returns is UNTRUSTED — a third party serves a cloud model — so it is
validated into :class:`TagRow` at the boundary rather than indexed as a raw dict downstream. The
same goes for the on-disk cache, which a corrupt file would otherwise turn into a raise that
silently disables discovery for good.

``OLLAMA_DISCOVERY=0`` switches the whole thing off.

Two deliberate choices in that name. Env rather than ``Config``, because
:mod:`interact.config.settings` imports :mod:`interact.models`, which reaches this module, so
reading typed config from here would close an import cycle — and the other switches that matter
(``OLLAMA_HOST``, ``OLLAMA_API_KEY``) are Ollama's own environment anyway, read exactly the way
:meth:`Model.is_available` reads a provider key. And NOT ``INTERACT_``-prefixed, because
``_LiveConfig.refresh`` deliberately DELETES every ``INTERACT_*`` variable that
``~/.interact/config.env`` does not define — so an ``INTERACT_OLLAMA_DISCOVERY`` set in a shell
would work for a CLI run and then vanish on a long-lived server's first tool call. A switch that
silently stops working is worse than no switch.
"""

import logging
import os
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from interact.ttl_cache import TTLCache, age_of

_log = logging.getLogger(__name__)

#: Where a local daemon listens unless told otherwise — Ollama's own default.
DEFAULT_BASE = "http://localhost:11434"
#: Ollama Cloud's API, which speaks the same endpoints. Only tried when a key exists.
CLOUD_BASE = "https://ollama.com"

#: Loopback refuses instantly, so this only bounds a remote host that accepts but stalls.
_LIST_TIMEOUT = 2.0
#: /api/show on a CLOUD model round-trips through the daemon to ollama.com, so it gets more room.
_SHOW_TIMEOUT = 5.0
#: Capability probes run concurrently; a handful of cloud models would otherwise cost a second.
_PROBE_WORKERS = 8
#: How many UNCACHED probes one discovery may spend. Cached digests never count against it, so a
#: box with many models fills its cache over a few runs instead of stalling any single one.
#: Sized above a real Ollama Cloud catalog (19 entries when measured) so the common case is
#: never truncated; at 8 workers that is a few concurrent rounds, once, then cached by digest.
_MAX_NEW_PROBES = 32

#: Capabilities are keyed by digest, which only changes on a re-pull — so a week is not stale.
_CAPABILITY_CACHE = TTLCache("ollama_capabilities.json", ttl_seconds=7 * 24 * 60 * 60)
#: A model whose capabilities we could NOT read (upstream retirement is the real case) must not
#: cost a wide-area round trip in every process — but a transient failure must not be believed for
#: a week either, so a failure is remembered only this long before it is worth asking again.
_FAILURE_TTL = 15 * 60
#: A long-lived MCP server calls into the registry on every tool invocation. One minute keeps the
#: daemon off that hot path while still noticing a model pulled during the session.
_MEMO_TTL = 60.0
_MEMO: dict[str, tuple[float, list["OllamaModel"]]] = {}

#: What Ollama reports in `capabilities` that we care about. Everything else (`tools`, `thinking`,
#: `insert`) says nothing about whether interact can drive the model.
_VISION = "vision"
_COMPLETION = "completion"
_EMBEDDING = "embedding"

#: Every character a real Ollama reference uses — `hf.co/user/repo:Q4_K_M`, `qwen3.5:397b`. The
#: point is what it EXCLUDES: this name is printed to a terminal by `interact doctor` and handed
#: to an agent by `list_providers`, and for a cloud model a third party writes it. Control
#: characters (ANSI escapes) and whitespace have no legitimate place in it.
_NAME = re.compile(r"^[A-Za-z0-9._:/@+-]+$")


class TagRow(BaseModel):
    """One row of ``/api/tags``, validated at the boundary rather than indexed as a raw dict."""

    model_config = {"extra": "ignore"}

    name: str
    digest: str = ""
    #: The daemon's own marker for a model it proxies to Ollama Cloud.
    remote_host: str = ""
    details: dict = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _plausible_name(cls, value: str) -> str:
        if not _NAME.match(value):
            raise ValueError(f"implausible model name: {value!r}")
        return value

    @property
    def parameter_size(self) -> str:
        return str(self.details.get("parameter_size") or "")


class CapabilityCache(BaseModel):
    """The on-disk memo. Typed because a corrupt file used to raise out of the read, and the
    caller's own ``except`` then made that look exactly like "no daemon" — permanently, since the
    file is only rewritten AFTER a successful read."""

    model_config = {"extra": "ignore"}

    fetched_at: float = 0.0
    #: digest -> capabilities, for models we successfully read.
    capabilities: dict[str, list[str]] = Field(default_factory=dict)
    #: digest -> when we last failed to read them.
    failures: dict[str, float] = Field(default_factory=dict)

    @classmethod
    def load(cls) -> "CapabilityCache":
        try:
            return cls.model_validate(_CAPABILITY_CACHE.read() or {})
        except ValidationError:
            _log.debug("ollama capability cache is unreadable; starting fresh", exc_info=True)
            return cls()

    def known(self) -> dict[str, list[str]]:
        """digest -> capabilities, with a still-fresh FAILURE folded in as an empty list — which
        :func:`discover` already reads as "known, and it is nothing". That is what stops a
        permanently-broken model costing a round trip in every process, with no extra parameter."""
        if age_of(self.fetched_at) > _CAPABILITY_CACHE.ttl_seconds:
            return {}
        known = dict(self.capabilities)
        for digest, when in self.failures.items():
            if age_of(when) <= _FAILURE_TTL:
                known.setdefault(digest, [])
        return known


@dataclass(frozen=True)
class OllamaModel:
    """One model the daemon says it has, and what it says the model can do."""

    name: str
    capabilities: tuple[str, ...] = ()
    cloud: bool = False
    parameter_size: str = ""
    digest: str = ""
    #: The endpoint that actually answered. Not cosmetic: discovery walks a ladder, so the base
    #: a caller GUESSES first is not necessarily the one the model came from — and this is also
    #: the base litellm will send the completion to, so naming it makes the two checkable.
    base: str = ""
    #: Whether we ASKED the daemon about this model on this pass. Distinguishes "probed and it
    #: refused" from "never got round to it", which look identical from the capabilities alone —
    #: and only the first is a failure worth remembering.
    probed: bool = False

    @property
    def model_id(self) -> str:
        """The litellm id — the same ``ollama/<name>`` form the baked catalog uses, so a
        discovered row and a baked row are the SAME registry entry rather than two."""
        return f"ollama/{self.name}"

    @property
    def vision(self) -> bool:
        return _VISION in self.capabilities

    @property
    def chat(self) -> bool:
        """Whether it answers a prompt at all. An embedding model returns vectors, so it must
        never be offered as a fallback for a job that needs a reply."""
        return not (_EMBEDDING in self.capabilities and _COMPLETION not in self.capabilities)

    def describe(self) -> str:
        """One human line for `interact doctor`."""
        traits = [t for t in (self.vision and "vision", self.cloud and "cloud") if t]
        if not self.capabilities:
            traits.append("capabilities unavailable")
        if self.parameter_size:
            traits.append(self.parameter_size)
        return f"{self.name}" + (f" ({', '.join(traits)})" if traits else "")


def normalise_base(value: str) -> str:
    """Ollama's own convention lets ``OLLAMA_HOST`` be scheme-less (``box.lan:11434``), which is
    not a URL — httpx would reject it. Add the scheme and drop a trailing slash."""
    base = value.strip().rstrip("/")
    if not base:
        return ""
    if "://" not in base:
        base = f"http://{base}"
    return base


def candidate_bases() -> list[str]:
    """Where to look, in order.

    An explicitly configured host is the only place we look — someone who named a host meant it.
    Otherwise: the local daemon, then Ollama Cloud IF a key exists. That last condition is what
    keeps a user with no Ollama from ever paying a wide-area round trip.
    """
    for name in ("OLLAMA_API_BASE", "OLLAMA_HOST"):
        configured = normalise_base(os.environ.get(name, ""))
        if configured:
            return [configured]
    bases = [DEFAULT_BASE]
    if os.environ.get("OLLAMA_API_KEY"):
        bases.append(CLOUD_BASE)
    return bases


def _is_local(base: str) -> bool:
    """Whether a base points at this machine — it decides whether the TCP pre-check is worth
    taking, whether the key may travel, and whether a model should be labelled cloud-served (the
    cloud catalog marks its own rows no other way)."""
    return (urlsplit(base).hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}


def _headers(base: str) -> dict[str, str]:
    """The bearer token, but only where it cannot leak.

    ``OLLAMA_API_KEY`` is a paid credential and ``base`` comes from the environment, so the naive
    "always attach it" sends it in CLEARTEXT to whatever host the user named — and Ollama's own
    ``OLLAMA_HOST=box.lan:11434`` convention is scheme-less, which :func:`normalise_base` turns
    into plain ``http://``. Pointing that at a shared workstation would hand the key to that
    host's operator and anyone on the path. Loopback cannot leave the machine and TLS protects
    the rest; a plain-HTTP remote host gets no credential, and Ollama needs none to serve a
    local model anyway.
    """
    key = os.environ.get("OLLAMA_API_KEY", "")
    if not key:
        return {}
    if _is_local(base) or urlsplit(base).scheme == "https":
        return {"Authorization": f"Bearer {key}"}
    _log.debug("withholding OLLAMA_API_KEY from the plaintext remote endpoint %s", base)
    return {}


def _port_open(base: str, timeout: float = 0.25) -> bool:
    """Whether anything is listening at ``base``, by TCP alone.

    This exists purely so the common case — no Ollama at all — costs nothing: an httpx client
    builds an SSL context on construction (~35 ms measured), which is pure waste against a port
    that is not there. A closed port answers in well under a millisecond on loopback.
    """
    parts = urlsplit(base)
    host = parts.hostname
    if not host:
        return False
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _open(base: str) -> httpx.Client:
    return httpx.Client(base_url=base, headers=_headers(base), timeout=_LIST_TIMEOUT)


def _probe(client: httpx.Client, name: str) -> tuple[str, ...]:
    """What ``/api/show`` says this model can do, or ``()`` when it will not say.

    A retired cloud model answers with an error here while still appearing in ``/api/tags``. An
    empty tuple is the honest record of that: it is pulled, and we do not know what it does.

    Catches broadly ON PURPOSE — this runs inside a thread pool whose ``map`` would otherwise
    propagate the first failure and lose every other model's answer with it, so per-item isolation
    has to live here, in the item.
    """
    try:
        payload = client.post("/api/show", json={"model": name}, timeout=_SHOW_TIMEOUT).json()
    except Exception:
        _log.debug("ollama /api/show failed for %s", name, exc_info=True)
        return ()
    if not isinstance(payload, dict) or payload.get("error"):
        return ()
    caps = payload.get("capabilities")
    return tuple(c for c in caps if isinstance(c, str)) if isinstance(caps, list) else ()


def discover(
    *,
    client: httpx.Client | None = None,
    base: str | None = None,
    known: dict[str, list[str]] | None = None,
) -> list[OllamaModel]:
    """Every model the daemon at ``base`` currently has. Never raises; ``[]`` means "not there".

    ``known`` maps digest → capabilities so an already-probed model costs nothing. Pure: no disk
    cache, no memo, no environment ladder — :func:`discover_cached` owns all of that.
    """
    owned = client is None
    client = client or _open(base or DEFAULT_BASE)
    origin = (base or str(client.base_url)).rstrip("/")
    remote = not _is_local(origin)
    known = known or {}
    try:
        try:
            payload = client.get("/api/tags", timeout=_LIST_TIMEOUT).json()
            rows = payload["models"]
        except Exception:
            # No daemon, a stalled host, or something at that port that is not Ollama.
            _log.debug("ollama /api/tags unavailable at %s", origin, exc_info=True)
            return []
        if not isinstance(rows, list):
            return []

        tags: list[TagRow] = []
        for row in rows:
            try:
                tags.append(TagRow.model_validate(row))
            except ValidationError:
                _log.debug("skipping an unusable /api/tags row: %r", row, exc_info=True)

        # Probe only what we have never resolved, up to the budget: a digest we already know is
        # the one round trip worth NOT spending. Whatever the budget leaves over keeps its empty
        # capabilities this round and is picked up by the next, so a very large collection fills
        # in over a few runs rather than stalling any single one.
        unknown = [t.name for t in tags if t.digest not in known]
        probed: dict[str, tuple[str, ...]] = {}
        if unknown:
            names = unknown[:_MAX_NEW_PROBES]

            def isolated(name: str) -> tuple[str, ...]:
                """`pool.map` re-raises the FIRST worker failure and loses every other model's
                answer with it, so isolation belongs at the worker boundary — not only inside
                `_probe`, whose own `except` cannot cover a bug in `_probe` itself. This is what
                makes this function's "never raises" contract actually true."""
                try:
                    return _probe(client, name)
                except Exception:
                    _log.debug("ollama capability probe blew up for %s", name, exc_info=True)
                    return ()

            with ThreadPoolExecutor(max_workers=_PROBE_WORKERS) as pool:
                probed = dict(zip(names, pool.map(isolated, names)))

        found = []
        for tag in tags:
            cached = known.get(tag.digest)
            caps = tuple(cached) if cached is not None else probed.get(tag.name, ())
            found.append(
                OllamaModel(
                    name=tag.name,
                    capabilities=caps,
                    # `remote_host` is the daemon's own marker for a model it proxies to Ollama
                    # Cloud and `:cloud` is the user-visible convention — but the cloud endpoint's
                    # OWN catalog carries neither, so where we asked counts too.
                    cloud=remote or bool(tag.remote_host) or tag.name.endswith(":cloud"),
                    parameter_size=tag.parameter_size,
                    digest=tag.digest,
                    base=origin,
                    probed=tag.name in probed,
                )
            )
        return found
    finally:
        if owned:
            client.close()


def discover_cached() -> list[OllamaModel]:
    """The cached, environment-aware read the registry uses. Never raises, never blocks long.

    Walks :func:`candidate_bases` until one answers with at least one model, memoises the result
    for a minute, and persists the per-digest capabilities so a fresh process skips the expensive
    half. Failures at every level are silent to the caller and logged at DEBUG.
    """
    if os.environ.get("OLLAMA_DISCOVERY", "1").strip().lower() in {"0", "false", "no"}:
        return []

    bases = candidate_bases()
    memo_key = "|".join(bases)
    hit = _MEMO.get(memo_key)
    if hit and (time.monotonic() - hit[0]) < _MEMO_TTL:
        return hit[1]

    cache = CapabilityCache.load()
    known = cache.known()
    found: list[OllamaModel] = []
    for base in bases:
        # Only worth pre-checking a LOCAL base: there a closed port is the common case and the
        # probe is ~0.1 ms, so it saves building a client for nothing. Against a REMOTE base the
        # probe costs a whole extra round trip and almost never saves one, so skip it.
        if _is_local(base) and not _port_open(base):
            continue
        try:
            with _open(base) as client:
                found = discover(client=client, known=known)
        except Exception:  # a malformed base, a DNS failure — never the caller's problem
            _log.debug("ollama discovery failed against %s", base, exc_info=True)
            found = []
        if found:
            break

    if found:
        now = time.time()
        capabilities = {d: c for d, c in cache.capabilities.items() if c}
        failures = dict(cache.failures)
        for model in found:
            if not model.digest:
                continue
            if model.capabilities:
                capabilities[model.digest] = list(model.capabilities)
                failures.pop(model.digest, None)
            elif model.probed:
                # Only a model we actually ASKED about counts as a failure. Stamping one the
                # budget skipped would suppress it for the whole failure window without a single
                # request ever having been made about it.
                #
                # setdefault, never assign: a stamp we merely REPLAYED from cache must keep its
                # original time, or it would be renewed forever and never retried.
                failures.setdefault(model.digest, now)
        _CAPABILITY_CACHE.write(
            CapabilityCache(
                fetched_at=now, capabilities=capabilities, failures=failures
            ).model_dump()
        )

    _MEMO[memo_key] = (time.monotonic(), found)
    return found


def serving() -> list[OllamaModel]:
    """The models a caller can actually PASS as a model id — the chat-capable ones.

    One accessor rather than a ``[m for m in discover_cached() if m.chat]`` repeated at each of
    the three surfaces that needs it (doctor, the MCP tool, the registry merge); "a model you can
    actually use" is one idea and belongs in one place.
    """
    return [m for m in discover_cached() if m.chat]


def reachable() -> bool:
    """Whether any candidate daemon answers at all — for a test that must skip without one."""
    for base in candidate_bases():
        try:
            with _open(base) as client:
                if client.get("/api/tags", timeout=_LIST_TIMEOUT).status_code == 200:
                    return True
        except Exception:
            continue
    return False


def reset_cache() -> None:
    """Drop the process memo. The registry reloads within one process across tests and CLI
    commands, and a stale memo would make a monkeypatched daemon invisible."""
    _MEMO.clear()


__all__ = [
    "CLOUD_BASE",
    "DEFAULT_BASE",
    "CapabilityCache",
    "OllamaModel",
    "TagRow",
    "candidate_bases",
    "discover",
    "discover_cached",
    "normalise_base",
    "reachable",
    "reset_cache",
    "serving",
]
