"""Offline tests for the failure classifier (BUILD.md tasks 5.1-5.8)."""

from datetime import UTC, datetime

from src.agent.classifier import (
    ClassificationResult,
    classify_batch,
    classify_failure,
    needs_llm_adjudication,
    rule_prior,
)
from src.agent.classifier_eval import load_golden_set, run_classifier_eval
from src.eval.assignment import ASSIGNMENT_SEED, assign_arms
from src.llm.fake import FakeProvider
from src.simulator.generator import generate_batch
from src.simulator.schemas import FailureContext, PaymentFailure, RecoveryClass

_MODEL = "test-model"


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
        decline_code="INSUFFICIENT_FUNDS",
        decline_message_raw="Insufficient balance in account",
        failed_at=datetime(2026, 8, 29, 6, 30, tzinfo=UTC),
        attempt_number=1,
        context=context,
    )
    defaults.update(overrides)
    return PaymentFailure(**defaults)


# ---- rule prior + ambiguity router -----------------------------------------


def test_rule_prior_returns_class_for_clean_codes():
    failure = _failure(decline_code="MANDATE_REVOKED")
    assert rule_prior(failure) == RecoveryClass.DEAD


def test_rule_prior_is_none_for_do_not_honor():
    failure = _failure(decline_code="DO_NOT_HONOR")
    assert rule_prior(failure) is None


def test_needs_llm_adjudication_true_for_do_not_honor():
    failure = _failure(decline_code="DO_NOT_HONOR")
    assert needs_llm_adjudication(failure) is True


def test_needs_llm_adjudication_true_for_message_code_conflict():
    failure = _failure(
        decline_code="INSUFFICIENT_FUNDS",  # rule prior: action
        decline_message_raw="Temporary issue at bank's end, try again later",  # time-flavored
    )
    assert needs_llm_adjudication(failure) is True


def test_needs_llm_adjudication_true_for_context_conflict():
    failure = _failure(
        decline_code="MANDATE_REVOKED",
        decline_message_raw="Mandate cancelled by customer",
        context={
            "customer_tenure_days": 900,
            "prior_successful_payments": 48,
            "prior_failures_90d": 0,
        },
    )
    assert needs_llm_adjudication(failure) is True


def test_needs_llm_adjudication_false_for_a_clean_unambiguous_case():
    failure = _failure(
        decline_code="INSUFFICIENT_FUNDS", decline_message_raw="Insufficient balance in account"
    )
    assert needs_llm_adjudication(failure) is False


# ---- classify_failure --------------------------------------------------------


def test_classify_failure_uses_rule_prior_without_calling_the_llm():
    provider = FakeProvider([])  # any LLM call would raise: exhausted immediately
    failure = _failure(decline_code="CARD_EXPIRED")

    result = classify_failure(failure, provider, _MODEL)

    assert result.source == "rule"
    assert result.recovery_class == RecoveryClass.ACTION_RECOVERABLE
    assert result.confidence == 1.0
    assert provider.calls == []


def test_classify_failure_calls_llm_for_an_ambiguous_case():
    provider = FakeProvider(
        ['{"recovery_class": "dead", "confidence": 0.9, "rationale": "risk block"}']
    )
    failure = _failure(decline_code="DO_NOT_HONOR", decline_message_raw="Do not honor")

    result = classify_failure(failure, provider, _MODEL)

    assert result.source == "llm"
    assert result.recovery_class == RecoveryClass.DEAD
    assert result.confidence == 0.9
    assert len(provider.calls) == 1


def test_classify_failure_routes_low_confidence_to_the_exception_list():
    provider = FakeProvider(
        ['{"recovery_class": "action", "confidence": 0.3, "rationale": "unsure"}']
    )
    failure = _failure(decline_code="DO_NOT_HONOR")

    result = classify_failure(failure, provider, _MODEL)

    assert result.recovery_class is None
    assert result.source == "llm"
    assert "low confidence" in result.rationale


def test_classify_failure_routes_unparseable_llm_output_to_the_exception_list():
    provider = FakeProvider(["not json", "still not json", "nope"])
    failure = _failure(decline_code="DO_NOT_HONOR")

    result = classify_failure(failure, provider, _MODEL)

    assert result.recovery_class is None
    assert result.source == "llm"
    assert "unparseable" in result.rationale


# ---- classify_batch: all three arms -----------------------------------------


def test_classify_batch_labels_every_failure_regardless_of_assigned_arm():
    batch = generate_batch(n=3000, seed=ASSIGNMENT_SEED)
    assignment = assign_arms(batch.failures, seed=ASSIGNMENT_SEED)

    # Script enough responses for every case the router actually sends to the
    # LLM (DO_NOT_HONOR plus any message/context conflicts on "clean" codes)
    # so none of them raises FakeProviderExhausted.
    ambiguous_count = sum(1 for f in batch.failures if needs_llm_adjudication(f))
    response = '{"recovery_class": "action", "confidence": 0.9, "rationale": "r"}'
    provider = FakeProvider([response] * ambiguous_count)

    results: dict[str, ClassificationResult] = classify_batch(batch.failures, provider, _MODEL)

    assert len(results) == len(batch.failures)
    arms_seen = {assignment[fid] for fid in results}
    assert arms_seen == {"agent", "baseline", "holdout"}
    holdout_ids = [fid for fid, arm in assignment.items() if arm == "holdout"]
    assert all(fid in results for fid in holdout_ids)


# ---- golden set --------------------------------------------------------------


def test_golden_set_has_30_cases_weighted_to_ambiguous_codes_and_covers_all_classes():
    cases = load_golden_set()

    assert len(cases) == 30

    ambiguous_count = sum(1 for failure, _ in cases if failure.decline_code == "DO_NOT_HONOR")
    assert ambiguous_count >= 12  # weighted toward ambiguous, not exactly half by construction

    gold_classes = {gold for _, gold in cases}
    assert gold_classes == set(RecoveryClass)


# ---- eval runner --------------------------------------------------------------


def test_run_classifier_eval_computes_accuracy_call_rate_and_confusion():
    cases = [
        (
            _failure(decline_code="CARD_EXPIRED", decline_message_raw="Expired card"),
            RecoveryClass.ACTION_RECOVERABLE,
        ),  # rule, correct
        (
            _failure(
                decline_code="MANDATE_REVOKED", decline_message_raw="Mandate cancelled by customer"
            ),
            RecoveryClass.DEAD,
        ),  # rule, correct
        (
            _failure(decline_code="DO_NOT_HONOR", decline_message_raw="Do not honor"),
            RecoveryClass.DEAD,
        ),  # llm, wrong on purpose
    ]
    provider = FakeProvider(['{"recovery_class": "action", "confidence": 0.9, "rationale": "r"}'])

    report = run_classifier_eval(cases, provider, _MODEL)

    assert report.total == 3
    assert report.correct == 2
    assert report.accuracy == 2 / 3
    assert report.llm_calls == 1
    assert report.llm_call_rate == 1 / 3
    assert report.exceptions == 0
    assert report.confusion[("dead", "action")] == 1
    assert "accuracy" in report.render()
