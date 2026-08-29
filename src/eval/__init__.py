"""Evaluation: three-arm assignment, ledger schema, and (later) lift reporting."""

from src.eval.assignment import (
    ASSIGNMENT_SEED,
    DEFAULT_ALLOCATION,
    amount_band,
    assign_arms,
    build_assignment_ledger_entries,
    stratum_key,
)
from src.eval.schemas import Arm, LedgerEntry

__all__ = [
    "ASSIGNMENT_SEED",
    "DEFAULT_ALLOCATION",
    "Arm",
    "LedgerEntry",
    "amount_band",
    "assign_arms",
    "build_assignment_ledger_entries",
    "stratum_key",
]
