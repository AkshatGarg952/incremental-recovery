"""The policy agent's structured output — BUILD.md R3.

The envelope validates instances of this schema; the LLM policy agent
(Phase 6) is the thing that produces them. `template_id` is picked from a
fixed catalogue — the model never authors customer-facing copy at runtime.
"""

from typing import Literal

from pydantic import BaseModel

from src.simulator.schemas import RecoveryClass


class RetryStep(BaseModel):
    delay_hours: int
    route_hint: Literal["same", "alternate_psp", "alternate_method"]
    reason: str


class MessageSpec(BaseModel):
    channel: Literal["sms", "email", "whatsapp", "in_app"]
    template_id: str
    variables: dict[str, str]
    send_after_hours: int


class ProposedPolicy(BaseModel):
    failure_id: str
    recovery_class: RecoveryClass
    should_retry: bool
    should_contact: bool
    retry_schedule: list[RetryStep]
    customer_message: MessageSpec | None
    predicted_uplift: float
    rationale: str
    confidence: float
