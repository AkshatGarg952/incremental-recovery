"""Shared eval-domain schemas — BUILD.md R2, R3.

`LedgerEntry` is defined here (not in `src/executor`) because assignment
(Phase 4) needs to log a `stage="assign"` entry before an executor exists at
all. Phase 7 adds the append-only SQLite table this schema is written to;
the shape doesn't change between here and there.
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
