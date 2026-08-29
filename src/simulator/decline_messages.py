"""Realistic, messy issuer decline messages — BUILD.md R1.

`decline_message_raw` is deliberately inconsistent: different issuers phrase
the same code differently, and for `DO_NOT_HONOR` the raw text sometimes
leaks the real reason the generic code hides. That gap between code and
message is why the classifier ever needs an LLM.
"""

import random

from src.simulator.schemas import RecoveryClass

_ISSUER_CODES = ["HDFC", "ICICI", "SBI", "AXIS", "KOTAK", "YES", "IDFC", "PNB"]

_TEMPLATES: dict[str, list[str]] = {
    "INSUFFICIENT_FUNDS": [
        "Insufficient balance in account",
        "Txn declined - low bal",
        "INSUFF FUNDS - retry after fund transfer",
        "Available balance is less than transaction amount",
    ],
    "ISSUER_DOWN": [
        "Issuer or switch is inoperative",
        "Bank server not responding, try again later",
        "Unable to process - issuer down",
        "Temporary issue at bank's end",
    ],
    "GATEWAY_TIMEOUT": [
        "Transaction timed out",
        "No response received within time limit",
        "Gateway timeout - please retry",
    ],
    "AUTH_TIMEOUT": [
        "Customer did not authorize within time limit",
        "Collect request expired, not approved",
        "UPI mandate not approved in time",
    ],
    "CARD_EXPIRED": [
        "Expired card",
        "Card validity has lapsed",
        "Please use a valid, unexpired card",
    ],
    "MANDATE_REVOKED": [
        "Mandate cancelled by customer",
        "Standing instruction revoked",
        "e-Mandate no longer active",
    ],
    "LIMIT_EXCEEDED": [
        "Transaction amount exceeds permissible limit",
        "Per-transaction limit exceeded",
        "Daily limit exceeded for this instrument",
    ],
    "INVALID_VPA": [
        "Invalid VPA / UPI handle",
        "Beneficiary VPA does not exist",
        "Incorrect UPI ID provided",
    ],
    "RISK_BLOCKED": [
        "Blocked by risk engine",
        "Transaction flagged for review",
        "Suspicious activity detected, transaction held",
    ],
}

_DO_NOT_HONOR_GENERIC = [
    "Do not honor",
    "Transaction declined by issuing bank",
    "Genuine decline - contact your bank",
]

# When DO_NOT_HONOR is picked, the raw text sometimes leaks the true recovery
# class the generic code hides — the demo moment where the message carries
# more signal than the code (BUILD.md R1). Only ever sampled by the
# generator, which holds ground truth; never fed back deterministically.
_DO_NOT_HONOR_HINT_TEMPLATES: dict[RecoveryClass, list[str]] = {
    RecoveryClass.ACTION_RECOVERABLE: [
        "Do not honor - card reported as expired",
        "Do not honor - insufficient funds as per issuer",
    ],
    RecoveryClass.TIME_RECOVERABLE: [
        "Do not honor - temporary hold, retry later",
        "Do not honor - issuer system congestion",
    ],
    RecoveryClass.ROUTE_RECOVERABLE: [
        "Do not honor - try an alternate payment method",
        "Do not honor - this rail is currently restricted",
    ],
    RecoveryClass.DEAD: [
        "Do not honor - suspected fraud, blocked by risk team",
        "Do not honor - customer disputed a prior charge",
    ],
}

_DO_NOT_HONOR_HINT_PROBABILITY = 0.5


def sample_issuer_code(rng: random.Random) -> str:
    return rng.choice(_ISSUER_CODES)


def generate_decline_message_raw(
    decline_code: str, rng: random.Random, hint_class: RecoveryClass | None = None
) -> str:
    if decline_code == "DO_NOT_HONOR":
        if hint_class is not None and rng.random() < _DO_NOT_HONOR_HINT_PROBABILITY:
            return rng.choice(_DO_NOT_HONOR_HINT_TEMPLATES[hint_class])
        return rng.choice(_DO_NOT_HONOR_GENERIC)
    return rng.choice(_TEMPLATES[decline_code])
