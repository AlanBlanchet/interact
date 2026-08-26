"""Choosing a model by what it SCORES, not by what it is called.

"we could say agent: 'MMLU > 0.8' to use a model that has MMLU above a criteria for a
benchmark... Or also control price... etc..."

A pinned model id is a claim frozen at the moment somebody typed it — it cannot notice a better
model shipping, a price cut, or (the case that cost us weeks) that the tier was never good enough
for the job. A CRITERION is the claim itself, re-resolved every time: "whatever currently scores
above this on that benchmark, cheapest first".
"""

import pytest

from interact.models import Model, ModelCapability
from interact.criteria import Criteria, CriteriaError


@pytest.fixture
def registry():
    """Three models with known scores, prices and capabilities.

    They carry no provider key, so every selection here passes `available_only=False` —
    availability is its own concern (tested in test_agent_providers), and mixing it in would
    make these tests pass or fail on the machine's environment.
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


def test_a_benchmark_threshold_reads_as_english(registry):
    c = Criteria.parse("screenspot > 0.8")
    assert c.terms[0].field == "screenspot"
    assert c.terms[0].op == ">"
    assert c.terms[0].value == 0.8
    assert "screenspot" in str(c)


def test_price_and_intelligence_are_criteria_too(registry):
    """"Or also control price... etc..." — the same grammar, so nobody learns two."""
    assert Criteria.parse("price < 5").terms[0].field == "price"
    assert Criteria.parse("intelligence >= 30").terms[0].value == 30.0
    # Several, all of which must hold.
    both = Criteria.parse("intelligence >= 30 and price < 10")
    assert len(both.terms) == 2


def test_a_criterion_nobody_can_evaluate_is_refused_at_parse_time(registry):
    """A typo must fail LOUDLY when it is written, never silently match nothing at 3am."""
    with pytest.raises(CriteriaError) as e:
        Criteria.parse("mmlu-pro-max > 0.8")
    assert "mmlu-pro-max" in str(e.value)
    for junk in ["price", "price <", "> 5", "price !! 5", ""]:
        with pytest.raises(CriteriaError):
            Criteria.parse(junk)


def test_it_selects_the_cheapest_model_that_actually_clears_the_bar(registry):
    """Cheapest that QUALIFIES — the point is a floor on quality, then thrift under it."""
    chosen = Criteria.parse("intelligence >= 30").choose(available_only=False)
    assert chosen is not None and chosen.id == "sharp-eyes"
    # With a bar everybody clears, thrift decides.
    assert Criteria.parse("intelligence >= 5").choose(available_only=False).id == "blind-but-cheap"


def test_price_criteria_bite(registry):
    assert Criteria.parse("price < 1").choose(available_only=False).id == "blind-but-cheap"
    assert Criteria.parse("price > 5").choose(available_only=False).id == "sharp-eyes"


def test_a_capability_can_be_demanded_by_name(registry):
    """A visual judge that cannot see is not a cheaper visual judge, it is a wrong answer."""
    chosen = Criteria.parse("vlm and price < 100").choose(available_only=False)
    assert chosen is not None and chosen.id == "cheap-eyes", "blind-but-cheap must be excluded"


def test_nothing_qualifies_returns_nothing_rather_than_a_surprise(registry):
    """Silently falling back to some other model is how a criterion becomes a lie."""
    assert Criteria.parse("intelligence > 999").choose(available_only=False) is None


def test_a_model_with_no_score_on_the_named_benchmark_never_qualifies(registry):
    """Unknown is not the same as good — the whole reason to write a criterion."""
    # No published screenspot score is attached to these three.
    assert Criteria.parse("screenspot > 0.1").choose(available_only=False) is None


def test_the_criterion_explains_itself_when_it_finds_nothing(registry):
    """A criterion that matched nothing must say WHICH term did the excluding."""
    why = Criteria.parse("intelligence > 999 and price < 1").explain(available_only=False)
    assert "intelligence" in why and "999" in why


def test_a_criterion_where_a_model_id_goes_resolves_before_the_cli_sees_it(registry):
    """The whole feature, at the seam: `agent-models.json` may hold EITHER a model id or a
    criterion, and by the time the vendor CLI is invoked it is a concrete model — the CLI has no
    idea criteria exist."""
    from interact.agents.run import resolve_model

    # An id passes through untouched, exactly as before.
    _, name = resolve_model("claude-sonnet-5", {})
    assert name == "claude-sonnet-5"

    # A criterion resolves to the cheapest model that clears it.
    _, name = resolve_model("intelligence >= 30", {}, available_only=False)
    assert name == "sharp-eyes", "a criterion must arrive at the CLI as a real model"


def test_a_criterion_that_matches_nothing_refuses_loudly(registry):
    """Silently falling back to the vendor default is how you discover, three weeks later, that
    the criterion never applied."""
    from interact.agents.run import ModelUnavailable, resolve_model

    with pytest.raises(ModelUnavailable) as e:
        resolve_model("intelligence > 999", {}, available_only=False)
    assert "999" in str(e.value), "the refusal must name the bar nobody cleared"
