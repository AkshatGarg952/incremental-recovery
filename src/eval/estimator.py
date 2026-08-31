"""Estimator validation — BUILD.md task 8.5.

Checks the holdout arm's *sampled* self-recovery rate against the *true*
self-recovery rate computed from the generator's own latent ground truth
across the whole batch. In production there is no generator to check
against; this is the machinery that would still be running once there
isn't one.
"""

from dataclasses import dataclass

from src.eval.lift import wilson_ci
from src.eval.outcome_store import OutcomeRecord
from src.simulator.schemas import LatentOutcome


def true_self_recovery_rate(latent_outcomes: dict[str, LatentOutcome]) -> float:
    outcomes = list(latent_outcomes.values())
    if not outcomes:
        return 0.0
    return sum(1 for o in outcomes if o.would_self_recover) / len(outcomes)


@dataclass
class EstimatorValidation:
    true_rate: float
    holdout_estimate: float
    ci: tuple[float, float]
    ci_covers_truth: bool


def validate_estimator(
    holdout: list[OutcomeRecord], latent_outcomes: dict[str, LatentOutcome], alpha: float = 0.05
) -> EstimatorValidation:
    true_rate = true_self_recovery_rate(latent_outcomes)
    successes = sum(1 for r in holdout if r.recovered)
    n = len(holdout)
    holdout_estimate = successes / n if n else 0.0
    ci = wilson_ci(successes, n, alpha)

    return EstimatorValidation(
        true_rate=true_rate,
        holdout_estimate=holdout_estimate,
        ci=ci,
        ci_covers_truth=ci[0] <= true_rate <= ci[1],
    )
