"""FakeProvider — scripted `ChatClient` for offline tests. No network calls.

Responses are queued per instance; each `complete()` call pops the next one.
Queuing a malformed string (or an `Exception` to raise) lets tests exercise
`structured.py`'s bounded-retry path and error handling without a live model.
"""

from src.llm.client import ChatClient, ChatRequest, ChatResponse, Usage


class FakeProviderExhausted(RuntimeError):
    """Raised when `complete()` is called with no scripted responses left."""


class FakeProvider(ChatClient):
    def __init__(self, responses: list[str | Exception], provider: str = "fake") -> None:
        self._responses = list(responses)
        self._provider = provider
        self.calls: list[ChatRequest] = []

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.calls.append(request)
        if not self._responses:
            raise FakeProviderExhausted("FakeProvider has no scripted responses left")
        next_item = self._responses.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return ChatResponse(
            content=next_item,
            usage=Usage(prompt_tokens=10, completion_tokens=max(len(next_item.split()), 1)),
            model=request.model,
            provider=self._provider,
        )
