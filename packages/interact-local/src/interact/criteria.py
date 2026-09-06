"""Choosing a model by what it SCORES, and saying who measured it.

    ~/.interact/agents.json:  {"agents": {"visual-critic": "cap.vlm and gui.screenspot > 0.85"}}

A pinned model id is a claim frozen at the moment somebody typed it. It cannot notice a better
model shipping, a price cut, or — the case that cost this project weeks — that the tier was never
good enough for the job it was pinned to. A CRITERION is that claim written down instead:
"whatever currently clears this bar, cheapest first", re-resolved every time it is asked.

Every variable is NAMESPACED BY ITS SOURCE, because a bare ``intelligence`` hides who measured it
and two leaderboards rarely agree:

    aa.intelligence        Artificial Analysis' capability score
    aa.mmmu_pro            Artificial Analysis' MMMU Pro visual metric
    oc.mmbench             the OpenCompass MMBench leaderboard
    gui.screenspot         the GUI-Agent grounding leaderboard
    oc.video_mme           the OpenCompass video leaderboard
    price.in / price.out   $ per million tokens, from the provider catalog
    cap.vlm                a capability, demanded by name

The set is DERIVED, never a hardcoded list: a benchmark added to the registry tomorrow is usable
in a criterion the same day, and a model that ships tomorrow and clears the bar is simply used.
"""

from __future__ import annotations

import re
import math
from dataclasses import dataclass, field
from typing import Callable

from interact import benchmark_tables
from interact.models import Benchmark, Model, ModelCapability


class CriteriaError(ValueError):
    """A criterion that cannot be evaluated — raised where it is WRITTEN, never at use."""


@dataclass(frozen=True)
class Variable:
    """One comparable fact about a model, and where the number comes from."""

    name: str
    describe: str
    read: Callable[[Model], float | None]
    #: True for a yes/no (a capability), which takes no operator.
    flag: bool = False


class Variables:
    """Every comparison interact can make, derived from what is registered right now."""

    #: Scalars off the model record. Namespaced by SOURCE: the capability score is Artificial
    #: Analysis', the prices are the provider catalog's, and saying so is the whole point.
    _SCALARS: dict[str, tuple[str, str]] = {
        "aa.intelligence": ("intelligence_score", "Artificial Analysis capability score"),
        "price.in": ("input_cost_per_million", "input cost, $ per million tokens"),
        "price.out": ("output_cost_per_million", "output cost, $ per million tokens"),
    }

    @classmethod
    def all(cls) -> list[Variable]:
        out: list[Variable] = []
        for name, (attr, describe) in cls._SCALARS.items():
            out.append(Variable(name, describe, _reader(attr)))
        for bench in Benchmark.registry():
            out.append(Variable(
                bench.variable, f"{bench.name} — {bench.source or 'published'}",
                _bench_reader(bench),
            ))
        for cap in ModelCapability:
            out.append(Variable(
                f"cap.{cap.value}", f"the model can do {cap.value}",
                _cap_reader(cap), flag=True,
            ))
        return out

    @classmethod
    def by_name(cls, name: str) -> Variable | None:
        return next((v for v in cls.all() if v.name == name), None)

    @classmethod
    def names(cls) -> list[str]:
        return sorted(v.name for v in cls.all())


def _reader(attr: str) -> Callable[[Model], float | None]:
    return lambda model: getattr(model, attr, None)


def _bench_reader(bench: Benchmark) -> Callable[[Model], float | None]:
    def read(model: Model) -> float | None:
        live = benchmark_tables.load_tables().get(bench.id)
        published = (
            live
            if live is not None
            and (bench.published is None or live.retrieved >= bench.published.retrieved)
            else bench.published
        )
        if published is None:
            return None
        if published.freshness != "current":
            return None
        for entry in published.entries:
            scored = Model.by_id(entry.model_id) if entry.model_id else None
            value = entry.normalized_score
            if entry.status != "eligible" or value is None:
                continue
            if scored is None:
                continue
            if scored.id == model.id:
                return value
        return None

    return read


def _cap_reader(cap: ModelCapability) -> Callable[[Model], float | None]:
    return lambda model: 1.0 if model.can(cap) else 0.0


_OPS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "=": lambda a, b: a == b,
    "==": lambda a, b: a == b,
}

_TERM = re.compile(r"^\s*([\w.-]+)\s*(>=|<=|==|=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$")
_BARE = re.compile(r"^\s*([\w.-]+)\s*$")


def _did_you_mean(name: str) -> str:
    """The namespaced variables whose tail matches what they typed — so a bare `intelligence`
    is answered with `aa.intelligence` rather than the whole catalogue."""
    renamed = {"aa.mmmu": "aa.mmmu_pro", "aa.mmbench": "oc.mmbench"}
    if replacement := renamed.get(name.lower()):
        return f" This metric was corrected; use {replacement!r} and review its meaning."
    tail = name.rsplit(".", 1)[-1].lower()
    near = [n for n in Variables.names() if n.rsplit(".", 1)[-1].lower() == tail]
    return f" Did you mean: {', '.join(near)}?" if near else ""


@dataclass(frozen=True)
class Term:
    """One clause. A capability has no op or value — it is a yes/no."""

    field: str
    op: str = ""
    value: float = 0.0

    def __str__(self) -> str:
        return self.field if not self.op else f"{self.field} {self.op} {self.value:g}"

    def score_of(self, model: Model) -> float | None:
        """What this term measures on ``model``, or None when nothing measured it.

        None is NOT zero and never qualifies: "unknown" is exactly what a criterion excludes.
        """
        var = Variables.by_name(self.field)
        return None if var is None else var.read(model)

    def holds(self, model: Model) -> bool:
        got = self.score_of(model)
        if got is None:
            return False
        if not self.op:
            return got > 0
        return _OPS[self.op](got, self.value)


@dataclass(frozen=True)
class Criteria:
    """A model requirement, as a sentence somebody can read and change."""

    terms: tuple[Term, ...] = field(default_factory=tuple)
    source: str = ""

    def __str__(self) -> str:
        return self.source or " and ".join(str(t) for t in self.terms)

    @classmethod
    def parse(cls, text: str) -> "Criteria":
        """Read a criterion, refusing anything nobody can evaluate.

        Raises `CriteriaError` naming the clause THEY typed — an unknown or un-namespaced
        variable fails here, at the moment it is written, never silently matching nothing later.
        """
        if not text or not text.strip():
            raise CriteriaError("an empty criterion selects nothing — say what you want")
        terms: list[Term] = []
        for clause in re.split(r"\s+and\s+|,", text):
            if not clause.strip():
                continue
            if (m := _TERM.match(clause)) is not None:
                name, op, value = m.group(1), m.group(2), float(m.group(3))
                var = Variables.by_name(name)
                if var is None:
                    raise CriteriaError(
                        f"{name!r} is not a variable interact knows.{_did_you_mean(name)}"
                    )
                if var.flag:
                    raise CriteriaError(f"{name!r} is a yes/no — write it on its own, not with {op}")
                terms.append(Term(name, op, value))
            elif (m := _BARE.match(clause)) is not None:
                name = m.group(1)
                var = Variables.by_name(name)
                if var is None or not var.flag:
                    raise CriteriaError(
                        f"{name!r} is not a capability.{_did_you_mean(name)}"
                        if var is None else
                        f"{name!r} is a measurement — compare it, e.g. '{name} > 0.8'"
                    )
                terms.append(Term(name))
            else:
                raise CriteriaError(
                    f"{clause.strip()!r} is not a criterion — write it as 'name > number'"
                )
        if not terms:
            raise CriteriaError("an empty criterion selects nothing — say what you want")
        return cls(tuple(terms), text.strip())

    @staticmethod
    def _pool(available_only: bool, runnable: Callable[[Model], bool] | None) -> list[Model]:
        """Who is in the running. `runnable`, when given, IS the pool: the caller — a vendor CLI —
        knows what it can actually be pointed at, its own login included. Otherwise every model
        whose key is here (or every model at all, for a dry look at the catalog)."""
        models = Model.catalog()
        if runnable is not None:
            return [m for m in models if runnable(m)]
        return [m for m in models if not available_only or m.is_available()]

    def qualifying(
        self, available_only: bool = True, runnable: Callable[[Model], bool] | None = None
    ) -> list[Model]:
        """Every model clearing EVERY term, cheapest first.

        Cheapest-first is the point: the criterion is a FLOOR on quality, and under that floor
        thrift decides — the opposite of a pin, where the price is whatever the pin happened to
        cost on the day it was typed.
        """
        fit = [m for m in self._pool(available_only, runnable) if all(t.holds(m) for t in self.terms)]
        fit.sort(key=lambda m: m.cost_score)
        return fit

    def choose(
        self, available_only: bool = True, runnable: Callable[[Model], bool] | None = None,
        weights: str = "",
    ) -> Model | None:
        """The one to use, or None. NEVER a fallback: a criterion that quietly resolves to some
        other model is worse than no criterion, because it looks like it worked."""
        fit = self.qualifying(available_only, runnable)
        parsed = _parse_weights(weights)
        if parsed:
            weighted: list[tuple[float, Model]] = []
            for model in fit:
                values = [(Variables.by_name(name), weight) for name, weight in parsed.items()]
                scores = [(variable.read(model) if variable else None, weight) for variable, weight in values]
                numeric = [(score, weight) for score, weight in scores if score is not None]
                if len(numeric) == len(scores) and all(0 <= score <= 1 for score, _ in numeric):
                    weighted.append((sum(score * weight for score, weight in numeric), model))
            weighted.sort(key=lambda pair: (-pair[0], pair[1].cost_score, pair[1].id))
            return weighted[0][1] if weighted else None
        return fit[0] if fit else None

    @staticmethod
    def validate_weights(weights: str) -> None:
        _parse_weights(weights)

    def explain(
        self, available_only: bool = True, runnable: Callable[[Model], bool] | None = None
    ) -> str:
        """Why nothing qualified — which term excluded everyone, and how close anyone got."""
        pool = self._pool(available_only, runnable)
        if not pool:
            if runnable is None:
                return "no model is configured at all — add a provider key first"
            return ("nothing in the catalog is runnable through this CLI — it runs its own vendor's "
                    "models through its login; anything else needs a route and that provider's key")
        fit = self.qualifying(available_only, runnable)
        if fit:
            return f"{len(fit)} model(s) clear {self}; cheapest is {fit[0].id}"
        lines = []
        for term in self.terms:
            about = f"{term} — " if len(self.terms) > 1 else ""
            kept = [m for m in pool if term.holds(m)]
            if kept:
                lines.append(f"  {about}{len(kept)} of {len(pool)} pass")
                continue
            scored = [(m.id, term.score_of(m)) for m in pool if term.score_of(m) is not None]
            if not scored:
                lines.append(f"  {about}nothing in the catalog is scored on '{term.field}'")
            else:
                near = max(scored, key=lambda pair: pair[1] or 0)
                lines.append(f"  {about}nobody passes; best is {near[0]} at {near[1]:g}")
        return "\n".join(lines)


def _parse_weights(text: str) -> dict[str, float]:
    if not text.strip():
        return {}
    weights: dict[str, float] = {}
    benchmark_variables = {benchmark.variable for benchmark in Benchmark.registry()}
    for clause in text.split(","):
        name, separator, raw = clause.partition("=")
        name = name.strip()
        if not separator or name not in benchmark_variables:
            raise CriteriaError(
                f"{name!r} is not a normalized benchmark; raw price, latency, and index units cannot be weighted"
            )
        try:
            value = float(raw)
        except ValueError as exc:
            raise CriteriaError(f"weight for {name!r} is not a number") from exc
        if not math.isfinite(value) or value < 0:
            raise CriteriaError(f"weight for {name!r} must be finite and non-negative")
        if name in weights:
            raise CriteriaError(f"duplicate weight for {name!r}")
        weights[name] = value
    total = sum(weights.values())
    if total <= 0:
        raise CriteriaError("criteria weights must have a positive total")
    return {name: value / total for name, value in weights.items()}
