"""Population-level distributions for the failure simulator.

Keep mixture proportions here, not in `latent.py` — see BUILD.md R5: a
mixture-arithmetic check that passes while the plausibility band fails means
the *mix* is wrong, not the per-class recovery model.
"""

import random

from src.simulator.schemas import RecoveryClass

# Marginal share of each recovery class across all failures, derived from the
# R1 decline-code mix: INSUFFICIENT_FUNDS/AUTH_TIMEOUT/CARD_EXPIRED/INVALID_VPA
# -> action (46%), ISSUER_DOWN -> time (18%), GATEWAY_TIMEOUT/LIMIT_EXCEEDED
# split time/route (9.5%/2.5%), MANDATE_REVOKED/RISK_BLOCKED -> dead (7%). The
# ambiguous DO_NOT_HONOR share (10%) carries no code-level class signal, so
# it is distributed proportionally across the other four rather than assigned
# its own bucket.
RECOVERY_CLASS_SHARE: dict[RecoveryClass, float] = {
    RecoveryClass.ACTION_RECOVERABLE: 0.54,
    RecoveryClass.TIME_RECOVERABLE: 0.30,
    RecoveryClass.ROUTE_RECOVERABLE: 0.08,
    RecoveryClass.DEAD: 0.08,
}

assert abs(sum(RECOVERY_CLASS_SHARE.values()) - 1.0) < 1e-9, "class shares must sum to 1.0"


def sample_recovery_class(rng: random.Random) -> RecoveryClass:
    """Draw one recovery class from `RECOVERY_CLASS_SHARE`.

    `rng` must be a caller-seeded `random.Random` — never the global `random`
    module — so generation stays byte-identical for a given seed.
    """
    classes = list(RECOVERY_CLASS_SHARE.keys())
    weights = list(RECOVERY_CLASS_SHARE.values())
    return rng.choices(classes, weights=weights, k=1)[0]
