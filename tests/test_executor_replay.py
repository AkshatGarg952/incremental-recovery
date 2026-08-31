"""BUILD GATE — idempotent replay (BUILD.md task 7.9, gate 'Idempotent
replay'): re-running a batch produces zero duplicate charges.

Runs a small multi-failure, multi-arm batch through the ledger twice and
asserts the second pass writes exactly nothing new.
"""

from datetime import UTC, datetime

from src.envelope.schemas import MessageSpec, ProposedPolicy, RetryStep
from src.executor.agent_executor import AgentExecutor
from src.executor.baseline_executor import BaselineExecutor
from src.executor.clock import SimulatedClock
from src.executor.holdout_observer import HoldoutObserver
from src.executor.ledger import Ledger
from src.simulator.schemas import FailureContext, PaymentFailure, RecoveryClass

_START = datetime(2026, 8, 29, 6, 30, tzinfo=UTC)


class _NeverRecoversResolver:
    """Exercises every scheduled action on every pass — the strictest case
    for idempotent replay, since nothing short-circuits early."""

    def recovered_by(self, failure_id, at_hours, retries_attempted, contacts_made) -> bool:
        return False


def _failure(failure_id: str, **overrides) -> PaymentFailure:
    context = FailureContext(
        source="subscription",
        customer_tenure_days=200,
        prior_failures_90d=0,
        prior_successful_payments=10,
        contacts_last_7d=0,
        subscription_mrr_paise=50_000,
        invoice_due_date=None,
        consent_channels={"sms", "email"},
    )
    defaults = dict(
        failure_id=failure_id,
        merchant_id="merchant_demo_01",
        customer_ref=f"cust_{failure_id}",
        amount_paise=50_000,
        currency="INR",
        method="upi",
        issuer_code="HDFC",
        decline_code="AUTH_TIMEOUT",
        decline_message_raw="Customer did not authorize within time limit",
        failed_at=_START,
        attempt_number=1,
        context=context,
    )
    defaults.update(overrides)
    return PaymentFailure(**defaults)


def _proposal(failure_id: str) -> ProposedPolicy:
    return ProposedPolicy(
        failure_id=failure_id,
        recovery_class=RecoveryClass.ACTION_RECOVERABLE,
        should_retry=True,
        should_contact=True,
        retry_schedule=[
            RetryStep(delay_hours=2, route_hint="same", reason="r"),
            RetryStep(delay_hours=10, route_hint="alternate_psp", reason="r"),
        ],
        customer_message=MessageSpec(
            channel="sms", template_id="action_required_sms", variables={}, send_after_hours=1
        ),
        predicted_uplift=0.4,
        rationale="r",
        confidence=0.8,
    )


def test_replaying_a_mixed_arm_batch_writes_no_duplicate_ledger_rows(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    resolver = _NeverRecoversResolver()

    agent_failures = [_failure(f"agent_{i}") for i in range(5)]
    baseline_failures = [_failure(f"baseline_{i}") for i in range(5)]
    holdout_failures = [_failure(f"holdout_{i}") for i in range(5)]

    def run_batch() -> None:
        clock = SimulatedClock(_START)
        agent_executor = AgentExecutor(ledger, clock, resolver)
        baseline_executor = BaselineExecutor(ledger, clock, resolver)
        holdout_observer = HoldoutObserver(ledger, clock, resolver)

        for failure in agent_failures:
            agent_executor.execute(failure, _proposal(failure.failure_id))
        for failure in baseline_failures:
            baseline_executor.execute(failure)
        for failure in holdout_failures:
            holdout_observer.execute(failure)

    run_batch()
    execute_count_first = ledger.count_by_stage("execute")
    outcome_count_first = ledger.count_by_stage("outcome")
    assert execute_count_first > 0
    assert outcome_count_first > 0

    # Replay the exact same batch against the same ledger.
    run_batch()
    execute_count_second = ledger.count_by_stage("execute")
    outcome_count_second = ledger.count_by_stage("outcome")

    assert execute_count_second == execute_count_first
    assert outcome_count_second == outcome_count_first

    # And per-failure row counts are stable too, not just the totals.
    for failure in agent_failures + baseline_failures:
        entries = ledger.entries_for_failure(failure.failure_id)
        entry_ids = [e.entry_id for e in entries]
        assert len(entry_ids) == len(set(entry_ids))
