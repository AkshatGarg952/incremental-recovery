"""Offline tests for three-arm stratified assignment (BUILD.md tasks 4.1-4.4)."""

from collections import Counter, defaultdict
from datetime import UTC, datetime

import pytest

from src.eval.assignment import (
    ASSIGNMENT_SEED,
    DEFAULT_ALLOCATION,
    amount_band,
    assign_arms,
    build_assignment_ledger_entries,
    stratum_key,
)
from src.simulator.generator import generate_batch

_BATCH = generate_batch(n=3000, seed=ASSIGNMENT_SEED)


def test_assign_arms_holds_allocation_within_every_stratum():
    assignment = assign_arms(_BATCH.failures, seed=ASSIGNMENT_SEED)

    strata: dict[tuple[str, str], list] = defaultdict(list)
    for failure in _BATCH.failures:
        strata[stratum_key(failure)].append(failure)

    checked_any = False
    for key, failures in strata.items():
        if len(failures) < 20:
            continue  # thin cells can't hold tight proportions — not a balance failure
        checked_any = True
        counts = Counter(assignment[f.failure_id] for f in failures)
        n = len(failures)
        for arm, target in DEFAULT_ALLOCATION.items():
            actual = counts.get(arm, 0) / n
            assert abs(actual - target) < 0.08, (
                f"{key}: {arm} actual={actual:.2f} target={target:.2f}"
            )

    assert checked_any, "no stratum had enough rows to check balance"


def test_assign_arms_is_seed_deterministic():
    first = assign_arms(_BATCH.failures, seed=ASSIGNMENT_SEED)
    second = assign_arms(_BATCH.failures, seed=ASSIGNMENT_SEED)

    assert first == second


def test_assign_arms_covers_every_failure_exactly_once():
    assignment = assign_arms(_BATCH.failures, seed=ASSIGNMENT_SEED)

    assert set(assignment) == {f.failure_id for f in _BATCH.failures}
    assert set(assignment.values()) <= {"agent", "baseline", "holdout"}


def test_assign_arms_honors_a_custom_allocation():
    allocation = {"agent": 0.6, "baseline": 0.2, "holdout": 0.2}
    assignment = assign_arms(_BATCH.failures, seed=ASSIGNMENT_SEED, allocation=allocation)

    counts = Counter(assignment.values())
    total = sum(counts.values())
    assert abs(counts["agent"] / total - 0.6) < 0.03


def test_assign_arms_rejects_allocation_not_summing_to_one():
    with pytest.raises(ValueError, match="sum to 1.0"):
        assign_arms(
            _BATCH.failures[:10],
            seed=ASSIGNMENT_SEED,
            allocation={"agent": 0.5, "baseline": 0.3, "holdout": 0.3},
        )


def test_assign_arms_rejects_allocation_missing_an_arm():
    with pytest.raises(ValueError, match="exactly the three arms"):
        assign_arms(
            _BATCH.failures[:10],
            seed=ASSIGNMENT_SEED,
            allocation={"agent": 0.5, "baseline": 0.5},
        )


def test_amount_band_is_monotonic_and_covers_the_generator_range():
    assert amount_band(9_900) == "lt_300"
    assert amount_band(50_000) == "300_1000"
    assert amount_band(150_000) == "1000_2500"
    assert amount_band(500_000) == "gte_2500"


def test_build_assignment_ledger_entries_are_stage_assign_with_no_outcome_fields():
    assignment = assign_arms(_BATCH.failures, seed=ASSIGNMENT_SEED)
    entries = build_assignment_ledger_entries(
        _BATCH.failures, assignment, ts=datetime(2026, 9, 1, tzinfo=UTC)
    )

    assert len(entries) == len(_BATCH.failures)
    for entry, failure in zip(entries, _BATCH.failures, strict=True):
        assert entry.stage == "assign"
        assert entry.failure_id == failure.failure_id
        assert entry.arm == assignment[failure.failure_id]
        assert entry.proposed is None
        assert entry.approved is None
        assert entry.envelope_verdict is None
        assert entry.envelope_rules_fired == []
