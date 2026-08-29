"""BUILD GATE — written before the latent model exists (BUILD.md task 1.1,
gate R5).

Holdout-only, zero interventions, N=20,000, fixed seed. Zero model calls, so
it is free and instant. If TIME and ACTION self-recovery rates are within
10pp of each other, the latent model is not encoding recovery class at all:
there is no signal to act on, and the per-class lift breakdown collapses into
a flat bar.
"""

import random

import pytest

from src.simulator.distributions import RECOVERY_CLASS_SHARE, sample_recovery_class
from src.simulator.latent import generate_latent_outcome
from src.simulator.sanity_gate import BAND, SanityGateFailure, check_sanity_gate
from src.simulator.schemas import RecoveryClass

_N = 20_000
_SEED = 20260901


def _generate_population(n: int, seed: int) -> dict[RecoveryClass, list[bool]]:
    rng = random.Random(seed)
    outcomes: dict[RecoveryClass, list[bool]] = {c: [] for c in RecoveryClass}
    for _ in range(n):
        recovery_class = sample_recovery_class(rng)
        reliability = rng.random()
        outcome = generate_latent_outcome(recovery_class, reliability, rng)
        outcomes[recovery_class].append(outcome.would_self_recover)
    return outcomes


def test_self_recovery_rate_is_plausible_and_class_ordered():
    outcomes = _generate_population(_N, _SEED)

    rate_pct = {c: 100.0 * sum(vals) / len(vals) for c, vals in outcomes.items() if vals}

    for recovery_class, (low, high) in BAND.items():
        assert low <= rate_pct[recovery_class] <= high, (
            f"{recovery_class}: {rate_pct[recovery_class]:.1f}% outside band [{low}, {high}]"
        )

    # THE load-bearing assertion.
    spread = rate_pct[RecoveryClass.TIME_RECOVERABLE] - rate_pct[RecoveryClass.ACTION_RECOVERABLE]
    assert spread >= 30.0

    total = sum(len(vals) for vals in outcomes.values())
    share = {c: len(vals) / total for c, vals in outcomes.items()}
    expected_aggregate = sum(share[c] * rate_pct[c] for c in RecoveryClass)
    actual_aggregate = 100.0 * sum(sum(vals) for vals in outcomes.values()) / total

    # Mixture arithmetic holds.
    assert abs(actual_aggregate - expected_aggregate) < 2.0
    # And the result is plausible.
    assert 15.0 <= actual_aggregate <= 25.0

    # The generator (task 2.8) wires this exact check in at generation time —
    # the same population must pass it too.
    check_sanity_gate(outcomes)


def test_recovery_class_shares_are_stable_and_sum_to_one():
    assert abs(sum(RECOVERY_CLASS_SHARE.values()) - 1.0) < 1e-9
    for share in RECOVERY_CLASS_SHARE.values():
        assert 0.0 < share < 1.0


def test_generation_is_seed_deterministic():
    first = _generate_population(2_000, _SEED)
    second = _generate_population(2_000, _SEED)
    assert first == second


def test_check_sanity_gate_rejects_a_population_with_no_class_signal():
    flat_outcomes = {c: [True] * 20 + [False] * 80 for c in RecoveryClass}  # 20% everywhere

    with pytest.raises(SanityGateFailure):
        check_sanity_gate(flat_outcomes)
