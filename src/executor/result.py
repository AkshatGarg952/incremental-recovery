"""Shared result shape across all three arm executors."""

from dataclasses import dataclass

from src.eval.schemas import Arm


@dataclass
class ExecutionResult:
    failure_id: str
    arm: Arm
    recovered: bool
    recovered_at_hours: float | None
    retries_made: int
    contacts_made: int
