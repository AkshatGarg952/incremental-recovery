"""`Arm` and `LedgerEntry` — BUILD.md R2, R3.

Live here (not in `src/eval`) because the executor package needs them and
must never depend on `src.eval` (whose `__init__` pulls in the harness,
which depends on the executor — a real cycle, not a style preference).
`src/eval/schemas.py` re-exports both for the modules that already import
from there; assignment (Phase 4) started that pattern before this package
existed, and there was no reason to churn every call site once it did.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Arm = Literal["agent", "baseline", "holdout"]


class LedgerEntry(BaseModel):
    entry_id: str
    failure_id: str
    ts: datetime
    arm: Arm
    stage: Literal["assign", "classify", "propose", "envelope", "execute", "outcome"]
    proposed: dict | None = None
    approved: dict | None = None
    envelope_verdict: Literal["pass", "clamped", "blocked"] | None = None
    envelope_rules_fired: list[str] = Field(default_factory=list)
    model_name: str | None = None
    provider: str | None = None
    prompt_version: str | None = None
    cache_hit: bool | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    shadow_cost_usd: float | None = None
