"""Which model a task actually runs on — best first, and only what is really configured.

Three defects this pins, each of which made interact use a model the user never chose:

1. The chain was ordered by a COST-WEIGHTED score computed offline, so the default for image work
   was a `flash` model even when something far stronger was configured and paid for.
2. A pinned model whose API key is absent was returned anyway, producing an auth failure deep in a
   vendor call rather than falling to the next model that can actually run.
3. The VS Code extension baked `models.json`'s defaults into `INTERACT_*_MODEL`, so the pin was
   never empty and the walk never ran at all — a user with only an OpenAI key got a Gemini id and
   a failure. That half is pinned in the extension's own suite.
"""

import json

import pytest

from interact.models import Model, ModelChain

#: A catalog with an obvious quality order and a deliberately WRONG curated order, so a test can
#: tell "sorted by quality" apart from "kept the order it was handed".
CATALOG = {
    "providers": {
        "alpha": {
            "envKeys": ["ALPHA_KEY"],
            "models": {
                "alpha/weak": {"intelligence_score": 10.0, "input_cost_per_million": 0.1,
                               "output_cost_per_million": 0.1, "capabilities": ["vlm"]},
                "alpha/strong": {"intelligence_score": 90.0, "input_cost_per_million": 9.0,
                                 "output_cost_per_million": 9.0, "capabilities": ["vlm"]},
            },
        },
        "beta": {
            "envKeys": ["BETA_KEY"],
            "models": {
                "beta/middling": {"intelligence_score": 50.0, "input_cost_per_million": 1.0,
                                  "output_cost_per_million": 1.0, "capabilities": ["vlm"]},
            },
        },
        # Needs no key at all. `is_available()` reports False for these deliberately: a keyless
        # provider is a subscription wrapper, and interact never drives someone's subscription
        # credentials — its auth is an interactive device-code flow that blocks forever.
        "keyless": {
            "envKeys": [],
            "models": {
                "keyless/genius": {"intelligence_score": 99.0, "input_cost_per_million": 0.0,
                                   "output_cost_per_million": 0.0, "capabilities": ["vlm"]},
            },
        },
    },
    # Deliberately worst-first: the shipped list is cost-weighted, and reordering it is the point.
    "recommendations": {"image": ["alpha/weak", "beta/middling", "alpha/strong",
                                  "keyless/genius"]},
}


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    monkeypatch.setenv("INTERACT_MODELS_JSON", json.dumps(CATALOG))
    for key in ("ALPHA_KEY", "BETA_KEY"):
        monkeypatch.delenv(key, raising=False)
    Model.load_registry()
    yield
    Model.load_registry()


def _chain(configured: str = "") -> ModelChain:
    return ModelChain.from_config("image", configured, CATALOG["recommendations"]["image"])


def test_the_chain_is_ordered_best_first():
    """The ask, literally: "the default be the best one ... go down the best models hierarchy".
    The curated order is cost-weighted, which is why the default for image work was a flash
    model even for someone paying for something far better."""
    ranked = [m.id for m in _chain().preferences
              if m.id in {"alpha/weak", "beta/middling", "alpha/strong"}]
    assert ranked == ["alpha/strong", "beta/middling", "alpha/weak"]


def test_it_walks_down_to_the_first_model_actually_configured(monkeypatch):
    """Best first, but only among models that can run: with no ALPHA key the strongest is
    unreachable, so the next one down that IS paid for wins."""
    monkeypatch.setenv("BETA_KEY", "k")
    assert _chain().active().id == "beta/middling"


def test_the_strongest_configured_model_wins(monkeypatch):
    monkeypatch.setenv("ALPHA_KEY", "k")
    monkeypatch.setenv("BETA_KEY", "k")
    assert _chain().active().id == "alpha/strong"


def test_a_keyless_provider_is_never_walked_into(monkeypatch):
    """It scores highest and costs nothing, which is exactly why it needs pinning."""
    monkeypatch.setenv("ALPHA_KEY", "k")
    assert _chain().active().id == "alpha/strong"


def test_a_model_with_no_quality_score_sorts_below_one_that_has_it(monkeypatch):
    """Unknown is not "best". A catalog entry lacking a score must not leapfrog a measured model
    because a missing value happened to sort high."""
    catalog = json.loads(json.dumps(CATALOG))
    catalog["providers"]["alpha"]["models"]["alpha/unscored"] = {
        "input_cost_per_million": 0.1, "output_cost_per_million": 0.1, "capabilities": ["vlm"]}
    catalog["recommendations"]["image"] = ["alpha/unscored", "alpha/strong"]
    monkeypatch.setenv("INTERACT_MODELS_JSON", json.dumps(catalog))
    Model.load_registry()
    order = [m.id for m in ModelChain.from_config(
        "image", "", catalog["recommendations"]["image"]).preferences]
    assert order.index("alpha/strong") < order.index("alpha/unscored")


def test_an_explicit_pin_still_leads(monkeypatch):
    """Ranking never overrides a person's own choice: a pin is a decision, and substituting a
    "better" model for it is the same defect facing the other way."""
    monkeypatch.setenv("ALPHA_KEY", "k")
    assert _chain("alpha/weak").preferences[0].id == "alpha/weak"
    assert _chain("alpha/weak").active().id == "alpha/weak"


def test_a_pin_whose_key_is_missing_falls_through_rather_than_failing(monkeypatch):
    """Honouring an unusable pin honours nothing — it produced an auth error from inside a vendor
    call. Falling to the best model that CAN run is strictly more useful, and `interact doctor`
    already flags the missing key, so it is not silent."""
    monkeypatch.setenv("BETA_KEY", "k")
    assert _chain("alpha/strong").active().id == "beta/middling"


def test_nothing_configured_at_all_reports_rather_than_guessing():
    assert _chain().active() is None


# --- The one resolution site --------------------------------------------------------------


def _config(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from interact.config import Config

    return Config()


def test_resolve_model_prefers_the_strongest_configured(monkeypatch):
    """End to end through the site every VLM call funnels into."""
    monkeypatch.setenv("BETA_KEY", "k")
    cfg = _config(monkeypatch)
    monkeypatch.setattr(cfg, "_recommendations", CATALOG["recommendations"], raising=False)
    monkeypatch.setattr(cfg, "image_model", "", raising=False)
    assert cfg.resolve_model("image") == "beta/middling"


def test_resolve_model_falls_through_a_pin_that_cannot_run(monkeypatch):
    """A pin whose key is absent used to be returned regardless, so the failure arrived as an
    auth error from inside a vendor call. Falling to the best model that CAN run is more useful,
    and `interact doctor` already prints the missing key beside the pin."""
    monkeypatch.setenv("BETA_KEY", "k")
    cfg = _config(monkeypatch)
    monkeypatch.setattr(cfg, "_recommendations", CATALOG["recommendations"], raising=False)
    monkeypatch.setattr(cfg, "image_model", "alpha/strong", raising=False)
    assert cfg.resolve_model("image") == "beta/middling"


def test_a_usable_pin_is_still_obeyed(monkeypatch):
    monkeypatch.setenv("ALPHA_KEY", "k")
    cfg = _config(monkeypatch)
    monkeypatch.setattr(cfg, "_recommendations", CATALOG["recommendations"], raising=False)
    monkeypatch.setattr(cfg, "image_model", "alpha/weak", raising=False)
    assert cfg.resolve_model("image") == "alpha/weak"


def test_an_unrunnable_pin_with_nothing_else_available_is_still_named(monkeypatch):
    """When nothing can run, name what the person actually asked for — the resulting auth error
    should mention their model, not one they never chose."""
    cfg = _config(monkeypatch)
    monkeypatch.setattr(cfg, "_recommendations", CATALOG["recommendations"], raising=False)
    monkeypatch.setattr(cfg, "image_model", "alpha/strong", raising=False)
    assert cfg.resolve_model("image") == "alpha/strong"


def test_an_explicit_per_call_override_beats_everything(monkeypatch):
    monkeypatch.setenv("ALPHA_KEY", "k")
    cfg = _config(monkeypatch)
    monkeypatch.setattr(cfg, "_recommendations", CATALOG["recommendations"], raising=False)
    assert cfg.resolve_model("image", "beta/middling") == "beta/middling"


def test_a_pinned_model_outside_the_catalog_is_left_alone(monkeypatch):
    """A self-hosted endpoint or local runner has no entry here, so `is_available()` reports False
    for it — absence of knowledge, not evidence it cannot run. An earlier version of the
    fall-through used that check and would have quietly replaced somebody's pinned local model
    with a hosted one, which is auto-selection overruling a decision rather than making one.
    """
    monkeypatch.setenv("BETA_KEY", "k")
    cfg = _config(monkeypatch)
    monkeypatch.setattr(cfg, "_recommendations", CATALOG["recommendations"], raising=False)
    monkeypatch.setattr(cfg, "image_model", "my-own-box/qwen-vl", raising=False)
    assert cfg.resolve_model("image") == "my-own-box/qwen-vl"


def test_only_a_provably_unusable_pin_is_walked_past(monkeypatch):
    """The narrow case the fall-through is FOR: a provider we know, which declares keys, whose
    keys are absent. That one cannot run, and saying so beats an auth error from a vendor call."""
    from interact.models import Model

    monkeypatch.setenv("BETA_KEY", "k")
    Model.load_registry()
    assert Model.from_litellm_id("alpha/strong").key_missing() is True
    assert Model.from_litellm_id("my-own-box/qwen-vl").key_missing() is False, (
        "an id outside the catalog must not be declared unusable")
