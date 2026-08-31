"""`HoldoutObserver` — records outcomes, takes no action at all.

BUILD.md task 7.7: the natural self-recovery rate, same ledger shape as the
other two arms (a single `stage="outcome"` row instead of `execute` rows,
since nothing was ever executed).
"""

from src.executor.clock import SimulatedClock
from src.executor.idempotency import idempotency_key
from src.executor.ledger import Ledger
from src.executor.outcomes import RECOVERY_HORIZON_HOURS, OutcomeResolver
from src.executor.result import ExecutionResult
from src.executor.schemas import LedgerEntry
from src.simulator.schemas import PaymentFailure


class HoldoutObserver:
    def __init__(self, ledger: Ledger, clock: SimulatedClock, resolver: OutcomeResolver) -> None:
        self._ledger = ledger
        self._clock = clock
        self._resolver = resolver

    def execute(self, failure: PaymentFailure) -> ExecutionResult:
        recovered = self._resolver.recovered_by(failure.failure_id, RECOVERY_HORIZON_HOURS, 0, 0)

        key = idempotency_key(failure.failure_id, "outcome", 1)
        if not self._ledger.has_entry(key):
            self._ledger.append(
                LedgerEntry(
                    entry_id=key,
                    failure_id=failure.failure_id,
                    ts=self._clock.now(),
                    arm="holdout",
                    stage="outcome",
                )
            )

        return ExecutionResult(
            failure_id=failure.failure_id,
            arm="holdout",
            recovered=recovered,
            recovered_at_hours=RECOVERY_HORIZON_HOURS if recovered else None,
            retries_made=0,
            contacts_made=0,
        )
