"""Metering wrapper for the model-use report — BUILD.md task 8.11.

Wraps whatever `ChatClient` the harness passes to `classify_failure` /
`propose_policy` and accumulates call count, cache hits, and token usage —
without either of those functions needing to change their signature to
expose it.
"""

from src.llm.client import ChatClient, ChatRequest, ChatResponse
from src.llm.cost import TokenAccountant


class MeteringChatClient(ChatClient):
    def __init__(self, client: ChatClient, accountant: TokenAccountant) -> None:
        self._client = client
        self.accountant = accountant
        self.calls = 0
        self.cache_hits = 0

    def complete(self, request: ChatRequest) -> ChatResponse:
        response = self._client.complete(request)
        self.calls += 1
        if getattr(self._client, "last_cache_hit", False):
            self.cache_hits += 1
        else:
            self.accountant.record(response.usage, response.model)
        return response

    @property
    def cache_hit_rate(self) -> float:
        return self.cache_hits / self.calls if self.calls else 0.0
