"""Groq adapter — `ChatClient` backed by Groq's OpenAI-compatible chat completions API.

`gpt-oss` models spend completion tokens on hidden reasoning before emitting any
visible output. Without `reasoning_effort: low` and `response_format: json_object`,
a small structured reply can be truncated mid-reasoning — and a truncated body is
indistinguishable from a malformed one on the wire. See BUILD.md R9.
"""

import os

import httpx

from src.llm.client import ChatClient, ChatRequest, ChatResponse, Usage

_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


class GroqClient(ChatClient):
    def __init__(self, api_key: str | None = None, timeout: float = 30.0) -> None:
        self._api_key = api_key or os.environ["GROQ_API_KEY"]
        self._client = httpx.Client(timeout=timeout)

    def complete(self, request: ChatRequest) -> ChatResponse:
        payload: dict = {
            "model": request.model,
            "messages": [message.model_dump() for message in request.messages],
            "temperature": request.temperature,
        }
        if request.max_completion_tokens is not None:
            payload["max_completion_tokens"] = request.max_completion_tokens
        if request.response_format is not None:
            payload["response_format"] = {"type": request.response_format}
        if request.reasoning_effort is not None:
            payload["reasoning_effort"] = request.reasoning_effort

        headers = {"Authorization": f"Bearer {self._api_key}"}
        response = self._client.post(_ENDPOINT, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()

        choice = body["choices"][0]
        usage = body.get("usage", {})

        return ChatResponse(
            content=choice["message"]["content"],
            usage=Usage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
            ),
            model=request.model,
            provider="groq",
        )
