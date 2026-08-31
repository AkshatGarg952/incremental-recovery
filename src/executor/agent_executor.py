"""`AgentExecutor` — retries and contacts per approved policy.

BUILD.md task 7.5, with idempotency + write-before-act (7.3) and contact
accounting fed to the outcome resolver (7.8) built directly into the loop.

The retry schedule and message from `approved` are fixed at proposal time,
so each timeline position gets a deterministic idempotency key — replaying
the same `approved` policy against the same ledger finds every key already
present and performs zero further writes or actions (BUILD.md task 7.9,
the idempotent-replay build gate).

Never imports `src.simulator.latent` — outcomes are resolved entirely
through the injected `OutcomeResolver`. See tests/test_no_label_leak.py.
"""

from src.envelope.schemas import ProposedPolicy
from src.executor.clock import SimulatedClock
from src.executor.idempotency import idempotency_key
from src.executor.ledger import Ledger
from src.executor.outcomes import RECOVERY_HORIZON_HOURS, OutcomeResolver
from src.executor.result import ExecutionResult
from src.executor.schemas import LedgerEntry
from src.simulator.schemas import PaymentFailure


def _build_timeline(approved: ProposedPolicy) -> list[tuple[float, str, object]]:
    timeline: list[tuple[float, str, object]] = []
    if approved.should_retry:
        for step in approved.retry_schedule:
            timeline.append((float(step.delay_hours), "retry", step))
    if approved.should_contact and approved.customer_message is not None:
        message = approved.customer_message
        timeline.append((float(message.send_after_hours), "contact", message))
    timeline.sort(key=lambda item: item[0])
    return timeline


class AgentExecutor:
    def __init__(self, ledger: Ledger, clock: SimulatedClock, resolver: OutcomeResolver) -> None:
        self._ledger = ledger
        self._clock = clock
        self._resolver = resolver

    def execute(
        self, failure: PaymentFailure, approved: ProposedPolicy, arm: str = "agent"
    ) -> ExecutionResult:
        timeline = _build_timeline(approved)
        retries_attempted = 0
        contacts_made = 0
        recovered = False
        recovered_at_hours: float | None = None
        retry_index = 0
        contact_index = 0

        for hours, kind, step in timeline:
            if self._resolver.recovered_by(
                failure.failure_id, hours, retries_attempted, contacts_made
            ):
                recovered = True
                recovered_at_hours = hours
                break

            if kind == "retry":
                retry_index += 1
                key = idempotency_key(failure.failure_id, "retry", retry_index)
                if not self._ledger.has_entry(key):
                    self._ledger.append(
                        LedgerEntry(
                            entry_id=key,
                            failure_id=failure.failure_id,
                            ts=self._clock.now(),
                            arm=arm,
                            stage="execute",
                            approved={
                                "kind": "retry",
                                "delay_hours": step.delay_hours,
                                "route_hint": step.route_hint,
                            },
                        )
                    )
                retries_attempted += 1
            else:
                contact_index += 1
                key = idempotency_key(failure.failure_id, "contact", contact_index)
                if not self._ledger.has_entry(key):
                    self._ledger.append(
                        LedgerEntry(
                            entry_id=key,
                            failure_id=failure.failure_id,
                            ts=self._clock.now(),
                            arm=arm,
                            stage="execute",
                            approved={
                                "kind": "contact",
                                "channel": step.channel,
                                "template_id": step.template_id,
                            },
                        )
                    )
                contacts_made += 1

        if not recovered:
            recovered = self._resolver.recovered_by(
                failure.failure_id, RECOVERY_HORIZON_HOURS, retries_attempted, contacts_made
            )
            if recovered:
                recovered_at_hours = RECOVERY_HORIZON_HOURS

        return ExecutionResult(
            failure_id=failure.failure_id,
            arm=arm,
            recovered=recovered,
            recovered_at_hours=recovered_at_hours,
            retries_made=retries_attempted,
            contacts_made=contacts_made,
        )
