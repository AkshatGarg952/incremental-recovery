"""Offline tests for the policy agent (BUILD.md tasks 6.1-6.7): valid,
malformed, and out-of-policy proposals, all against FakeProvider."""

from datetime import UTC, datetime
from pathlib import Path

from src.agent.policy import (
    apply_stopping_rules,
    build_uplift_log_entry,
    contact_is_worth_it,
    propose_policy,
    retry_is_worth_it,
)
from src.envelope.schemas import MessageSpec, ProposedPolicy, RetryStep
from src.llm.fake import FakeProvider
from src.simulator.schemas import FailureContext, PaymentFailure, RecoveryClass

_MODEL = "test-model"

_ECONOMICS = {
    "contact_cost_paise": {"sms": 20, "email": 2, "whatsapp": 35, "in_app": 1},
    "mandate_retry_cap": 4,
    "decline_rate_penalty_threshold": 0.15,
}

_VALID_PROPOSAL_JSON = """
{
  "failure_id": "fail_0000001",
  "recovery_class": "action",
  "should_retry": true,
  "should_contact": true,
  "retry_schedule": [{"delay_hours": 2, "route_hint": "same", "reason": "let it settle"}],
  "customer_message": {
    "channel": "sms",
    "template_id": "action_required_sms",
    "variables": {"amount": "INR 500.00", "merchant_name": "Acme"},
    "send_after_hours": 1
  },
  "predicted_uplift": 0.4,
  "rationale": "customer needs to act",
  "confidence": 0.8
}
"""


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
        failed_at=datetime(2026, 8, 29, 6, 30, tzinfo=UTC),
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
        retry_schedule=[RetryStep(delay_hours=2, route_hint="same", reason="r")],
        customer_message=MessageSpec(
            channel="sms",
            template_id="action_required_sms",
            variables={"amount": "INR 500.00", "merchant_name": "Acme"},
            send_after_hours=1,
        ),
        predicted_uplift=0.4,
        rationale="r",
        confidence=0.8,
    )
    defaults.update(overrides)
    return ProposedPolicy(**defaults)


# ---- prompt file -------------------------------------------------------------


def test_policy_prompt_has_template_catalogue_schema_and_a_do_not_intervene_example():
    text = Path("prompts/policy.v1.md").read_text(encoding="utf-8").lower()

    assert "action_required_sms" in text
    assert "predicted_uplift" in text
    assert "do not intervene" in text
    assert '"recovery_class": "dead"' in text


# ---- contact stopping rule (6.3) --------------------------------------------


def test_contact_is_worth_it_when_uplift_times_amount_beats_cost():
    assert contact_is_worth_it(0.5, 50_000, "sms", _ECONOMICS) is True


def test_contact_is_not_worth_it_when_uplift_times_amount_is_below_cost():
    # 0.0001 * 50,000 paise = 5 paise < sms cost of 20 paise
    assert contact_is_worth_it(0.0001, 50_000, "sms", _ECONOMICS) is False


# ---- retry stopping rule (6.4) -----------------------------------------------


def test_retry_is_worth_it_for_a_plausible_case():
    assert retry_is_worth_it(RecoveryClass.ACTION_RECOVERABLE, 0.3, 0, _ECONOMICS) is True


def test_retry_is_never_worth_it_for_dead_class_regardless_of_uplift():
    assert retry_is_worth_it(RecoveryClass.DEAD, 0.9, 0, _ECONOMICS) is False


def test_retry_is_not_worth_it_once_mandate_cap_is_reached():
    assert retry_is_worth_it(RecoveryClass.ACTION_RECOVERABLE, 0.9, 4, _ECONOMICS) is False


def test_retry_is_not_worth_it_below_the_decline_rate_penalty_threshold():
    assert retry_is_worth_it(RecoveryClass.ACTION_RECOVERABLE, 0.1, 0, _ECONOMICS) is False


# ---- apply_stopping_rules: out-of-policy proposals get downgraded -----------


def test_apply_stopping_rules_downgrades_an_uneconomical_contact_but_keeps_the_retry():
    # uplift 0.16 clears the retry threshold (0.15) but 0.16 * Rs 1 = 16 paise
    # doesn't clear the sms cost (20 paise) — isolates the contact rule from
    # the retry rule so this test can't pass by coincidence.
    proposal = _proposal(predicted_uplift=0.16)
    failure = _failure(amount_paise=100)

    adjusted = apply_stopping_rules(proposal, failure, _ECONOMICS)

    assert adjusted.should_contact is False
    assert adjusted.customer_message is None
    assert adjusted.should_retry is True


def test_apply_stopping_rules_downgrades_retry_for_dead_class():
    proposal = _proposal(
        recovery_class=RecoveryClass.DEAD, should_contact=False, customer_message=None
    )
    failure = _failure()

    adjusted = apply_stopping_rules(proposal, failure, _ECONOMICS)

    assert adjusted.should_retry is False
    assert adjusted.retry_schedule == []


def test_apply_stopping_rules_downgrades_retry_past_mandate_cap():
    proposal = _proposal(should_contact=False, customer_message=None)
    failure = _failure()

    adjusted = apply_stopping_rules(proposal, failure, _ECONOMICS, attempts_used=4)

    assert adjusted.should_retry is False


def test_apply_stopping_rules_leaves_a_well_formed_proposal_untouched():
    proposal = _proposal(predicted_uplift=0.5)
    failure = _failure(amount_paise=50_000)

    adjusted = apply_stopping_rules(proposal, failure, _ECONOMICS)

    assert adjusted == proposal


# ---- propose_policy: valid, malformed, out-of-policy (6.7) ------------------


def test_propose_policy_returns_a_valid_proposal_and_logs_uplift():
    provider = FakeProvider([_VALID_PROPOSAL_JSON])
    failure = _failure()

    result = propose_policy(
        failure, RecoveryClass.ACTION_RECOVERABLE, provider, _MODEL, economics_config=_ECONOMICS
    )

    assert result.fallback_outcome is None
    assert result.proposal is not None
    assert result.proposal.should_contact is True
    assert result.uplift_log is not None
    assert result.uplift_log.predicted_uplift == 0.4
    assert result.uplift_log.failure_id == failure.failure_id


def test_propose_policy_falls_back_to_baseline_on_malformed_output():
    provider = FakeProvider(["not json", "still not json", "nope"])
    failure = _failure()

    result = propose_policy(
        failure, RecoveryClass.ACTION_RECOVERABLE, provider, _MODEL, economics_config=_ECONOMICS
    )

    assert result.proposal is None
    assert result.uplift_log is None
    assert result.fallback_outcome is not None
    assert result.fallback_outcome.rule_id == "ENV_SCHEMA_VALID"
    assert result.fallback_outcome.verdict.value == "blocked"


def test_propose_policy_downgrades_an_out_of_policy_llm_proposal():
    # Model proposes contact on a tiny amount where it can't possibly be worth it.
    out_of_policy_json = _VALID_PROPOSAL_JSON.replace(
        '"predicted_uplift": 0.4', '"predicted_uplift": 0.00001'
    )
    provider = FakeProvider([out_of_policy_json])
    failure = _failure(amount_paise=50_000)

    result = propose_policy(
        failure, RecoveryClass.ACTION_RECOVERABLE, provider, _MODEL, economics_config=_ECONOMICS
    )

    assert result.proposal is not None
    assert result.proposal.should_contact is False
    assert result.proposal.customer_message is None
    # uplift 0.00001 is also below the retry threshold (0.15) -> retry is dropped too.
    assert result.proposal.should_retry is False


def test_build_uplift_log_entry_maps_fields_directly():
    proposal = _proposal(predicted_uplift=0.42, confidence=0.77)

    entry = build_uplift_log_entry(proposal)

    assert entry.failure_id == proposal.failure_id
    assert entry.recovery_class == proposal.recovery_class
    assert entry.predicted_uplift == 0.42
    assert entry.confidence == 0.77
