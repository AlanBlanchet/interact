"""Choosing a model by what it SCORES, and saying who measured it.

"maybe instead of 'intelligence' and things like that we could do a 'aa.intelligence'? aa stands
for artificial analysis... we should turn all the benchmarks and possible comparisons we can make
into variables that are compared, such that if tomorrow a better model shows and respects the
criterias, then it would work!"

A pinned model id is a claim frozen at the moment somebody typed it. A CRITERION is the claim
itself, re-resolved every spawn — and each variable is NAMESPACED BY ITS SOURCE, because a bare
`intelligence` hides who measured it and two leaderboards rarely agree.
"""

import pytest

from interact.models import Benchmark, Model, ModelCapability
from interact.criteria import Criteria, CriteriaError, Variables


@pytest.fixture
def registry():
    """Three models with known scores, prices and capabilities.

    They carry no provider key, so every selection passes `available_only=False` — availability
    is its own concern, and mixing it in would make these pass or fail on the machine's env.
    """
    Model._reset()
    for spec in [
        dict(id="cheap-eyes", capabilities={ModelCapability.VLM},
             input_cost_per_million=0.5, output_cost_per_million=1.0, intelligence_score=10.0),
        dict(id="sharp-eyes", capabilities={ModelCapability.VLM},
             input_cost_per_million=8.0, output_cost_per_million=24.0, intelligence_score=40.0),
        dict(id="blind-but-cheap", capabilities=set(),
             input_cost_per_million=0.1, output_cost_per_million=0.2, intelligence_score=20.0),
    ]:
        Model._register(Model(provider="p", **spec))
    yield
    Model._reset()


def test_every_variable_says_who_measured_it(registry):
    """The naming rule, stated as a test: no variable without a source namespace."""
    names = {v.name for v in Variables.all()}
    assert "aa.intelligence" in names, "the owner's own example must work"
    assert "price.in" in names and "price.out" in names
    assert "cap.vlm" in names
    # Benchmarks are namespaced by WHERE the number came from, never lumped together.
    assert "gui.screenspot" in names, "a grounding leaderboard is not Artificial Analysis"
    assert "aa.mmmu" in names
    assert all("." in n for n in names), f"un-namespaced variables: {[n for n in names if '.' not in n]}"


def test_a_new_benchmark_becomes_a_variable_with_no_code_change(registry):
    """"turn all the benchmarks... into variables" — the registry IS the source of truth, so a
    leaderboard added to the data tomorrow is usable in a criterion the same day."""
    added = Benchmark(id="brand_new", name="Brand New", description="d",
                      source="Artificial Analysis", namespace="aa", category="image")
    Benchmark._register(added)
    try:
        assert "aa.brand_new" in {v.name for v in Variables.all()}
        Criteria.parse("aa.brand_new > 0.5")  # parses, because the variable exists
    finally:
        # Remove exactly what was added — resetting the registry would wipe the shipped
        # benchmarks for every test after this one (they are registered at import time and
        # never come back).
        Benchmark.registry().remove(added)


def test_criteria_read_as_english(registry):
    c = Criteria.parse("gui.screenspot > 0.8")
    assert c.terms[0].field == "gui.screenspot" and c.terms[0].op == ">"
    assert Criteria.parse("price.in < 5").terms[0].field == "price.in"
    assert len(Criteria.parse("aa.intelligence >= 30 and price.in < 10").terms) == 2


def test_an_unnamespaced_or_unknown_variable_is_refused_where_it_is_written(registry):
    """A typo must fail LOUDLY at parse time, never silently match nothing at 3am. The bare
    name is refused too: it is exactly the ambiguity the namespace exists to remove."""
    for junk in ["intelligence >= 30", "mmlu-pro-max > 0.8", "aa.nope > 1",
                 "price.in", "price.in <", "> 5", ""]:
        with pytest.raises(CriteriaError):
            Criteria.parse(junk)
    # and the message names what they typed plus what exists
    with pytest.raises(CriteriaError) as e:
        Criteria.parse("intelligence >= 30")
    assert "intelligence" in str(e.value) and "aa.intelligence" in str(e.value)


def test_it_selects_the_cheapest_model_that_clears_the_bar(registry):
    assert Criteria.parse("aa.intelligence >= 30").choose(available_only=False).id == "sharp-eyes"
    assert Criteria.parse("aa.intelligence >= 5").choose(available_only=False).id == "blind-but-cheap"
    assert Criteria.parse("price.in < 1").choose(available_only=False).id == "blind-but-cheap"


def test_a_capability_can_be_demanded_by_name(registry):
    """A visual judge that cannot see is not a cheaper visual judge, it is a wrong answer."""
    chosen = Criteria.parse("cap.vlm and price.in < 100").choose(available_only=False)
    assert chosen is not None and chosen.id == "cheap-eyes"


def test_unknown_never_qualifies_and_nothing_matching_refuses_loudly(registry):
    assert Criteria.parse("aa.intelligence > 999").choose(available_only=False) is None
    # No published grounding score is attached to these three: unknown is not good.
    assert Criteria.parse("gui.screenspot > 0.1").choose(available_only=False) is None
    why = Criteria.parse("aa.intelligence > 999 and price.in < 1").explain(available_only=False)
    assert "aa.intelligence" in why and "999" in why


def test_a_criterion_where_a_model_id_goes_resolves_before_the_cli_sees_it(registry):
    from interact.agents.run import resolve_model

    _, name = resolve_model("claude-sonnet-5", {})
    assert name == "claude-sonnet-5", "an id passes through untouched"
    _, name = resolve_model("aa.intelligence >= 30", {}, available_only=False)
    assert name == "sharp-eyes", "a criterion must arrive at the CLI as a real model"


def test_a_criterion_that_matches_nothing_refuses_loudly(registry):
    from interact.agents.run import ModelUnavailable, resolve_model

    with pytest.raises(ModelUnavailable) as e:
        resolve_model("aa.intelligence > 999", {}, available_only=False)
    assert "999" in str(e.value)
