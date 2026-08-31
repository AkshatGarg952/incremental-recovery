"""Integration test for the batch harness (BUILD.md tasks 8.9-8.12): a small
hand-crafted batch run end-to-end through classify -> propose -> envelope ->
execute against FakeProvider, checking suppression, exceptions, model-use,
and report rendering all come out coherent.
"""

import json
from datetime import UTC, datetime

from src.agent.policy import load_economics_config
from src.eval.harness import run_batch
from src.eval.metering import MeteringChatClient
from src.eval.report import build_batch_report, render_console, render_json
from src.executor.clock import SimulatedClock
from src.executor.ledger import Ledger
from src.llm.cost import TokenAccountant, load_pricing
from src.llm.fake import FakeProvider
from src.simulator.schemas import FailureContext, LatentOutcome, PaymentFailure

_START = datetime(2026, 8, 29, 6, 30, tzinfo=UTC)
_CLASSIFY_MODEL = "gemini-2.5-flash-lite"
_POLICY_MODEL = "openai/gpt-oss-120b"


def _failure(failure_id: str, decline_code: str, **overrides) -> PaymentFailure:
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
        decline_code=decline_code,
        decline_message_raw="generic message",
        failed_at=_START,
        attempt_number=1,
        context=context,
    )
    defaults.update(overrides)
    return PaymentFailure(**defaults)


def _latent(would_self_recover: bool = False) -> LatentOutcome:
    return LatentOutcome(
        would_self_recover=would_self_recover,
        self_recovery_delay_hours=200.0,
        responds_to_retry=False,
        responds_to_message=False,
        fatigue_threshold=3,
        fatigue_decay_per_contact=0.5,
        churn_prob_per_excess_contact=0.1,
        ltv_paise=100_000,
    )


_CLASSIFY_RESPONSE = '{"recovery_class": "action", "confidence": 0.9, "rationale": "r"}'
_POLICY_RESPONSE = json.dumps(
    {
        "failure_id": "PLACEHOLDER",
        "recovery_class": "action",
        "should_retry": True,
        "should_contact": True,
        "retry_schedule": [{"delay_hours": 2, "route_hint": "same", "reason": "r"}],
        "customer_message": {
            "channel": "sms",
            "template_id": "action_required_sms",
            "variables": {"amount": "INR 500.00", "merchant_name": "Acme"},
            "send_after_hours": 1,
        },
        "predicted_uplift": 0.4,
        "rationale": "r",
        "confidence": 0.8,
    }
)


def _build_batch():
    failures = [
        _failure("agent_1", "DO_NOT_HONOR"),  # ambiguous -> classify calls the LLM
        _failure("agent_2", "CARD_EXPIRED"),  # clean -> rule prior, no classify call
        _failure("baseline_1", "CARD_EXPIRED"),
        _failure("baseline_2", "MANDATE_REVOKED"),
        _failure("holdout_1", "CARD_EXPIRED"),
        _failure("holdout_2", "ISSUER_DOWN"),
    ]
    assignment = {
        "agent_1": "agent",
        "agent_2": "agent",
        "baseline_1": "baseline",
        "baseline_2": "baseline",
        "holdout_1": "holdout",
        "holdout_2": "holdout",
    }
    latent_outcomes = {f.failure_id: _latent() for f in failures}
    return failures, assignment, latent_outcomes


def test_run_batch_makes_exactly_the_expected_llm_calls_and_produces_records():
    failures, assignment, latent_outcomes = _build_batch()
    # Order matches processing order: agent_1 classify, agent_1 propose, agent_2 propose.
    responses = [
        _CLASSIFY_RESPONSE,
        _POLICY_RESPONSE.replace("PLACEHOLDER", "agent_1"),
        _POLICY_RESPONSE.replace("PLACEHOLDER", "agent_2"),
    ]
    provider = FakeProvider(responses)
    ledger = Ledger(":memory:")
    clock = SimulatedClock(_START)
    economics = load_economics_config()

    result = run_batch(
        failures,
        assignment,
        latent_outcomes,
        provider,
        _CLASSIFY_MODEL,
        _POLICY_MODEL,
        ledger,
        clock,
        seed=1,
        economics_config=economics,
    )

    assert len(provider.calls) == 3
    assert len(result.store.records()) == 6
    assert {r.arm for r in result.store.records()} == {"agent", "baseline", "holdout"}
    # agent_1 got a real contact per its scripted proposal.
    agent_1_record = next(r for r in result.store.records() if r.failure_id == "agent_1")
    assert agent_1_record.contact_cost_paise > 0


def test_run_batch_records_a_classify_exception_for_low_confidence():
    failures, assignment, latent_outcomes = _build_batch()
    low_confidence = '{"recovery_class": "action", "confidence": 0.1, "rationale": "unsure"}'
    responses = [
        low_confidence,
        _POLICY_RESPONSE.replace("PLACEHOLDER", "agent_1"),
        _POLICY_RESPONSE.replace("PLACEHOLDER", "agent_2"),
    ]
    provider = FakeProvider(responses)
    ledger = Ledger(":memory:")
    clock = SimulatedClock(_START)
    economics = load_economics_config()

    result = run_batch(
        failures,
        assignment,
        latent_outcomes,
        provider,
        _CLASSIFY_MODEL,
        _POLICY_MODEL,
        ledger,
        clock,
        seed=1,
        economics_config=economics,
    )

    classify_exceptions = [e for e in result.exceptions if e.stage == "classify"]
    assert len(classify_exceptions) == 1
    assert classify_exceptions[0].failure_id == "agent_1"


def test_run_batch_falls_back_to_baseline_style_on_unparseable_policy_output():
    failures, assignment, latent_outcomes = _build_batch()
    # agent_1: classify (ambiguous) -> LLM, then 3 malformed propose attempts.
    # agent_2: classify is rule-based (clean code), then a normal propose call.
    responses = [
        _CLASSIFY_RESPONSE,
        "not json",
        "still not json",
        "nope",
        _POLICY_RESPONSE.replace("PLACEHOLDER", "agent_2"),
    ]
    provider = FakeProvider(responses)
    ledger = Ledger(":memory:")
    clock = SimulatedClock(_START)
    economics = load_economics_config()

    result = run_batch(
        failures[:2],  # just the two agent-arm failures
        assignment,
        latent_outcomes,
        provider,
        _CLASSIFY_MODEL,
        _POLICY_MODEL,
        ledger,
        clock,
        seed=1,
        economics_config=economics,
    )

    propose_exceptions = [e for e in result.exceptions if e.stage == "propose"]
    assert len(propose_exceptions) == 1
    assert propose_exceptions[0].failure_id == "agent_1"
    # fell back to baseline-style behaviour: retries but no contact
    agent_1_record = next(r for r in result.store.records() if r.failure_id == "agent_1")
    assert agent_1_record.retries_made > 0
    assert agent_1_record.contacts_made == 0


def test_metering_client_tracks_calls_and_cache_hits():
    failures, assignment, latent_outcomes = _build_batch()
    responses = [
        _CLASSIFY_RESPONSE,
        _POLICY_RESPONSE.replace("PLACEHOLDER", "agent_1"),
        _POLICY_RESPONSE.replace("PLACEHOLDER", "agent_2"),
    ]
    provider = FakeProvider(responses)
    pricing = load_pricing()
    accountant = TokenAccountant(pricing)
    metering = MeteringChatClient(provider, accountant)
    ledger = Ledger(":memory:")
    clock = SimulatedClock(_START)
    economics = load_economics_config()

    run_batch(
        failures,
        assignment,
        latent_outcomes,
        metering,
        _CLASSIFY_MODEL,
        _POLICY_MODEL,
        ledger,
        clock,
        seed=1,
        economics_config=economics,
    )

    assert metering.calls == 3
    assert metering.cache_hits == 0
    assert accountant.calls == 3


def test_build_batch_report_and_render_console_and_json():
    failures, assignment, latent_outcomes = _build_batch()
    responses = [
        _CLASSIFY_RESPONSE,
        _POLICY_RESPONSE.replace("PLACEHOLDER", "agent_1"),
        _POLICY_RESPONSE.replace("PLACEHOLDER", "agent_2"),
    ]
    provider = FakeProvider(responses)
    pricing = load_pricing()
    accountant = TokenAccountant(pricing)
    metering = MeteringChatClient(provider, accountant)
    ledger = Ledger(":memory:")
    clock = SimulatedClock(_START)
    economics = load_economics_config()

    result = run_batch(
        failures,
        assignment,
        latent_outcomes,
        metering,
        _CLASSIFY_MODEL,
        _POLICY_MODEL,
        ledger,
        clock,
        seed=1,
        economics_config=economics,
    )

    report = build_batch_report(result, latent_outcomes, metering, ambiguous_rate=1 / 6, seed=1)

    assert report.total_failures == 6
    assert report.lift.n_agent == 2
    assert report.model_use.llm_calls == 3

    console = render_console(report)
    assert "BATCH REPORT" in console
    assert "HEADLINE" in console
    assert "MONEY" in console

    payload = json.loads(render_json(report))
    assert payload["total_failures"] == 6
    assert "lift" in payload
