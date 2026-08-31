"""BUILD.md task 8.13 — known-lift fixture.

Construct a batch with known true recovery probabilities per arm, and
assert the harness's lift estimate recovers the true lift within its own
reported confidence interval — the estimator-validation idea (task 8.5)
applied directly to the lift computation itself.
"""

import random

import pytest

from src.eval.lift import compute_lift
from src.eval.outcome_store import OutcomeRecord
from src.simulator.schemas import RecoveryClass

_TRUE_RATE_AGENT = 0.35
_TRUE_RATE_BASELINE = 0.24
_TRUE_RATE_HOLDOUT = 0.19
_N_PER_ARM = 1000
_SEED = 20260901


def _draw_records(arm: str, true_rate: float, n: int, rng: random.Random) -> list[OutcomeRecord]:
    return [
        OutcomeRecord(
            failure_id=f"{arm}_{i}",
            arm=arm,
            recovery_class=RecoveryClass.ACTION_RECOVERABLE,
            recovered=rng.random() < true_rate,
            recovered_at_hours=None,
            retries_made=0,
            contacts_made=0,
            amount_paise=50_000,
            contact_cost_paise=0,
            would_self_recover=False,
        )
        for i in range(n)
    ]


def test_known_lift_fixture_is_recovered_within_the_reported_ci():
    rng = random.Random(_SEED)
    agent = _draw_records("agent", _TRUE_RATE_AGENT, _N_PER_ARM, rng)
    baseline = _draw_records("baseline", _TRUE_RATE_BASELINE, _N_PER_ARM, rng)
    holdout = _draw_records("holdout", _TRUE_RATE_HOLDOUT, _N_PER_ARM, rng)

    lift = compute_lift(agent, baseline, holdout)

    true_lift_vs_holdout = _TRUE_RATE_AGENT - _TRUE_RATE_HOLDOUT
    true_lift_vs_baseline = _TRUE_RATE_AGENT - _TRUE_RATE_BASELINE

    assert lift.lift_vs_holdout_ci[0] <= true_lift_vs_holdout <= lift.lift_vs_holdout_ci[1]
    assert lift.lift_vs_baseline_ci[0] <= true_lift_vs_baseline <= lift.lift_vs_baseline_ci[1]

    assert lift.rate_agent == pytest.approx(_TRUE_RATE_AGENT, abs=0.05)
    assert lift.rate_baseline == pytest.approx(_TRUE_RATE_BASELINE, abs=0.05)
    assert lift.rate_holdout == pytest.approx(_TRUE_RATE_HOLDOUT, abs=0.05)
