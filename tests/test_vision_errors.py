"""A provider fault on the model call — no credits, a rejected key, an unknown model id, no answer —
reaches the agent in interact's own words with the way out, never as a raw ``litellm.RateLimitError``
traceback (#124, #125). The translation lives at the ONE litellm seam (``_vision_completion`` and
``transcribe_audio``); ``@instrumented`` closes the ``ERROR:`` contract (tests/test_server.py)."""

import litellm
import pytest

import interact.vision.core as v
from interact.vision import VisionError

_MSGS = [{"role": "user", "content": [{"type": "text", "text": "what is this"}]}]
# The shape litellm really hands back for #124: its own stacked prefixes, the provider's sentence,
# then a body the agent cannot act on. Only the provider's sentence should survive into the message.
_SAID = "You have no credits remaining. Add credits to continue using the API"
_RAW = f"RateLimitError: OpenAIException - {_SAID}.\n{{'error': {{'code': 'insufficient_quota'}}}}"


def _raising(exc):
    async def fake(**_kwargs):
        raise exc

    return fake


@pytest.mark.parametrize(
    "exc, cause",
    [
        (
            litellm.exceptions.RateLimitError(message=_RAW, llm_provider="openai", model="gpt-x"),
            "rate-limited or out of credits",
        ),
        (
            litellm.exceptions.AuthenticationError(message=_RAW, llm_provider="openai", model="gpt-x"),
            "rejected the API key",
        ),
        (
            litellm.exceptions.NotFoundError(message=_RAW, model="gpt-x", llm_provider="openai"),
            "does not know this model id",
        ),
        (litellm.exceptions.Timeout(message=_RAW, model="gpt-x", llm_provider="openai"), "did not answer"),
        (
            litellm.exceptions.APIConnectionError(message=_RAW, llm_provider="openai", model="gpt-x"),
            "did not answer",
        ),
        # Any other litellm provider error (a 5xx here) gets the generic cause + the same way out.
        (
            litellm.exceptions.InternalServerError(message=_RAW, llm_provider="openai", model="gpt-x"),
            "failed the request",
        ),
    ],
    ids=[
        "RateLimitError",
        "AuthenticationError",
        "NotFoundError",
        "Timeout",
        "APIConnectionError",
        "InternalServerError",
    ],
)
@pytest.mark.asyncio
async def test_a_provider_fault_becomes_a_vision_error_saying_the_way_out(monkeypatch, exc, cause):
    monkeypatch.setattr(v.litellm, "acompletion", _raising(exc))
    with pytest.raises(VisionError) as info:
        await v._vision_completion(_MSGS, "openai/gpt-x")
    text = str(info.value)
    assert "openai/gpt-x" in text, text  # the id the caller passed, not litellm's stripped one
    assert cause in text, text  # the one-line human cause
    assert _SAID in text and "insufficient_quota" not in text, text  # the provider's sentence, not its body
    assert "model=" in text and "image.model" in text and "list_providers" in text, text
    assert info.value.__cause__ is exc  # the raw class stays reachable for logs


@pytest.mark.asyncio
async def test_a_non_provider_exception_is_not_dressed_up(monkeypatch):
    """Only litellm's provider faults are translated: a bug in interact's own code stays a bug."""
    monkeypatch.setattr(v.litellm, "acompletion", _raising(ValueError("interact bug")))
    with pytest.raises(ValueError):
        await v._vision_completion(_MSGS, "openai/gpt-x")


@pytest.mark.asyncio
async def test_transcription_shares_the_translation(monkeypatch):
    """``transcribe_audio`` is the OTHER litellm call; the same 429 must read the same way there."""
    monkeypatch.setattr(v.litellm, "validate_environment", lambda model: {"keys_in_environment": True})
    monkeypatch.setattr(
        v.litellm,
        "atranscription",
        _raising(litellm.exceptions.RateLimitError(message=_RAW, llm_provider="openai", model="whisper-1")),
    )
    with pytest.raises(VisionError) as info:
        await v.transcribe_audio(b"RIFF....WAVE", model="whisper-1", mime_type="audio/wav")
    text = str(info.value)
    assert "whisper-1" in text and "out of credits" in text and _SAID in text, text
