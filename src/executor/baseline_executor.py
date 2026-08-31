"""`BaselineExecutor` — the fixed schedule a merchant already runs.

BUILD.md task 7.6: T+24h / T+48h / T+72h, same route every time, never
messages, halts after the third attempt regardless of outcome. Same
idempotent write-before-act pattern as `AgentExecutor` (task 7.3/7.9) —
retries are numbered by fixed position, so a replay writes nothing new.
"""

from src.executor.clock import SimulatedClock
from src.executor.idempotency import idempotency_key
from src.executor.ledger import Ledger
from src.executor.outcomes import RECOVERY_HORIZON_HOURS, OutcomeResolver
from src.executor.result import ExecutionResult
from src.executor.schemas import LedgerEntry
from src.simulator.schemas import PaymentFailure

_SCHEDULE_HOURS = (24.0, 48.0, 72.0)


class BaselineExecutor:
    def __init__(self, ledger: Ledger, clock: SimulatedClock, resolver: OutcomeResolver) -> None:
        self._ledger = ledger
        self._clock = clock
        self._resolver = resolver

    def execute(self, failure: PaymentFailure) -> ExecutionResult:
        retries_attempted = 0
        recovered = False
        recovered_at_hours: float | None = None

        for index, hours in enumerate(_SCHEDULE_HOURS, start=1):
            if self._resolver.recovered_by(failure.failure_id, hours, retries_attempted, 0):
                recovered = True
                recovered_at_hours = hours
                break

            key = idempotency_key(failure.failure_id, "baseline_retry", index)
            if not self._ledger.has_entry(key):
                self._ledger.append(
                    LedgerEntry(
                        entry_id=key,
                        failure_id=failure.failure_id,
                        ts=self._clock.now(),
                        arm="baseline",
                        stage="execute",
                        approved={"kind": "retry", "delay_hours": hours, "route_hint": "same"},
                    )
                )
            retries_attempted += 1

        if not recovered:
            recovered = self._resolver.recovered_by(
                failure.failure_id, RECOVERY_HORIZON_HOURS, retries_attempted, 0
            )
            if recovered:
                recovered_at_hours = RECOVERY_HORIZON_HOURS

        return ExecutionResult(
            failure_id=failure.failure_id,
            arm="baseline",
            recovered=recovered,
            recovered_at_hours=recovered_at_hours,
            retries_made=retries_attempted,
            contacts_made=0,
        )
