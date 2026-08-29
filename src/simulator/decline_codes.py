"""Decline code taxonomy and method-conditional distribution — BUILD.md R1.

Codes are correlated with the (hidden) recovery class per R1's "typical
class" column, except `DO_NOT_HONOR`, which is deliberately ambiguous: the
most common real decline code, carrying almost no information on its own.
"""

import random
from datetime import datetime

from src.simulator.schemas import RecoveryClass

DECLINE_CODE_CLASS: dict[str, RecoveryClass | None] = {
    "INSUFFICIENT_FUNDS": RecoveryClass.ACTION_RECOVERABLE,
    "ISSUER_DOWN": RecoveryClass.TIME_RECOVERABLE,
    "GATEWAY_TIMEOUT": RecoveryClass.TIME_RECOVERABLE,
    "AUTH_TIMEOUT": RecoveryClass.ACTION_RECOVERABLE,
    "DO_NOT_HONOR": None,  # ambiguous by design
    "CARD_EXPIRED": RecoveryClass.ACTION_RECOVERABLE,
    "MANDATE_REVOKED": RecoveryClass.DEAD,
    "LIMIT_EXCEEDED": RecoveryClass.ACTION_RECOVERABLE,
    "INVALID_VPA": RecoveryClass.ACTION_RECOVERABLE,
    "RISK_BLOCKED": RecoveryClass.DEAD,
}

# Candidate codes per payment method, weighted so each method skews toward its
# characteristic failure mode: UPI toward AUTH_TIMEOUT (collect requests the
# customer never approves), cards toward DO_NOT_HONOR (a generic issuer
# decline carrying almost no information). CARD_EXPIRED and INVALID_VPA are
# method-specific; MANDATE_REVOKED only applies where a mandate exists.
_METHOD_CODE_WEIGHTS: dict[str, dict[str, float]] = {
    "upi": {
        "AUTH_TIMEOUT": 0.30,
        "INSUFFICIENT_FUNDS": 0.22,
        "ISSUER_DOWN": 0.14,
        "INVALID_VPA": 0.10,
        "GATEWAY_TIMEOUT": 0.10,
        "DO_NOT_HONOR": 0.08,
        "LIMIT_EXCEEDED": 0.04,
        "RISK_BLOCKED": 0.02,
    },
    "card": {
        "DO_NOT_HONOR": 0.28,
        "INSUFFICIENT_FUNDS": 0.20,
        "CARD_EXPIRED": 0.18,
        "ISSUER_DOWN": 0.12,
        "GATEWAY_TIMEOUT": 0.10,
        "LIMIT_EXCEEDED": 0.08,
        "RISK_BLOCKED": 0.04,
    },
    "netbanking": {
        "ISSUER_DOWN": 0.32,
        "GATEWAY_TIMEOUT": 0.24,
        "INSUFFICIENT_FUNDS": 0.20,
        "DO_NOT_HONOR": 0.14,
        "LIMIT_EXCEEDED": 0.10,
    },
    "emandate": {
        "MANDATE_REVOKED": 0.35,
        "INSUFFICIENT_FUNDS": 0.30,
        "ISSUER_DOWN": 0.15,
        "DO_NOT_HONOR": 0.12,
        "LIMIT_EXCEEDED": 0.08,
    },
    "wallet": {
        "INSUFFICIENT_FUNDS": 0.34,
        "GATEWAY_TIMEOUT": 0.24,
        "DO_NOT_HONOR": 0.20,
        "RISK_BLOCKED": 0.12,
        "LIMIT_EXCEEDED": 0.10,
    },
}

for _method, _weights in _METHOD_CODE_WEIGHTS.items():
    assert abs(sum(_weights.values()) - 1.0) < 1e-9, f"{_method} decline weights must sum to 1.0"

# Multiplier applied to INSUFFICIENT_FUNDS near month end — payday clustering,
# BUILD.md task 2.5. Weights need not sum to 1 for rng.choices, so this is
# applied directly without renormalizing the rest.
_MONTH_END_INSUFFICIENT_FUNDS_BOOST = 1.8


def sample_decline_code(method: str, rng: random.Random, near_month_end: bool = False) -> str:
    weights = dict(_METHOD_CODE_WEIGHTS[method])
    if near_month_end and "INSUFFICIENT_FUNDS" in weights:
        weights["INSUFFICIENT_FUNDS"] *= _MONTH_END_INSUFFICIENT_FUNDS_BOOST
    codes = list(weights.keys())
    probs = list(weights.values())
    return rng.choices(codes, weights=probs, k=1)[0]


def is_near_month_end(failed_at: datetime, threshold_days: int = 5) -> bool:
    import calendar

    days_in_month = calendar.monthrange(failed_at.year, failed_at.month)[1]
    return days_in_month - failed_at.day < threshold_days
