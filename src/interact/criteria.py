"""Choosing a model by what it SCORES, not by what it is called.

    agent_models.json:  {"visual-critic": "screenspot > 0.85 and price < 10"}

A pinned model id is a claim frozen at the moment somebody typed it. It cannot notice a better
model shipping, a price cut, or — the case that cost this project weeks — that the tier was never
good enough for the job it was pinned to. A CRITERION is that claim written down instead:
"whatever currently clears this bar, cheapest first", re-resolved every time it is asked.

The grammar is deliberately one line of English:

    screenspot > 0.85          a published benchmark score (any id in benchmarks.json)
    price < 5                  input $/M — "control price", his words
    out_price <= 20            output $/M, when that is the side that hurts
    intelligence >= 30         the catalog's own capability score
    vlm                        a capability, demanded by name
    ... and ...                several terms, all of which must hold

Everything is checked at PARSE time: an unknown field raises rather than silently matching
nothing at three in the morning, which is how a criterion becomes a lie.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import ClassVar

from interact.models import Benchmark, Model, ModelCapability


class CriteriaError(ValueError):
    """A criterion that cannot be evaluated — raised where it is WRITTEN, never at use."""


#: Fields that are not benchmarks: how to read them off a model.
_SCALARS: dict[str, str] = {
    "price": "input_cost_per_million",
    "out_price": "output_cost_per_million",
    "intelligence": "intelligence_score",
}

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


@dataclass(frozen=True)
class Term:
    """One clause. A bare capability has no op or value — it is a yes/no."""

    field: str
    op: str = ""
    value: float = 0.0

    def __str__(self) -> str:
        return self.field if not self.op else f"{self.field} {self.op} {self.value:g}"

    def score_of(self, model: Model) -> float | None:
        """What this term measures on ``model``, or None when nothing measured it.

        None is NOT zero and never qualifies: "unknown" is exactly the thing a criterion is
        written to exclude.
        """
        attr = _SCALARS.get(self.field)
        if attr is not None:
            return getattr(model, attr, None)
        bench = Benchmark.by_id(self.field)
        if bench is None:
            return None
        measured = bench.score_for(model)
        if measured is not None:
            return measured
        for scored, value in bench.published_models_in_registry():
            if scored.id == model.id:
                return value
        return None

    def holds(self, model: Model) -> bool:
        if not self.op:
            cap = ModelCapability(self.field)
            return model.can(cap)
        got = self.score_of(model)
        if got is None:
            return False
        return _OPS[self.op](got, self.value)


@dataclass(frozen=True)
class Criteria:
    """A model requirement, as a sentence somebody can read and change."""

    terms: tuple[Term, ...] = field(default_factory=tuple)
    source: str = ""

    #: Cache of what a capability name may be, so a typo is caught rather than treated as one.
    _CAPS: ClassVar[set[str]] = {c.value for c in ModelCapability}

    def __str__(self) -> str:
        return self.source or " and ".join(str(t) for t in self.terms)

    @classmethod
    def parse(cls, text: str) -> "Criteria":
        """Read a criterion, refusing anything nobody can evaluate.

        Raises `CriteriaError` with the offending clause — the message is read by whoever typed
        it, so it names the thing they typed, never the parser's internals.
        """
        if not text or not text.strip():
            raise CriteriaError("an empty criterion selects nothing — say what you want")
        terms: list[Term] = []
        for clause in re.split(r"\s+and\s+|,", text):
            if not clause.strip():
                continue
            if (m := _TERM.match(clause)) is not None:
                name, op, value = m.group(1), m.group(2), float(m.group(3))
                if name not in _SCALARS and Benchmark.by_id(name) is None:
                    known = ", ".join(sorted([*_SCALARS, *(b.id for b in Benchmark.registry())]))
                    raise CriteriaError(
                        f"{name!r} is not a benchmark or a measure interact knows. Try one of: {known}"
                    )
                terms.append(Term(name, op, value))
            elif (m := _BARE.match(clause)) is not None:
                name = m.group(1)
                if name not in cls._CAPS:
                    raise CriteriaError(
                        f"{name!r} is not a capability. Try one of: {', '.join(sorted(cls._CAPS))}"
                    )
                terms.append(Term(name))
            else:
                raise CriteriaError(
                    f"{clause.strip()!r} is not a criterion — write it as 'name > number'"
                )
        if not terms:
            raise CriteriaError("an empty criterion selects nothing — say what you want")
        return cls(tuple(terms), text.strip())

    def qualifying(self, available_only: bool = True) -> list[Model]:
        """Every model that clears EVERY term, cheapest first.

        Cheapest-first is the point: the criterion is a FLOOR on quality, and under that floor
        thrift decides — which is the opposite of a pinned id, where the price is whatever the
        pin happened to cost.
        """
        pool = [m for m in Model.registry() if not available_only or m.is_available()]
        fit = [m for m in pool if all(t.holds(m) for t in self.terms)]
        fit.sort(key=lambda m: m.cost_score)
        return fit

    def choose(self, available_only: bool = True) -> Model | None:
        """The one to use, or None. NEVER a fallback: a criterion that quietly resolves to some
        other model is worse than no criterion, because it looks like it worked."""
        fit = self.qualifying(available_only)
        return fit[0] if fit else None

    def explain(self, available_only: bool = True) -> str:
        """Why nothing qualified — which term did the excluding, and how close anyone got.

        A criterion that matches nothing is a question ("is my bar too high, or is nothing
        scored?"), and the answer is knowable, so it is answered rather than left to a shrug.
        """
        pool = [m for m in Model.registry() if not available_only or m.is_available()]
        if not pool:
            return "no model is configured at all — add a provider key first"
        fit = self.qualifying(available_only)
        if fit:
            best = fit[0]
            return f"{len(fit)} model(s) clear {self}; cheapest is {best.id}"
        lines = [f"nothing clears {self}:"]
        for term in self.terms:
            kept = [m for m in pool if term.holds(m)]
            if kept:
                lines.append(f"  {term} — {len(kept)} of {len(pool)} pass")
                continue
            scored = [(m.id, term.score_of(m)) for m in pool if term.score_of(m) is not None]
            if not scored:
                lines.append(f"  {term} — nothing in the catalog is scored on '{term.field}'")
            else:
                near = max(scored, key=lambda p: p[1] or 0)
                lines.append(f"  {term} — nobody passes; best is {near[0]} at {near[1]:g}")
        return "\n".join(lines)
