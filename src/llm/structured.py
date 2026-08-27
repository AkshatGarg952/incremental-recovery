"""Schema-validated structured output: parse the model's JSON against a Pydantic
schema with bounded retries, then hard fail.

Never a silent default — a proposal that cannot be made to parse must surface
as a raised error (and, upstream, an `ENV_SCHEMA_VALID` block), not a
fabricated fallback object.
"""

import json

from pydantic import BaseModel, ValidationError

from src.llm.client import ChatClient, ChatMessage, ChatRequest, ChatResponse

_RETRY_INSTRUCTION = (
    "Your previous response could not be parsed as valid JSON matching the "
    "required schema. Error: {error}\n\n"
    "Respond with ONLY the corrected JSON, matching the schema exactly. "
    "No prose, no markdown fences."
)


class StructuredParseError(RuntimeError):
    """Raised when the model's output still fails to validate after all retries."""

    def __init__(
        self, schema: type[BaseModel], attempts: int, last_error: str, last_content: str
    ) -> None:
        self.schema = schema
        self.attempts = attempts
        self.last_error = last_error
        self.last_content = last_content
        super().__init__(
            f"{schema.__name__}: failed to parse after {attempts} attempt(s): {last_error}"
        )


def _extract_json(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[len("json") :]
    return text.strip()


def parse_structured(
    client: ChatClient,
    request: ChatRequest,
    schema: type[BaseModel],
    max_retries: int = 2,
) -> BaseModel:
    """Call `client` with `request`, parsing the response against `schema`.

    On a parse or validation failure, appends a correction message to the
    conversation and retries up to `max_retries` times before raising
    `StructuredParseError`.
    """
    messages = list(request.messages)
    last_error = ""
    last_content = ""
    for _attempt in range(max_retries + 1):
        current_request = request.model_copy(update={"messages": messages})
        response: ChatResponse = client.complete(current_request)
        last_content = response.content
        try:
            payload = json.loads(_extract_json(response.content))
            return schema.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)
            messages = messages + [
                ChatMessage(role="assistant", content=response.content),
                ChatMessage(role="user", content=_RETRY_INSTRUCTION.format(error=last_error)),
            ]
    raise StructuredParseError(schema, max_retries + 1, last_error, last_content)
