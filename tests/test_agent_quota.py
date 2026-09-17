"""A vendor's quota refusal, remembered past the run that heard it.

"three research agents died on your Fable 7-day quota, twice each": the refusal is a fact about
the ACCOUNT for a period, so hearing it once must spare every later launch the same dead child.
"""

import time

import pytest

from interact.agents import quota


@pytest.fixture(autouse=True)
def _own_store(tmp_path, monkeypatch):
    """Every test writes its own cooldown file, never the developer's."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(quota.COOLDOWN_ENV, raising=False)
    quota.forget()


@pytest.mark.parametrize(
    ("said", "refusal"),
    [
        ("You've reached your Fable limit. Switch to another model", True),
        ('{"rate_limit_info":{"status":"rejected"}}', True),
        ("Error: usage limit reached", True),
        ("openai: rate limit exceeded, retry later", True),
        ('{"rate_limit_info":{"status":"allowed"},"type":"system"}', False),
        ('{"type":"system","subtype":"rate_limit_event"}', False),
        ("check the rate limit dashboard when you have a moment", False),
    ],
)
def test_only_a_refusal_reads_as_one(said, refusal):
    """A healthy child OPENS its stream with a rate-limit line saying `allowed`; reading that as
    a refusal passed over every candidate on the ranked list."""
    assert bool(quota.REFUSAL.search(said)) is refusal


def test_a_refused_model_is_remembered_then_forgotten_on_its_own():
    now = time.time()
    quota.record_refusal("claude", "claude-fable-5-1", now=now, cooldown=60)
    assert quota.blocked_until("claude", "claude-fable-5-1", now=now) == pytest.approx(now + 60)
    assert quota.blocked_until("claude", "claude-fable-5-1", now=now + 61) is None


def test_the_memory_is_per_model_not_per_vendor():
    """Falling through to another model of the same vendor is the whole point."""
    quota.record_refusal("claude", "claude-fable-5-1", cooldown=60)
    assert quota.blocked_until("claude", "claude-fable-5-1") is not None
    assert quota.blocked_until("claude", "claude-opus-5") is None


def test_the_cooldown_length_is_configurable(monkeypatch):
    monkeypatch.setenv(quota.COOLDOWN_ENV, "120")
    now = time.time()
    assert quota.record_refusal("claude", "m", now=now) == pytest.approx(now + 120)


def test_a_nonsense_cooldown_setting_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv(quota.COOLDOWN_ENV, "soon please")
    now = time.time()
    assert quota.record_refusal("claude", "m", now=now) == pytest.approx(now + quota.DEFAULT_COOLDOWN)


def test_expired_notes_do_not_accumulate():
    """The file is rewritten from what is still true, so it cannot grow without bound."""
    old = time.time() - 10_000
    quota.record_refusal("claude", "stale", now=old, cooldown=1)
    quota.record_refusal("claude", "fresh", cooldown=600)
    assert set(quota._read()) == {"claude/fresh"}


def test_a_corrupt_store_is_read_as_empty(tmp_path):
    quota._path().parent.mkdir(parents=True, exist_ok=True)
    quota._path().write_text("{not json", encoding="utf-8")
    assert quota.blocked_until("claude", "m") is None
    quota.record_refusal("claude", "m", cooldown=60)
    assert quota.blocked_until("claude", "m") is not None
