"""Per-rule tests plus the adversarial fuzz gate — BUILD.md task 3.10.

BUILD GATE (envelope escapes): zero adversarial proposals survive the
envelope. Every proposal below tries to break one rule; each assertion
checks that the *approved* output no longer carries the violating content.
"""

from datetime import UTC, datetime, timedelta

from src.envelope.engine import Envelope
from src.envelope.rules import (
    AmountBoundRule,
    ChannelConsentRule,
    ContactFrequencyRule,
    DeadNoChaseRule,
    EnvelopeContext,
    FatigueRule,
    QuietHoursRule,
    RetryCapRule,
    ScheduleSanityRule,
    SchemaValidRule,
    TemplateAllowlistRule,
    Verdict,
)
from src.envelope.schemas import MessageSpec, ProposedPolicy, RetryStep
from src.simulator.schemas import FailureContext, PaymentFailure, RecoveryClass

_TEMPLATE_IDS = frozenset({"retry_reminder_sms", "action_required_sms"})
_NOON_UTC = datetime(2026, 8, 29, 6, 30, tzinfo=UTC)  # 12:00 IST — well inside allowed hours


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
        failed_at=_NOON_UTC,
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
        retry_schedule=[RetryStep(delay_hours=2, route_hint="same", reason="retry once")],
        customer_message=MessageSpec(
            channel="sms",
            template_id="action_required_sms",
            variables={"amount": "INR 500.00", "merchant_name": "Acme"},
            send_after_hours=1,
        ),
        predicted_uplift=0.2,
        rationale="test proposal",
        confidence=0.8,
    )
    defaults.update(overrides)
    return ProposedPolicy(**defaults)


def _context(**overrides) -> EnvelopeContext:
    defaults = dict(
        failure=_failure(),
        now=_NOON_UTC,
        attempts_used=0,
        contacts_used_7d=0,
        consent_channels=frozenset({"sms", "email"}),
    )
    defaults.update(overrides)
    return EnvelopeContext(**defaults)


def _default_envelope() -> Envelope:
    return Envelope(
        rules=[
            RetryCapRule(max_attempts_per_mandate=4),
            ScheduleSanityRule(max_steps=4, max_horizon_hours=168, require_monotonic=True),
            QuietHoursRule(start_ist="21:00", end_ist="09:00"),
            ContactFrequencyRule(max_contacts_per_7d=3),
            ChannelConsentRule(),
            TemplateAllowlistRule(template_ids=_TEMPLATE_IDS),
            AmountBoundRule(),
            DeadNoChaseRule(),
            FatigueRule(block_after_contacts_and_failures=5),
        ]
    )


# ---- one test per rule ID ---------------------------------------------------


def test_env_retry_cap_truncates_schedule_beyond_remaining_attempts():
    rule = RetryCapRule(max_attempts_per_mandate=4)
    proposal = _proposal(
        retry_schedule=[
            RetryStep(delay_hours=h, route_hint="same", reason="r") for h in [1, 2, 3, 4, 5]
        ]
    )
    context = _context(attempts_used=2)

    clamped, outcome = rule.apply(proposal, context)

    assert outcome.rule_id == "ENV_RETRY_CAP"
    assert outcome.verdict == Verdict.CLAMPED
    assert len(clamped.retry_schedule) == 2


def test_env_retry_cap_blocks_when_cap_already_exhausted():
    rule = RetryCapRule(max_attempts_per_mandate=4)
    proposal = _proposal()
    context = _context(attempts_used=4)

    clamped, outcome = rule.apply(proposal, context)

    assert outcome.verdict == Verdict.BLOCKED
    assert clamped.should_retry is False
    assert clamped.retry_schedule == []


def test_env_schedule_sanity_fixes_negative_delays_and_non_monotonic_steps():
    rule = ScheduleSanityRule(max_steps=4, max_horizon_hours=168, require_monotonic=True)
    proposal = _proposal(
        retry_schedule=[
            RetryStep(delay_hours=-5, route_hint="same", reason="r"),
            RetryStep(delay_hours=-5, route_hint="same", reason="r"),
            RetryStep(delay_hours=1, route_hint="same", reason="r"),
        ]
    )
    context = _context()

    clamped, outcome = rule.apply(proposal, context)

    assert outcome.verdict == Verdict.CLAMPED
    delays = [s.delay_hours for s in clamped.retry_schedule]
    assert all(d >= 0 for d in delays)
    assert delays == sorted(set(delays)) and len(set(delays)) == len(delays)


def test_env_schedule_sanity_truncates_oversized_schedules():
    rule = ScheduleSanityRule(max_steps=4, max_horizon_hours=168, require_monotonic=True)
    proposal = _proposal(
        retry_schedule=[
            RetryStep(delay_hours=h, route_hint="same", reason="r") for h in range(1, 41)
        ]
    )
    context = _context()

    clamped, outcome = rule.apply(proposal, context)

    assert outcome.verdict == Verdict.CLAMPED
    assert len(clamped.retry_schedule) <= 4
    assert all(s.delay_hours <= 168 for s in clamped.retry_schedule)


def test_env_quiet_hours_shifts_send_time_out_of_the_blocked_window():
    rule = QuietHoursRule(start_ist="21:00", end_ist="09:00")
    # send_after_hours=0 means "now" (noon IST) is fine; push into the night instead.
    proposal = _proposal(
        customer_message=MessageSpec(
            channel="sms",
            template_id="action_required_sms",
            variables={},
            send_after_hours=11,  # noon + 11h = 23:00 IST -> inside quiet hours
        )
    )
    context = _context(now=_NOON_UTC)

    clamped, outcome = rule.apply(proposal, context)

    assert outcome.verdict == Verdict.CLAMPED
    send_at = context.now + timedelta(hours=clamped.customer_message.send_after_hours)
    ist_hour = (send_at + timedelta(hours=5, minutes=30)).hour
    assert 9 <= ist_hour < 21


def test_env_contact_freq_blocks_once_the_7d_cap_is_reached():
    rule = ContactFrequencyRule(max_contacts_per_7d=3)
    proposal = _proposal()
    context = _context(contacts_used_7d=3)

    clamped, outcome = rule.apply(proposal, context)

    assert outcome.verdict == Verdict.BLOCKED
    assert clamped.should_contact is False
    assert clamped.customer_message is None


def test_env_channel_consent_blocks_a_non_consented_channel():
    rule = ChannelConsentRule()
    proposal = _proposal(
        customer_message=MessageSpec(
            channel="whatsapp",
            template_id="action_required_whatsapp",
            variables={},
            send_after_hours=1,
        )
    )
    context = _context(consent_channels=frozenset({"sms", "email"}))

    clamped, outcome = rule.apply(proposal, context)

    assert outcome.verdict == Verdict.BLOCKED
    assert clamped.should_contact is False
    assert clamped.customer_message is None


def test_env_template_allowlist_blocks_an_invented_template_id():
    rule = TemplateAllowlistRule(template_ids=_TEMPLATE_IDS)
    proposal = _proposal(
        customer_message=MessageSpec(
            channel="sms", template_id="not_a_real_template", variables={}, send_after_hours=1
        )
    )
    context = _context()

    clamped, outcome = rule.apply(proposal, context)

    assert outcome.verdict == Verdict.BLOCKED
    assert clamped.should_contact is False
    assert clamped.customer_message is None


def test_env_amount_bound_overwrites_a_tampered_amount():
    rule = AmountBoundRule()
    proposal = _proposal(
        customer_message=MessageSpec(
            channel="sms",
            template_id="action_required_sms",
            variables={"amount": "INR 1.00"},  # real amount is INR 500.00
            send_after_hours=1,
        )
    )
    context = _context(failure=_failure(amount_paise=50_000))

    clamped, outcome = rule.apply(proposal, context)

    assert outcome.verdict == Verdict.CLAMPED
    assert clamped.customer_message.variables["amount"] == "INR 500.00"


def test_env_dead_no_chase_blocks_all_intervention_for_dead_class():
    rule = DeadNoChaseRule()
    proposal = _proposal(recovery_class=RecoveryClass.DEAD)
    context = _context()

    clamped, outcome = rule.apply(proposal, context)

    assert outcome.verdict == Verdict.BLOCKED
    assert clamped.should_retry is False
    assert clamped.should_contact is False
    assert clamped.retry_schedule == []
    assert clamped.customer_message is None


def test_env_fatigue_blocks_contact_past_the_bound():
    rule = FatigueRule(block_after_contacts_and_failures=5)
    proposal = _proposal()
    context = _context(failure=_failure(context={"prior_failures_90d": 3}), contacts_used_7d=3)

    clamped, outcome = rule.apply(proposal, context)

    assert outcome.verdict == Verdict.BLOCKED
    assert clamped.should_contact is False


def test_env_schema_valid_produces_a_blocked_outcome_for_unparseable_output():
    outcome = SchemaValidRule.blocked_outcome("could not parse after 3 attempts")

    assert outcome.rule_id == "ENV_SCHEMA_VALID"
    assert outcome.verdict == Verdict.BLOCKED


# ---- engine: clamp-then-recheck ---------------------------------------------


def test_engine_recheck_catches_a_breach_created_by_an_earlier_clamp():
    """A quiet-hours clamp must not silently create a contact-frequency breach."""
    envelope = Envelope(
        rules=[
            QuietHoursRule(start_ist="21:00", end_ist="09:00"),
            ContactFrequencyRule(max_contacts_per_7d=3),
        ]
    )
    proposal = _proposal(
        customer_message=MessageSpec(
            channel="sms", template_id="action_required_sms", variables={}, send_after_hours=11
        )
    )
    # Already at the cap — the quiet-hours clamp alone wouldn't catch this if
    # the engine only ran each rule once instead of rechecking to a fixed point.
    context = _context(contacts_used_7d=3)

    result = envelope.evaluate(proposal, context)

    assert result.verdict == Verdict.BLOCKED
    assert result.approved.should_contact is False
    assert any(o.rule_id == "ENV_CONTACT_FREQ" for o in result.rules_fired)


# ---- adversarial fuzz batch: zero adversarial proposals survive ------------


def _adversarial_proposals() -> list[ProposedPolicy]:
    return [
        # Invented template_id.
        _proposal(
            customer_message=MessageSpec(
                channel="sms", template_id="totally_made_up", variables={}, send_after_hours=1
            )
        ),
        # Negative delays.
        _proposal(
            retry_schedule=[
                RetryStep(delay_hours=-100, route_hint="same", reason="r"),
                RetryStep(delay_hours=-1, route_hint="same", reason="r"),
            ]
        ),
        # 40-step schedule.
        _proposal(
            retry_schedule=[
                RetryStep(delay_hours=h, route_hint="same", reason="r") for h in range(1, 41)
            ]
        ),
        # Amount tampering.
        _proposal(
            customer_message=MessageSpec(
                channel="sms",
                template_id="action_required_sms",
                variables={"amount": "INR 0.01"},
                send_after_hours=1,
            )
        ),
        # Non-consented channel.
        _proposal(
            customer_message=MessageSpec(
                channel="whatsapp",
                template_id="action_required_whatsapp",
                variables={},
                send_after_hours=1,
            )
        ),
        # Retry proposed for a DEAD failure.
        _proposal(recovery_class=RecoveryClass.DEAD),
        # Contact proposed while already fatigued.
        _proposal(),
        # Message scheduled for the middle of the night.
        _proposal(
            customer_message=MessageSpec(
                channel="sms", template_id="action_required_sms", variables={}, send_after_hours=15
            )
        ),
        # Retry schedule already over the mandate cap.
        _proposal(
            retry_schedule=[
                RetryStep(delay_hours=h, route_hint="same", reason="r") for h in [1, 2, 3, 4, 5]
            ]
        ),
    ]


def test_adversarial_fuzz_batch_survives_nothing_bad():
    envelope = _default_envelope()
    base_context = _context()
    fatigued_context = _context(
        failure=_failure(context={"prior_failures_90d": 5}), contacts_used_7d=5
    )
    exhausted_context = _context(attempts_used=4)

    contexts = [
        base_context,
        base_context,
        base_context,
        base_context,
        base_context,
        base_context,
        fatigued_context,
        base_context,
        exhausted_context,
    ]

    for proposal, context in zip(_adversarial_proposals(), contexts, strict=True):
        result = envelope.evaluate(proposal, context)
        approved = result.approved

        assert result.verdict != Verdict.PASS

        if approved.customer_message is not None:
            assert approved.customer_message.template_id in _TEMPLATE_IDS
            assert approved.customer_message.channel in context.consent_channels
            if "amount" in approved.customer_message.variables:
                assert approved.customer_message.variables["amount"] == "INR 500.00"

        delays = [s.delay_hours for s in approved.retry_schedule]
        assert all(0 <= d <= 168 for d in delays)
        assert len(delays) <= 4
        assert delays == sorted(set(delays))

        if approved.recovery_class == RecoveryClass.DEAD:
            assert approved.should_retry is False
            assert approved.should_contact is False
