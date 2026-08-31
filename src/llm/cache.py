"""Persistent SQLite response cache, keyed on `(role, provider, model, prompt_version,
sha256(payload))`.

Wraps any `ChatClient` so an identical request never hits the network twice —
the overnight batch and a demo re-run rely on this to make retries nearly free.
"""

import hashlib
import json
import sqlite3
from pathlib import Path

from src.llm.client import ChatClient, ChatRequest, ChatResponse, Usage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS response_cache (
    cache_key TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    content TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _payload_sha256(request: ChatRequest) -> str:
    payload = request.model_dump(mode="json")
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _cache_key(role: str, provider: str, model: str, prompt_version: str, payload_hash: str) -> str:
    return "|".join([role, provider, model, prompt_version, payload_hash])


class ResponseCache:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def get(
        self, role: str, provider: str, request: ChatRequest, prompt_version: str
    ) -> ChatResponse | None:
        payload_hash = _payload_sha256(request)
        key = _cache_key(role, provider, request.model, prompt_version, payload_hash)
        row = self._conn.execute(
            "SELECT content, prompt_tokens, completion_tokens FROM response_cache "
            "WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        content, prompt_tokens, completion_tokens = row
        return ChatResponse(
            content=content,
            usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
            model=request.model,
            provider=provider,
        )

    def put(
        self,
        role: str,
        provider: str,
        request: ChatRequest,
        prompt_version: str,
        response: ChatResponse,
    ) -> None:
        payload_hash = _payload_sha256(request)
        key = _cache_key(role, provider, request.model, prompt_version, payload_hash)
        self._conn.execute(
            "INSERT OR REPLACE INTO response_cache "
            "(cache_key, role, provider, model, prompt_version, payload_sha256, "
            "content, prompt_tokens, completion_tokens) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                role,
                provider,
                request.model,
                prompt_version,
                payload_hash,
                response.content,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
            ),
        )
        self._conn.commit()

    def delete(self, role: str, provider: str, request: ChatRequest, prompt_version: str) -> bool:
        """Remove one cached response, if present — selective invalidation
        (BUILD.md task 9.2): only the entry for this exact request, nothing
        else in the cache is touched. Returns whether a row was deleted.
        """
        payload_hash = _payload_sha256(request)
        key = _cache_key(role, provider, request.model, prompt_version, payload_hash)
        cursor = self._conn.execute("DELETE FROM response_cache WHERE cache_key = ?", (key,))
        self._conn.commit()
        return cursor.rowcount > 0

    def close(self) -> None:
        self._conn.close()


class CachingChatClient(ChatClient):
    """Wraps a `ChatClient`; an identical `(role, provider, model, prompt_version,
    payload)` tuple is served from the cache instead of calling the wrapped client."""

    def __init__(
        self,
        client: ChatClient,
        cache: ResponseCache,
        role: str,
        provider: str,
        prompt_version: str,
    ) -> None:
        self._client = client
        self._cache = cache
        self._role = role
        self._provider = provider
        self._prompt_version = prompt_version
        self.last_cache_hit: bool = False

    def complete(self, request: ChatRequest) -> ChatResponse:
        cached = self._cache.get(self._role, self._provider, request, self._prompt_version)
        if cached is not None:
            self.last_cache_hit = True
            return cached
        self.last_cache_hit = False
        response = self._client.complete(request)
        self._cache.put(self._role, self._provider, request, self._prompt_version, response)
        return response
