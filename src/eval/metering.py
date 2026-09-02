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


class RoutingMeteringChatClient(ChatClient):
    """A `MeteringChatClient` that also routes by `request.model`.

    `run_batch` takes exactly one `client` for both classify and propose
    calls, differentiated only by the `model` string — but a real run uses
    Gemini for classify and Groq for policy, two different underlying
    clients. This dispatches to whichever client is registered for the
    request's model, while still metering calls/cache-hits/tokens across
    all of them into one shared accountant, so the batch report's
    model-use section covers both roles.
    """

    def __init__(
        self, clients_by_model: dict[str, ChatClient], accountant: TokenAccountant
    ) -> None:
        self._clients_by_model = clients_by_model
        self.accountant = accountant
        self.calls = 0
        self.cache_hits = 0

    def complete(self, request: ChatRequest) -> ChatResponse:
        client = self._clients_by_model[request.model]
        response = client.complete(request)
        self.calls += 1
        if getattr(client, "last_cache_hit", False):
            self.cache_hits += 1
        else:
            self.accountant.record(response.usage, response.model)
        return response

    @property
    def cache_hit_rate(self) -> float:
        return self.cache_hits / self.calls if self.calls else 0.0
