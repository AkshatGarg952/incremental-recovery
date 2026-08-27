"""Provider-agnostic chat client interface, OpenAI-compatible request/response shape.

Every provider adapter (Gemini, Groq, the offline fake) implements `ChatClient`
against these schemas, so callers never branch on provider.
"""

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float = 0.0
    max_completion_tokens: int | None = None
    response_format: Literal["text", "json_object"] | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int


class ChatResponse(BaseModel):
    content: str
    usage: Usage
    model: str
    provider: str


class ChatClient(ABC):
    """A provider adapter turns a `ChatRequest` into a `ChatResponse`."""

    @abstractmethod
    def complete(self, request: ChatRequest) -> ChatResponse: ...
