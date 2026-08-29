"""Customer heterogeneity — tenure, failure history, reliability, and consent —
BUILD.md task 2.6.

Drives `FailureContext` and the `customer_reliability` signal fed to the
latent outcome model, plus the channel consent set the envelope's
`ENV_CHANNEL_CONSENT` rule checks against (BUILD.md R4).
"""

import random
from dataclasses import dataclass

_CHANNELS = ["sms", "email", "whatsapp", "in_app"]


@dataclass(frozen=True)
class CustomerProfile:
    customer_tenure_days: int
    prior_failures_90d: int
    prior_successful_payments: int
    contacts_last_7d: int
    reliability: float  # in [0, 1]; feeds latent responsiveness
    consent_channels: frozenset[str]


def generate_customer_profile(rng: random.Random) -> CustomerProfile:
    tenure_days = rng.randint(1, 5 * 365)

    reliability = min(max(rng.gauss(0.6, 0.2), 0.0), 1.0)
    prior_failures_90d = rng.choices([0, 1, 2, 3, 4], weights=[50, 25, 12, 8, 5], k=1)[0]
    prior_successful_payments = max(int(tenure_days / 30 * rng.uniform(0.5, 1.0)), 0)
    contacts_last_7d = rng.choices([0, 1, 2, 3], weights=[70, 18, 8, 4], k=1)[0]

    consent_pool_size = rng.choices([1, 2, 3, 4], weights=[15, 35, 35, 15], k=1)[0]
    consent_channels = frozenset(rng.sample(_CHANNELS, k=consent_pool_size))

    return CustomerProfile(
        customer_tenure_days=tenure_days,
        prior_failures_90d=prior_failures_90d,
        prior_successful_payments=prior_successful_payments,
        contacts_last_7d=contacts_last_7d,
        reliability=reliability,
        consent_channels=consent_channels,
    )
