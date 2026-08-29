"""The latent outcome model — ground truth the agent never sees directly.

Encodes per-class self-recovery, responsiveness to intervention, and fatigue
dynamics. `distributions.py` owns population *mixture* proportions; this
module owns the *per-class* recovery model — see BUILD.md R5 for why that
split matters and R6 for the fatigue-with-teeth requirement.
"""

import random

from src.simulator.schemas import LatentOutcome, RecoveryClass

# Base self-recovery probability per class, holdout / zero-intervention.
# Calibrated jointly with distributions.RECOVERY_CLASS_SHARE so the aggregate
# self-recovery rate lands comfortably inside the 15-25% plausibility band
# (R5), not just on its edge, while TIME - ACTION >= 30pp holds with margin.
_BASE_SELF_RECOVERY_RATE: dict[RecoveryClass, float] = {
    RecoveryClass.TIME_RECOVERABLE: 0.52,
    RecoveryClass.ROUTE_RECOVERABLE: 0.30,
    RecoveryClass.ACTION_RECOVERABLE: 0.10,
    RecoveryClass.DEAD: 0.01,
}

# Median self-recovery delay in hours, when it happens at all.
_SELF_RECOVERY_DELAY_HOURS: dict[RecoveryClass, float] = {
    RecoveryClass.TIME_RECOVERABLE: 6.0,
    RecoveryClass.ROUTE_RECOVERABLE: 18.0,
    RecoveryClass.ACTION_RECOVERABLE: 72.0,
    RecoveryClass.DEAD: 168.0,
}

# Probability a retry attempt (same or alternate route) succeeds, given the
# customer did not already self-recover.
_RETRY_RESPONSE_RATE: dict[RecoveryClass, float] = {
    RecoveryClass.TIME_RECOVERABLE: 0.70,
    RecoveryClass.ROUTE_RECOVERABLE: 0.55,
    RecoveryClass.ACTION_RECOVERABLE: 0.05,
    RecoveryClass.DEAD: 0.0,
}

# Probability a customer message (nudge to act) succeeds.
_MESSAGE_RESPONSE_RATE: dict[RecoveryClass, float] = {
    RecoveryClass.TIME_RECOVERABLE: 0.10,
    RecoveryClass.ROUTE_RECOVERABLE: 0.20,
    RecoveryClass.ACTION_RECOVERABLE: 0.45,
    RecoveryClass.DEAD: 0.0,
}

_DEFAULT_FATIGUE_THRESHOLD = 3
_DEFAULT_FATIGUE_DECAY_PER_CONTACT = 0.7
_DEFAULT_CHURN_PROB_PER_EXCESS_CONTACT = 0.05
_EXPECTED_REMAINING_MONTHS = 12


def generate_latent_outcome(
    recovery_class: RecoveryClass,
    customer_reliability: float,
    rng: random.Random,
    mrr_paise: int = 0,
) -> LatentOutcome:
    """Draw one customer's ground truth.

    `customer_reliability` in `[0, 1]` scales responsiveness to both retries
    and messages. `rng` must be seeded by the caller for determinism — this
    module never touches the global `random` module.
    """
    self_recover_rate = _BASE_SELF_RECOVERY_RATE[recovery_class]
    would_self_recover = rng.random() < self_recover_rate

    base_delay = _SELF_RECOVERY_DELAY_HOURS[recovery_class]
    self_recovery_delay_hours = base_delay * rng.uniform(0.5, 1.5)

    reliability_factor = 0.5 + customer_reliability  # in [0.5, 1.5]
    responds_to_retry = rng.random() < min(
        _RETRY_RESPONSE_RATE[recovery_class] * reliability_factor, 1.0
    )
    responds_to_message = rng.random() < min(
        _MESSAGE_RESPONSE_RATE[recovery_class] * reliability_factor, 1.0
    )

    ltv_paise = int(mrr_paise * _EXPECTED_REMAINING_MONTHS)

    return LatentOutcome(
        would_self_recover=would_self_recover,
        self_recovery_delay_hours=self_recovery_delay_hours,
        responds_to_retry=responds_to_retry,
        responds_to_message=responds_to_message,
        fatigue_threshold=_DEFAULT_FATIGUE_THRESHOLD,
        fatigue_decay_per_contact=_DEFAULT_FATIGUE_DECAY_PER_CONTACT,
        churn_prob_per_excess_contact=_DEFAULT_CHURN_PROB_PER_EXCESS_CONTACT,
        ltv_paise=ltv_paise,
    )


def remaining_recovery_probability(
    outcome: LatentOutcome, contacts_made: int, base_probability: float
) -> float:
    """Degrade `base_probability` for each contact past `fatigue_threshold`.

    Fatigue must affect outcomes, not just decisions (BUILD.md R6) — without
    this, every suppressed intervention is pure downside in the report, and a
    spam-everything agent posts better lift than a restrained one.
    """
    excess_contacts = max(contacts_made - outcome.fatigue_threshold, 0)
    return base_probability * (outcome.fatigue_decay_per_contact**excess_contacts)


def churn_probability(outcome: LatentOutcome, contacts_made: int) -> float:
    """Cumulative churn probability from contacts past `fatigue_threshold`."""
    excess_contacts = max(contacts_made - outcome.fatigue_threshold, 0)
    if excess_contacts <= 0:
        return 0.0
    survival = (1 - outcome.churn_prob_per_excess_contact) ** excess_contacts
    return 1 - survival
