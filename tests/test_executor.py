"""Offline tests for the three arm executors (BUILD.md tasks 7.3-7.8)."""

from datetime import UTC, datetime, timedelta

from src.envelope.schemas import MessageSpec, ProposedPolicy, RetryStep
from src.executor.agent_executor import AgentExecutor
from src.executor.baseline_executor import BaselineExecutor
from src.executor.clock import SimulatedClock
from src.executor.holdout_observer import HoldoutObserver
from src.executor.idempotency import idempotency_key
from src.executor.ledger import Ledger
from src.executor.outcomes import RECOVERY_HORIZON_HOURS
from src.simulator.schemas import FailureContext, PaymentFailure, RecoveryClass

_START = datetime(2026, 8, 29, 6, 30, tzinfo=UTC)


class FakeResolver:
    """Deterministic test double standing in for Phase 8's latent-backed
    resolver — recovers once a configured threshold is crossed."""

    def __init__(
        self,
        recovers_after_retries: int | None = None,
        recovers_after_contacts: int | None = None,
        recovers_at_hours: float | None = None,
    ) -> None:
        self.calls: list[tuple[str, float, int, int]] = []
        self._recovers_after_retries = recovers_after_retries
        self._recovers_after_contacts = recovers_after_contacts
        self._recovers_at_hours = recovers_at_hours

    def recovered_by(
        self, failure_id: str, at_hours: float, retries_attempted: int, contacts_made: int
    ) -> bool:
        self.calls.append((failure_id, at_hours, retries_attempted, contacts_made))
        retry_threshold = self._recovers_after_retries
        if retry_threshold is not None and retries_attempted >= retry_threshold:
            return True
        contact_threshold = self._recovers_after_contacts
        if contact_threshold is not None and contacts_made >= contact_threshold:
            return True
        return self._recovers_at_hours is not None and at_hours >= self._recovers_at_hours


def _failure(**overrides) -> PaymentFailure:
    context_defaults = dict(
        source="subscription",
        customer_tenure_days=200,
        prior_failures_90d=0,
        prior_successful_payments=10,
        contacts_last_7d=0,
        subscription_mrr_paise=50_000,
        invoice_due_date=None,
        consent_channels={"sms", "email"},
    )
    context_defaults.update(overrides.pop("context", {}))
    context = FailureContext(**context_defaults)

    defaults = dict(
        failure_id="fail_0000001",
        merchant_id="merchant_demo_01",
        customer_ref="cust_test",
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


def _proposal(**overrides) -> ProposedPolicy:
    defaults = dict(
        failure_id="fail_0000001",
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
    defaults.update(overrides)
    return ProposedPolicy(**defaults)


# ---- idempotency key (7.3) ---------------------------------------------------


def test_idempotency_key_is_scoped_by_kind_and_index():
    assert idempotency_key("f1", "retry", 1) != idempotency_key("f1", "contact", 1)
    assert idempotency_key("f1", "retry", 1) != idempotency_key("f1", "retry", 2)
    assert idempotency_key("f1", "retry", 1) == idempotency_key("f1", "retry", 1)


# ---- simulated clock (7.4) ----------------------------------------------------


def test_simulated_clock_only_advances_when_told():
    clock = SimulatedClock(_START)
    assert clock.now() == _START
    clock.advance_hours(168)
    assert clock.now() == _START + timedelta(hours=168)


# ---- AgentExecutor (7.5, with 7.3 and 7.8) -----------------------------------


def test_agent_executor_runs_the_full_timeline_when_never_recovered(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    clock = SimulatedClock(_START)
    resolver = FakeResolver()  # never recovers
    executor = AgentExecutor(ledger, clock, resolver)
    failure = _failure()
    approved = _proposal()

    result = executor.execute(failure, approved)

    assert result.retries_made == 2
    assert result.contacts_made == 1
    assert result.recovered is False
    assert ledger.count_by_stage("execute", arm="agent") == 3  # 2 retries + 1 contact


def test_agent_executor_stops_acting_once_recovered(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    clock = SimulatedClock(_START)
    resolver = FakeResolver(recovers_after_retries=0)  # recovered before any action
    executor = AgentExecutor(ledger, clock, resolver)
    failure = _failure()
    approved = _proposal()

    result = executor.execute(failure, approved)

    assert result.recovered is True
    assert result.retries_made == 0
    assert result.contacts_made == 0
    assert ledger.count_by_stage("execute") == 0


def test_agent_executor_checks_the_horizon_when_never_recovered_during_the_timeline(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    clock = SimulatedClock(_START)
    resolver = FakeResolver(recovers_at_hours=RECOVERY_HORIZON_HOURS)
    executor = AgentExecutor(ledger, clock, resolver)
    failure = _failure()
    approved = _proposal()

    result = executor.execute(failure, approved)

    assert result.recovered is True
    assert result.recovered_at_hours == RECOVERY_HORIZON_HOURS
    # both retries and the contact still ran before the horizon check
    assert result.retries_made == 2
    assert result.contacts_made == 1


def test_agent_executor_feeds_contact_counts_to_the_resolver(tmp_path):
    """BUILD.md task 7.8 — contact accounting must reach the resolver so the
    fatigue model on its side of the boundary sees an accurate count."""
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    clock = SimulatedClock(_START)
    resolver = FakeResolver()
    executor = AgentExecutor(ledger, clock, resolver)
    failure = _failure()
    approved = _proposal()

    executor.execute(failure, approved)

    contacts_seen = [call[3] for call in resolver.calls]
    # contacts_made passed to the resolver must never decrease, and must
    # reach 1 by the end (the message is the last timeline event here).
    assert contacts_seen == sorted(contacts_seen)
    assert contacts_seen[-1] == 1


def test_agent_executor_replay_is_idempotent(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    clock = SimulatedClock(_START)
    resolver = FakeResolver()
    executor = AgentExecutor(ledger, clock, resolver)
    failure = _failure()
    approved = _proposal()

    executor.execute(failure, approved)
    first_count = ledger.count_by_stage("execute")

    executor.execute(failure, approved)
    second_count = ledger.count_by_stage("execute")

    assert first_count == second_count == 3


# ---- BaselineExecutor (7.6) ---------------------------------------------------


def test_baseline_executor_never_contacts_and_halts_after_three_attempts(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    clock = SimulatedClock(_START)
    resolver = FakeResolver()  # never recovers
    executor = BaselineExecutor(ledger, clock, resolver)
    failure = _failure()

    result = executor.execute(failure)

    assert result.retries_made == 3
    assert result.contacts_made == 0
    assert ledger.count_by_stage("execute", arm="baseline") == 3
    approved_kinds = {
        entry.approved["kind"] for entry in ledger.entries_for_failure(failure.failure_id)
    }
    assert approved_kinds == {"retry"}


def test_baseline_executor_stops_early_if_recovered(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    # Recovery is checked before each attempt using the count already made,
    # so recovering after the 1st retry (at hour 24) is only observed at the
    # next check point, hour 48 — before a 2nd retry is ever written.
    resolver = FakeResolver(recovers_after_retries=1)
    executor = BaselineExecutor(ledger, SimulatedClock(_START), resolver)

    result = executor.execute(_failure())

    assert result.recovered is True
    assert result.retries_made == 1
    assert result.recovered_at_hours == 48.0


# ---- HoldoutObserver (7.7) -----------------------------------------------------


def test_holdout_observer_takes_no_action_and_records_the_outcome(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    clock = SimulatedClock(_START)
    resolver = FakeResolver(recovers_at_hours=RECOVERY_HORIZON_HOURS)
    observer = HoldoutObserver(ledger, clock, resolver)
    failure = _failure()

    result = observer.execute(failure)

    assert result.recovered is True
    assert result.retries_made == 0
    assert result.contacts_made == 0
    assert ledger.count_by_stage("execute") == 0
    assert ledger.count_by_stage("outcome", arm="holdout") == 1


def test_holdout_observer_replay_does_not_duplicate_the_outcome_entry(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    clock = SimulatedClock(_START)
    resolver = FakeResolver()
    observer = HoldoutObserver(ledger, clock, resolver)
    failure = _failure()

    observer.execute(failure)
    observer.execute(failure)

    assert ledger.count_by_stage("outcome", arm="holdout") == 1
