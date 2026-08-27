"""Gemini adapter — `ChatClient` backed by the `generateContent` API."""

import os

import httpx

from src.llm.client import ChatClient, ChatRequest, ChatResponse, Usage

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiClient(ChatClient):
    def __init__(self, api_key: str | None = None, timeout: float = 30.0) -> None:
        self._api_key = api_key or os.environ["GEMINI_API_KEY"]
        self._client = httpx.Client(timeout=timeout)

    def complete(self, request: ChatRequest) -> ChatResponse:
        system_instruction = None
        contents = []
        for message in request.messages:
            if message.role == "system":
                system_instruction = {"parts": [{"text": message.content}]}
                continue
            role = "model" if message.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message.content}]})

        generation_config: dict = {"temperature": request.temperature}
        if request.max_completion_tokens is not None:
            generation_config["maxOutputTokens"] = request.max_completion_tokens
        if request.response_format == "json_object":
            generation_config["responseMimeType"] = "application/json"

        payload: dict = {"contents": contents, "generationConfig": generation_config}
        if system_instruction is not None:
            payload["systemInstruction"] = system_instruction

        url = _ENDPOINT.format(model=request.model)
        response = self._client.post(url, params={"key": self._api_key}, json=payload)
        response.raise_for_status()
        body = response.json()

        candidate = body["candidates"][0]
        content = "".join(part.get("text", "") for part in candidate["content"]["parts"])
        usage_meta = body.get("usageMetadata", {})

        return ChatResponse(
            content=content,
            usage=Usage(
                prompt_tokens=usage_meta.get("promptTokenCount", 0),
                completion_tokens=usage_meta.get("candidatesTokenCount", 0),
            ),
            model=request.model,
            provider="gemini",
        )
