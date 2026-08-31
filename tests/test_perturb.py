"""Offline tests for the perturbation engine, cache invalidation, and
re-plan/diff rendering (BUILD.md tasks 9.1-9.3)."""

import json
from datetime import UTC, datetime

from src.agent.classifier import build_classification_request
from src.agent.policy import build_policy_request, load_economics_config
from src.executor.clock import SimulatedClock
from src.llm.cache import ResponseCache
from src.llm.fake import FakeProvider
from src.perturb.cache_invalidation import invalidate_cache_for_failures
from src.perturb.engine import apply_clock_shift, apply_decline_spike, apply_issuer_outage
from src.perturb.replan import render_decision_diffs, replan_affected_failures
from src.simulator.schemas import FailureContext, PaymentFailure, RecoveryClass

_START = datetime(2026, 8, 29, 6, 30, tzinfo=UTC)
_CLASSIFY_MODEL = "gemini-2.5-flash-lite"
_POLICY_MODEL = "openai/gpt-oss-120b"


def _failure(failure_id: str, issuer_code: str, decline_code: str, **overrides) -> PaymentFailure:
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
        issuer_code=issuer_code,
        decline_code=decline_code,
        decline_message_raw="generic message",
        failed_at=_START,
        attempt_number=1,
        context=context,
    )
    defaults.update(overrides)
    return PaymentFailure(**defaults)


def _batch() -> list[PaymentFailure]:
    return [
        _failure("f1", "HDFC", "AUTH_TIMEOUT"),
        _failure("f2", "HDFC", "INSUFFICIENT_FUNDS"),
        _failure("f3", "ICICI", "DO_NOT_HONOR"),
        _failure("f4", "HDFC", "CARD_EXPIRED"),
        _failure("f5", "SBI", "GATEWAY_TIMEOUT"),
    ]


# ---- engine (9.1) -------------------------------------------------------------


def test_apply_issuer_outage_only_affects_matching_issuer():
    result = apply_issuer_outage(_batch(), "HDFC", duration_hours=0.75)

    assert set(result.affected_failure_ids) == {"f1", "f2", "f4"}
    for failure_id in result.affected_failure_ids:
        assert result.perturbed_by_id[failure_id].decline_code == "ISSUER_DOWN"
        assert "HDFC" in result.perturbed_by_id[failure_id].decline_message_raw
        # original is untouched — perturbation returns a copy
        assert result.original_by_id[failure_id].decline_code != "ISSUER_DOWN"


def test_apply_issuer_outage_respects_max_affected():
    result = apply_issuer_outage(_batch(), "HDFC", duration_hours=0.75, max_affected=2)
    assert len(result.affected_failure_ids) == 2


def test_apply_issuer_outage_with_no_matches_is_empty():
    result = apply_issuer_outage(_batch(), "AXIS", duration_hours=0.75)
    assert result.affected_failure_ids == []


def test_apply_decline_spike_is_seed_deterministic_and_skips_already_matching():
    first = apply_decline_spike(_batch(), "MANDATE_REVOKED", max_affected=3, seed=42)
    second = apply_decline_spike(_batch(), "MANDATE_REVOKED", max_affected=3, seed=42)

    assert first.affected_failure_ids == second.affected_failure_ids
    for failure_id in first.affected_failure_ids:
        assert first.perturbed_by_id[failure_id].decline_code == "MANDATE_REVOKED"


def test_apply_clock_shift_advances_the_clock():
    from datetime import timedelta

    clock = SimulatedClock(_START)
    apply_clock_shift(clock, 72.0)
    assert clock.now() == _START + timedelta(hours=72)


# ---- selective cache invalidation (9.2) ---------------------------------------


def test_invalidate_cache_for_failures_removes_only_the_affected_entries(tmp_path):
    cache = ResponseCache(tmp_path / "cache.sqlite3")

    f1 = _failure("f1", "HDFC", "AUTH_TIMEOUT")
    f2 = _failure("f2", "ICICI", "DO_NOT_HONOR")
    recovery_classes = {"f1": RecoveryClass.ACTION_RECOVERABLE, "f2": RecoveryClass.DEAD}

    for failure in (f1, f2):
        classify_request = build_classification_request(failure, _CLASSIFY_MODEL)
        cache.put(
            "classify",
            "gemini",
            classify_request,
            "v1",
            _fake_response(classify_request, "cached classify"),
        )
        policy_request = build_policy_request(
            failure, recovery_classes[failure.failure_id], _POLICY_MODEL
        )
        cache.put(
            "policy", "groq", policy_request, "v1", _fake_response(policy_request, "cached policy")
        )

    invalidated = invalidate_cache_for_failures(
        cache, [f1], recovery_classes, _CLASSIFY_MODEL, "gemini", _POLICY_MODEL, "groq"
    )

    assert invalidated == 2  # f1's classify + policy entries
    assert (
        cache.get("classify", "gemini", build_classification_request(f1, _CLASSIFY_MODEL), "v1")
        is None
    )
    assert (
        cache.get("classify", "gemini", build_classification_request(f2, _CLASSIFY_MODEL), "v1")
        is not None
    )


def _fake_response(request, content: str):
    from src.llm.client import ChatResponse, Usage

    return ChatResponse(
        content=content,
        usage=Usage(prompt_tokens=1, completion_tokens=1),
        model=request.model,
        provider="fake",
    )


# ---- re-plan and decision diffs (9.3) ------------------------------------------


def test_replan_affected_failures_shows_a_changed_decision():
    original = {"f1": _failure("f1", "HDFC", "AUTH_TIMEOUT")}
    perturbed = {"f1": _failure("f1", "HDFC", "ISSUER_DOWN")}

    # before: classify(rule, action) -> propose(action)
    # after: classify(rule, time) -> propose(time)
    before_policy = json.dumps(
        {
            "failure_id": "f1",
            "recovery_class": "action",
            "should_retry": False,
            "should_contact": True,
            "retry_schedule": [],
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
    after_policy = json.dumps(
        {
            "failure_id": "f1",
            "recovery_class": "time",
            "should_retry": True,
            "should_contact": False,
            "retry_schedule": [{"delay_hours": 2, "route_hint": "same", "reason": "r"}],
            "customer_message": None,
            "predicted_uplift": 0.3,
            "rationale": "r",
            "confidence": 0.8,
        }
    )
    # AUTH_TIMEOUT and ISSUER_DOWN are both "clean" codes -> classify is rule-based,
    # no LLM call needed. Only the two propose_policy calls hit the provider.
    provider = FakeProvider([before_policy, after_policy])
    economics = load_economics_config()

    diffs = replan_affected_failures(
        original, perturbed, provider, _CLASSIFY_MODEL, provider, _POLICY_MODEL, economics
    )

    assert len(diffs) == 1
    diff = diffs[0]
    assert diff.before_decline_code == "AUTH_TIMEOUT"
    assert diff.after_decline_code == "ISSUER_DOWN"
    assert diff.before_recovery_class == RecoveryClass.ACTION_RECOVERABLE
    assert diff.after_recovery_class == RecoveryClass.TIME_RECOVERABLE
    assert diff.changed is True

    rendered = render_decision_diffs(diffs)
    assert "CHANGED" in rendered
    assert "1/1 decisions changed" in rendered


def test_replan_reports_no_change_when_decisions_are_identical():
    original = {"f1": _failure("f1", "HDFC", "CARD_EXPIRED")}
    perturbed = {"f1": _failure("f1", "HDFC", "CARD_EXPIRED")}  # no actual change
    provider = FakeProvider(
        [
            json.dumps(
                {
                    "failure_id": "f1",
                    "recovery_class": "action",
                    "should_retry": False,
                    "should_contact": False,
                    "retry_schedule": [],
                    "customer_message": None,
                    "predicted_uplift": 0.0,
                    "rationale": "r",
                    "confidence": 0.5,
                }
            )
        ]
        * 2
    )
    economics = load_economics_config()

    diffs = replan_affected_failures(
        original, perturbed, provider, _CLASSIFY_MODEL, provider, _POLICY_MODEL, economics
    )

    assert diffs[0].changed is False
    assert "0/1 decisions changed" in render_decision_diffs(diffs)
