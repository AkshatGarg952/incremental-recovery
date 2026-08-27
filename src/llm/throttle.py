"""Request throttling and exponential backoff on HTTP 429, wrapping any `ChatClient`.

Free-tier rate limits are architectural, not an afterthought: a single N=3,000
batch is ~1,860 calls, comfortably over a free tier's per-minute cap. See
BUILD.md R9.
"""

import time

import httpx

from src.llm.client import ChatClient, ChatRequest, ChatResponse


class RateLimitExceeded(RuntimeError):
    """Raised when a request is still rate-limited after exhausting all retries."""


class ThrottledChatClient(ChatClient):
    def __init__(
        self,
        client: ChatClient,
        min_interval_seconds: float = 0.0,
        max_retries: int = 5,
        base_backoff_seconds: float = 1.0,
        sleep=time.sleep,
        now=time.monotonic,
    ) -> None:
        self._client = client
        self._min_interval = min_interval_seconds
        self._max_retries = max_retries
        self._base_backoff = base_backoff_seconds
        self._sleep = sleep
        self._now = now
        self._last_call_at: float | None = None

    def _wait_for_slot(self) -> None:
        if self._min_interval <= 0 or self._last_call_at is None:
            return
        remaining = self._min_interval - (self._now() - self._last_call_at)
        if remaining > 0:
            self._sleep(remaining)

    def complete(self, request: ChatRequest) -> ChatResponse:
        attempt = 0
        while True:
            self._wait_for_slot()
            try:
                response = self._client.complete(request)
            except httpx.HTTPStatusError as exc:
                self._last_call_at = self._now()
                if exc.response.status_code != 429:
                    raise
                if attempt >= self._max_retries:
                    raise RateLimitExceeded(
                        f"still rate-limited after {attempt} retries"
                    ) from exc
                self._sleep(self._base_backoff * (2**attempt))
                attempt += 1
                continue
            self._last_call_at = self._now()
            return response
