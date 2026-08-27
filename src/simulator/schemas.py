"""Ground-truth schemas for the failure simulator's latent outcome model."""

from enum import StrEnum

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
