"""Lift against both holdout and baseline, with confidence intervals —
BUILD.md tasks 8.2-8.3.

CIs use statsmodels' Newcombe/Wilson methods (`confint_proportions_2indep`,
`proportion_confint`) — do not hand-roll a normal-approximation interval.
"""

from dataclasses import dataclass

from statsmodels.stats.proportion import confint_proportions_2indep, proportion_confint

from src.eval.outcome_store import OutcomeRecord


def recovery_rate(records: list[OutcomeRecord]) -> float:
    if not records:
        return 0.0
    return sum(1 for r in records if r.recovered) / len(records)


def wilson_ci(successes: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    low, high = proportion_confint(successes, n, alpha=alpha, method="wilson")
    return (float(low), float(high))


def newcombe_diff_ci(
    successes_a: int, n_a: int, successes_b: int, n_b: int, alpha: float = 0.05
) -> tuple[float, float]:
    """CI for `p_a - p_b`, Newcombe's method (the score-based difference of
    two Wilson intervals)."""
    if n_a == 0 or n_b == 0:
        return (0.0, 0.0)
    low, high = confint_proportions_2indep(
        successes_a, n_a, successes_b, n_b, method="newcomb", compare="diff", alpha=alpha
    )
    return (float(low), float(high))


@dataclass
class LiftReport:
    n_agent: int
    n_baseline: int
    n_holdout: int
    rate_agent: float
    rate_baseline: float
    rate_holdout: float
    lift_vs_holdout: float
    lift_vs_holdout_ci: tuple[float, float]
    lift_vs_baseline: float
    lift_vs_baseline_ci: tuple[float, float]


def compute_lift(
    agent: list[OutcomeRecord],
    baseline: list[OutcomeRecord],
    holdout: list[OutcomeRecord],
    alpha: float = 0.05,
) -> LiftReport:
    n_agent, n_baseline, n_holdout = len(agent), len(baseline), len(holdout)
    successes_agent = sum(1 for r in agent if r.recovered)
    successes_baseline = sum(1 for r in baseline if r.recovered)
    successes_holdout = sum(1 for r in holdout if r.recovered)

    rate_agent = recovery_rate(agent)
    rate_baseline = recovery_rate(baseline)
    rate_holdout = recovery_rate(holdout)

    return LiftReport(
        n_agent=n_agent,
        n_baseline=n_baseline,
        n_holdout=n_holdout,
        rate_agent=rate_agent,
        rate_baseline=rate_baseline,
        rate_holdout=rate_holdout,
        lift_vs_holdout=rate_agent - rate_holdout,
        lift_vs_holdout_ci=newcombe_diff_ci(
            successes_agent, n_agent, successes_holdout, n_holdout, alpha
        ),
        lift_vs_baseline=rate_agent - rate_baseline,
        lift_vs_baseline_ci=newcombe_diff_ci(
            successes_agent, n_agent, successes_baseline, n_baseline, alpha
        ),
    )
