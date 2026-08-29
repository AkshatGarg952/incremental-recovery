"""Three-arm stratified randomization — BUILD.md tasks 4.1-4.3, R2.

Stratifies on `(decline_code, amount_band)` — both observable at assignment
time — never on `recovery_class`: that is the classifier's output and does
not exist yet at assignment time. Classification later runs on all three
arms so per-class lift is computable; only the agent arm acts on it.
"""

import random
from collections import defaultdict
from datetime import datetime

from src.eval.schemas import Arm, LedgerEntry
from src.simulator.schemas import PaymentFailure

# Committed so a batch's assignment is reproducible from the seed alone.
ASSIGNMENT_SEED = 20260901

DEFAULT_ALLOCATION: dict[Arm, float] = {"agent": 0.50, "baseline": 0.25, "holdout": 0.25}


def amount_band(amount_paise: int) -> str:
    """Coarse amount bucket — one half of the stratification key."""
    if amount_paise < 30_000:  # < Rs 300
        return "lt_300"
    if amount_paise < 100_000:  # Rs 300 - 1,000
        return "300_1000"
    if amount_paise < 250_000:  # Rs 1,000 - 2,500
        return "1000_2500"
    return "gte_2500"


def stratum_key(failure: PaymentFailure) -> tuple[str, str]:
    return failure.decline_code, amount_band(failure.amount_paise)


def _validate_allocation(allocation: dict[Arm, float]) -> None:
    if set(allocation) != {"agent", "baseline", "holdout"}:
        raise ValueError(f"allocation must cover exactly the three arms, got {set(allocation)}")
    if abs(sum(allocation.values()) - 1.0) > 1e-9:
        raise ValueError(f"allocation must sum to 1.0, got {sum(allocation.values())}")


def assign_arms(
    failures: list[PaymentFailure],
    seed: int,
    allocation: dict[Arm, float] | None = None,
) -> dict[str, Arm]:
    """Return `{failure_id: arm}`, balanced within every `(decline_code,
    amount_band)` stratum to `allocation`'s proportions (default 50/25/25).

    Uses largest-remainder allocation per stratum rather than independent
    per-row sampling, so proportions hold even in small strata instead of
    drifting away from target with sampling noise.
    """
    allocation = allocation if allocation is not None else DEFAULT_ALLOCATION
    _validate_allocation(allocation)
    rng = random.Random(seed)

    strata: dict[tuple[str, str], list[PaymentFailure]] = defaultdict(list)
    for failure in failures:
        strata[stratum_key(failure)].append(failure)

    arms = list(allocation.keys())
    assignment: dict[str, Arm] = {}

    for stratum_failures in strata.values():
        shuffled = list(stratum_failures)
        rng.shuffle(shuffled)
        n = len(shuffled)

        raw_counts = {arm: allocation[arm] * n for arm in arms}
        counts = {arm: int(raw_counts[arm]) for arm in arms}
        remaining = n - sum(counts.values())
        by_remainder = sorted(arms, key=lambda a: raw_counts[a] - counts[a], reverse=True)
        for arm in by_remainder[:remaining]:
            counts[arm] += 1

        arm_sequence: list[Arm] = [arm for arm in arms for _ in range(counts[arm])]
        rng.shuffle(arm_sequence)

        for failure, arm in zip(shuffled, arm_sequence, strict=True):
            assignment[failure.failure_id] = arm

    return assignment


def build_assignment_ledger_entries(
    failures: list[PaymentFailure], assignment: dict[str, Arm], ts: datetime
) -> list[LedgerEntry]:
    """One `stage="assign"` ledger entry per failure.

    Written before any outcome exists (task 4.3) — assignment must be
    committed before an agent ever acts on a failure, so it can never be
    adjusted after the fact based on how a case turns out.
    """
    return [
        LedgerEntry(
            entry_id=f"assign_{failure.failure_id}",
            failure_id=failure.failure_id,
            ts=ts,
            arm=assignment[failure.failure_id],
            stage="assign",
        )
        for failure in failures
    ]
