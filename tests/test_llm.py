"""Offline tests for the LLM layer: cache, throttle, and malformed-output parsing.

All against `FakeProvider` — no network calls, no free-tier quota burned.
"""

import httpx
import pytest
from pydantic import BaseModel

from src.llm.cache import CachingChatClient, ResponseCache
from src.llm.client import ChatMessage, ChatRequest
from src.llm.cost import TokenAccountant, shadow_cost
from src.llm.fake import FakeProvider, FakeProviderExhausted
from src.llm.structured import StructuredParseError, parse_structured
from src.llm.throttle import RateLimitExceeded, ThrottledChatClient


def _request(prompt: str = "hello") -> ChatRequest:
    return ChatRequest(model="fake-model", messages=[ChatMessage(role="user", content=prompt)])


class _Point(BaseModel):
    x: int
    y: int


# ---- FakeProvider ----------------------------------------------------------


def test_fake_provider_returns_canned_responses_in_order():
    provider = FakeProvider(['{"x": 1, "y": 2}', '{"x": 3, "y": 4}'])

    first = provider.complete(_request())
    second = provider.complete(_request())

    assert first.content == '{"x": 1, "y": 2}'
    assert second.content == '{"x": 3, "y": 4}'
    assert len(provider.calls) == 2


def test_fake_provider_raises_when_exhausted():
    provider = FakeProvider(["{}"])
    provider.complete(_request())

    with pytest.raises(FakeProviderExhausted):
        provider.complete(_request())


def test_fake_provider_can_raise_a_scripted_exception():
    provider = FakeProvider([RuntimeError("boom")])

    with pytest.raises(RuntimeError, match="boom"):
        provider.complete(_request())


# ---- ResponseCache / CachingChatClient -------------------------------------


def test_cache_miss_then_hit_for_identical_request(tmp_path):
    cache = ResponseCache(tmp_path / "cache.sqlite3")
    provider = FakeProvider(['{"x": 1, "y": 2}'])
    client = CachingChatClient(
        provider, cache, role="classify", provider="fake", prompt_version="v1"
    )

    first = client.complete(_request("same prompt"))
    assert client.last_cache_hit is False
    assert len(provider.calls) == 1

    second = client.complete(_request("same prompt"))
    assert client.last_cache_hit is True
    assert len(provider.calls) == 1
    assert second.content == first.content


def test_cache_miss_for_different_payload(tmp_path):
    cache = ResponseCache(tmp_path / "cache.sqlite3")
    provider = FakeProvider(['{"x": 1, "y": 2}', '{"x": 3, "y": 4}'])
    client = CachingChatClient(
        provider, cache, role="classify", provider="fake", prompt_version="v1"
    )

    client.complete(_request("prompt a"))
    client.complete(_request("prompt b"))

    assert len(provider.calls) == 2


def test_cache_keys_are_scoped_by_role_and_prompt_version(tmp_path):
    cache = ResponseCache(tmp_path / "cache.sqlite3")
    provider = FakeProvider(['{"x": 1, "y": 2}', '{"x": 3, "y": 4}'])
    classify_client = CachingChatClient(
        provider, cache, role="classify", provider="fake", prompt_version="v1"
    )
    policy_client = CachingChatClient(
        provider, cache, role="policy", provider="fake", prompt_version="v1"
    )

    classify_client.complete(_request("same prompt"))
    policy_client.complete(_request("same prompt"))

    assert len(provider.calls) == 2


def test_cache_persists_across_instances_against_same_db(tmp_path):
    db_path = tmp_path / "cache.sqlite3"
    provider = FakeProvider(['{"x": 1, "y": 2}'])
    first_client = CachingChatClient(
        provider, ResponseCache(db_path), role="classify", provider="fake", prompt_version="v1"
    )
    first_client.complete(_request("same prompt"))

    second_client = CachingChatClient(
        provider, ResponseCache(db_path), role="classify", provider="fake", prompt_version="v1"
    )
    second_client.complete(_request("same prompt"))

    assert len(provider.calls) == 1


# ---- ThrottledChatClient ----------------------------------------------------


class _FlakyClient:
    """Raises the given HTTP status `fail_times` times, then delegates to `provider`."""

    def __init__(self, provider, fail_times: int, status_code: int = 429) -> None:
        self._provider = provider
        self._fail_times = fail_times
        self._status_code = status_code
        self._calls = 0

    def complete(self, request):
        self._calls += 1
        if self._calls <= self._fail_times:
            response = httpx.Response(
                self._status_code, request=httpx.Request("POST", "https://example.test")
            )
            raise httpx.HTTPStatusError("failing", request=response.request, response=response)
        return self._provider.complete(request)


def test_throttle_retries_on_429_then_succeeds():
    provider = FakeProvider(['{"ok": true}'])
    flaky = _FlakyClient(provider, fail_times=2, status_code=429)
    sleeps: list[float] = []
    client = ThrottledChatClient(flaky, max_retries=5, sleep=sleeps.append, now=lambda: 0.0)

    response = client.complete(_request())

    assert response.content == '{"ok": true}'
    assert len(sleeps) == 2
    assert sleeps == sorted(sleeps)  # exponential backoff is non-decreasing


def test_throttle_retries_on_503_then_succeeds():
    """A live batch run hit a plain 503 from Gemini — an ordinary transient
    failure, not a rate limit — and it must be retried too, not crash the
    whole batch outright."""
    provider = FakeProvider(['{"ok": true}'])
    flaky = _FlakyClient(provider, fail_times=2, status_code=503)
    sleeps: list[float] = []
    client = ThrottledChatClient(flaky, max_retries=5, sleep=sleeps.append, now=lambda: 0.0)

    response = client.complete(_request())

    assert response.content == '{"ok": true}'
    assert len(sleeps) == 2


def test_throttle_hard_fails_after_exhausting_retries():
    provider = FakeProvider(['{"ok": true}'])
    flaky = _FlakyClient(provider, fail_times=10, status_code=429)
    client = ThrottledChatClient(flaky, max_retries=3, sleep=lambda _: None, now=lambda: 0.0)

    with pytest.raises(RateLimitExceeded):
        client.complete(_request())


def test_throttle_hard_fails_after_exhausting_retries_on_persistent_503():
    provider = FakeProvider(['{"ok": true}'])
    flaky = _FlakyClient(provider, fail_times=10, status_code=503)
    client = ThrottledChatClient(flaky, max_retries=3, sleep=lambda _: None, now=lambda: 0.0)

    with pytest.raises(RateLimitExceeded):
        client.complete(_request())


def test_throttle_does_not_retry_genuine_client_errors():
    class _AlwaysBadRequest:
        def complete(self, request):
            response = httpx.Response(400, request=httpx.Request("POST", "https://example.test"))
            raise httpx.HTTPStatusError("boom", request=response.request, response=response)

    client = ThrottledChatClient(_AlwaysBadRequest(), max_retries=3, sleep=lambda _: None)

    with pytest.raises(httpx.HTTPStatusError):
        client.complete(_request())


# ---- structured.py: malformed parse -----------------------------------------


def test_parse_structured_succeeds_on_first_try():
    provider = FakeProvider(['{"x": 1, "y": 2}'])

    result = parse_structured(provider, _request(), _Point)

    assert result == _Point(x=1, y=2)


def test_parse_structured_recovers_after_malformed_then_valid():
    provider = FakeProvider(["not json at all", '{"x": 5, "y": 6}'])

    result = parse_structured(provider, _request(), _Point, max_retries=2)

    assert result == _Point(x=5, y=6)
    assert len(provider.calls) == 2


def test_parse_structured_strips_markdown_fences():
    provider = FakeProvider(['```json\n{"x": 7, "y": 8}\n```'])

    result = parse_structured(provider, _request(), _Point)

    assert result == _Point(x=7, y=8)


def test_parse_structured_hard_fails_after_bounded_retries():
    provider = FakeProvider(["garbage 1", "garbage 2", "garbage 3"])

    with pytest.raises(StructuredParseError) as exc_info:
        parse_structured(provider, _request(), _Point, max_retries=2)

    assert exc_info.value.attempts == 3
    assert len(provider.calls) == 3


def test_parse_structured_fails_on_schema_mismatch_not_just_bad_json():
    provider = FakeProvider(['{"x": 1}', '{"x": 1}'])  # missing required "y"

    with pytest.raises(StructuredParseError):
        parse_structured(provider, _request(), _Point, max_retries=1)


# ---- cost.py -----------------------------------------------------------------


_PRICING = {
    "usd_per_million_tokens": {"fake-model": {"input": 1.0, "output": 2.0}},
    "usd_to_inr": 90.0,
}


def test_shadow_cost_prices_input_and_output_tokens_separately():
    from src.llm.client import Usage

    usage = Usage(prompt_tokens=1_000_000, completion_tokens=500_000)
    cost = shadow_cost(usage, "fake-model", _PRICING)

    assert cost.usd == pytest.approx(1.0 + 1.0)
    assert cost.inr == pytest.approx(180.0)


def test_shadow_cost_raises_on_unpriced_model():
    from src.llm.client import Usage

    with pytest.raises(KeyError):
        shadow_cost(Usage(prompt_tokens=1, completion_tokens=1), "unknown-model", _PRICING)


def test_token_accountant_accumulates_across_calls():
    from src.llm.client import Usage

    accountant = TokenAccountant(_PRICING)
    accountant.record(Usage(prompt_tokens=1_000_000, completion_tokens=0), "fake-model")
    accountant.record(Usage(prompt_tokens=0, completion_tokens=1_000_000), "fake-model")

    assert accountant.calls == 2
    assert accountant.prompt_tokens == 1_000_000
    assert accountant.completion_tokens == 1_000_000
    assert accountant.usd == pytest.approx(1.0 + 2.0)
