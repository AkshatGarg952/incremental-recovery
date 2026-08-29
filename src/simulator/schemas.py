"""Schemas for the failure simulator: observable failures and the latent
outcome model that generates them."""

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class RecoveryClass(StrEnum):
    TIME_RECOVERABLE = "time"
    ROUTE_RECOVERABLE = "route"
    ACTION_RECOVERABLE = "action"
    DEAD = "dead"


class LatentOutcome(BaseModel):
    """Ground truth for one payment failure.

    Never imported by agent, envelope, or executor code — see
    tests/test_no_label_leak.py, the build gate that enforces this.
    """

    would_self_recover: bool
    self_recovery_delay_hours: float
    responds_to_retry: bool
    responds_to_message: bool
    fatigue_threshold: int
    fatigue_decay_per_contact: float
    churn_prob_per_excess_contact: float
    ltv_paise: int


class FailureContext(BaseModel):
    source: Literal["subscription", "checkout", "invoice", "mandate"]
    customer_tenure_days: int
    prior_failures_90d: int
    prior_successful_payments: int
    contacts_last_7d: int
    subscription_mrr_paise: int | None
    invoice_due_date: date | None


class PaymentFailure(BaseModel):
    """Everything an agent is allowed to see about one failed payment."""

    failure_id: str
    merchant_id: str
    customer_ref: str
    amount_paise: int
    currency: Literal["INR"]
    method: Literal["upi", "card", "netbanking", "emandate", "wallet"]
    issuer_code: str
    decline_code: str
    decline_message_raw: str
    failed_at: datetime
    attempt_number: int
    context: FailureContext
