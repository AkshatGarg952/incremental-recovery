"""Batch failure generation — BUILD.md tasks 2.7 and 2.8.

Assembles `PaymentFailure` records from the method-conditional decline
distribution (2.2), issuer messages (2.3), evening/outage/month-end temporal
patterns (2.4, 2.5), customer heterogeneity (2.6), and the recovery-class
shares from Phase 1. The sanity gate is wired in here (2.8): generation
raises before returning if the batch's own latent population fails it, so
nothing bad ever reaches disk.
"""

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from src.simulator.customer import generate_customer_profile
from src.simulator.decline_codes import is_near_month_end, sample_decline_code
from src.simulator.decline_messages import generate_decline_message_raw, sample_issuer_code
from src.simulator.distributions import sample_recovery_class
from src.simulator.latent import generate_latent_outcome
from src.simulator.sanity_gate import check_sanity_gate
from src.simulator.schemas import FailureContext, LatentOutcome, PaymentFailure, RecoveryClass
from src.simulator.temporal import in_outage, sample_failed_at, sample_issuer_outage

_METHODS = ["upi", "card", "netbanking", "emandate", "wallet"]
_METHOD_WEIGHTS = [0.42, 0.32, 0.10, 0.08, 0.08]
_ISSUER_CODES = ["HDFC", "ICICI", "SBI", "AXIS", "KOTAK", "YES", "IDFC", "PNB"]
_MERCHANT_ID = "merchant_demo_01"
_DEFAULT_WINDOW_END = datetime(2026, 9, 1, tzinfo=UTC)
_DEFAULT_WINDOW_DAYS = 30


@dataclass
class GeneratedBatch:
    failures: list[PaymentFailure]
    latent_outcomes: dict[str, LatentOutcome]
    recovery_classes: dict[str, RecoveryClass]


def _sample_source(method: str, rng: random.Random) -> str:
    if method == "emandate":
        return "mandate"
    return rng.choices(["subscription", "checkout", "invoice"], weights=[45, 35, 20], k=1)[0]


def _sample_amount_paise(rng: random.Random) -> int:
    return rng.randint(9_900, 500_000)  # Rs 99 - Rs 5,000


def generate_batch(
    n: int,
    seed: int,
    window_end: datetime = _DEFAULT_WINDOW_END,
    window_days: int = _DEFAULT_WINDOW_DAYS,
) -> GeneratedBatch:
    rng = random.Random(seed)
    window_start = window_end - timedelta(days=window_days)

    outage_count = max(window_days // 10, 1)
    outages = [
        sample_issuer_outage(_ISSUER_CODES, window_start, window_end, rng)
        for _ in range(outage_count)
    ]

    failures: list[PaymentFailure] = []
    latent_outcomes: dict[str, LatentOutcome] = {}
    recovery_classes: dict[str, RecoveryClass] = {}

    for i in range(n):
        failure_id = f"fail_{i:07d}"
        method = rng.choices(_METHODS, weights=_METHOD_WEIGHTS, k=1)[0]
        recovery_class = sample_recovery_class(rng)
        profile = generate_customer_profile(rng)
        failed_at = sample_failed_at(window_start, window_end, rng)
        issuer_code = sample_issuer_code(rng)

        if any(in_outage(outage, issuer_code, failed_at) for outage in outages):
            decline_code = "ISSUER_DOWN"
        else:
            near_month_end = is_near_month_end(failed_at)
            decline_code = sample_decline_code(method, rng, near_month_end=near_month_end)
        decline_message_raw = generate_decline_message_raw(
            decline_code, rng, hint_class=recovery_class
        )

        amount_paise = _sample_amount_paise(rng)
        source = _sample_source(method, rng)
        subscription_mrr_paise = amount_paise if source == "subscription" else None
        invoice_due_date = (
            (failed_at + timedelta(days=rng.randint(1, 10))).date() if source == "invoice" else None
        )

        context = FailureContext(
            source=source,
            customer_tenure_days=profile.customer_tenure_days,
            prior_failures_90d=profile.prior_failures_90d,
            prior_successful_payments=profile.prior_successful_payments,
            contacts_last_7d=profile.contacts_last_7d,
            subscription_mrr_paise=subscription_mrr_paise,
            invoice_due_date=invoice_due_date,
        )

        failures.append(
            PaymentFailure(
                failure_id=failure_id,
                merchant_id=_MERCHANT_ID,
                customer_ref=f"cust_{rng.getrandbits(48):012x}",
                amount_paise=amount_paise,
                currency="INR",
                method=method,
                issuer_code=issuer_code,
                decline_code=decline_code,
                decline_message_raw=decline_message_raw,
                failed_at=failed_at,
                attempt_number=1,
                context=context,
            )
        )

        latent_outcomes[failure_id] = generate_latent_outcome(
            recovery_class, profile.reliability, rng, mrr_paise=subscription_mrr_paise or 0
        )
        recovery_classes[failure_id] = recovery_class

    outcomes_by_class: dict[RecoveryClass, list[bool]] = {c: [] for c in RecoveryClass}
    for failure_id, outcome in latent_outcomes.items():
        outcomes_by_class[recovery_classes[failure_id]].append(outcome.would_self_recover)
    check_sanity_gate(outcomes_by_class)

    return GeneratedBatch(
        failures=failures, latent_outcomes=latent_outcomes, recovery_classes=recovery_classes
    )
