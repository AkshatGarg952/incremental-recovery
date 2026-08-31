"""Outcome store — BUILD.md task 8.1.

Joins each failure's realized `ExecutionResult` with its arm, recovery
class, and the contact cost incurred, ready for every report section that
follows. Ground truth (`would_self_recover`) rides along only for the
estimator-validation check (task 8.5) — nothing downstream of this record
is allowed to condition a *decision* on it, only a validation report.
"""

from dataclasses import dataclass, field

from src.eval.schemas import Arm
from src.executor.result import ExecutionResult
from src.simulator.schemas import PaymentFailure, RecoveryClass


@dataclass
class OutcomeRecord:
    failure_id: str
    arm: Arm
    recovery_class: RecoveryClass | None  # None if classification fell to the exception list
    recovered: bool
    recovered_at_hours: float | None
    retries_made: int
    contacts_made: int
    amount_paise: int
    contact_cost_paise: int
    would_self_recover: bool  # ground truth — estimator validation only


def build_outcome_record(
    failure: PaymentFailure,
    result: ExecutionResult,
    recovery_class: RecoveryClass | None,
    would_self_recover: bool,
    contact_cost_paise: int = 0,
) -> OutcomeRecord:
    return OutcomeRecord(
        failure_id=failure.failure_id,
        arm=result.arm,
        recovery_class=recovery_class,
        recovered=result.recovered,
        recovered_at_hours=result.recovered_at_hours,
        retries_made=result.retries_made,
        contacts_made=result.contacts_made,
        amount_paise=failure.amount_paise,
        contact_cost_paise=contact_cost_paise,
        would_self_recover=would_self_recover,
    )


@dataclass
class OutcomeStore:
    _records: list[OutcomeRecord] = field(default_factory=list)

    def add(self, record: OutcomeRecord) -> None:
        self._records.append(record)

    def records(self) -> list[OutcomeRecord]:
        return list(self._records)

    def by_arm(self, arm: Arm) -> list[OutcomeRecord]:
        return [r for r in self._records if r.arm == arm]
