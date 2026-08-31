"""Per-class breakdown with thin-cell flagging (8.6) and the horizon curve
(8.7) — BUILD.md tasks 8.6-8.7.
"""

from dataclasses import dataclass

from src.eval.lift import recovery_rate
from src.eval.outcome_store import OutcomeRecord
from src.simulator.schemas import RecoveryClass

# BUILD.md R8: "DEAD is ~37 holdout rows — print the wide interval and say
# so." Below this count in any arm, flag the row rather than pretend the
# rate is precise.
THIN_CELL_THRESHOLD = 30

DEFAULT_HORIZONS_HOURS = (24.0, 72.0, 168.0)


@dataclass
class ClassBreakdownRow:
    recovery_class: RecoveryClass
    n_agent: int
    n_baseline: int
    n_holdout: int
    rate_agent: float
    rate_baseline: float
    rate_holdout: float
    lift_vs_baseline: float
    thin_cell: bool


def per_class_breakdown(
    agent: list[OutcomeRecord], baseline: list[OutcomeRecord], holdout: list[OutcomeRecord]
) -> list[ClassBreakdownRow]:
    rows = []
    for recovery_class in RecoveryClass:
        class_agent = [r for r in agent if r.recovery_class == recovery_class]
        class_baseline = [r for r in baseline if r.recovery_class == recovery_class]
        class_holdout = [r for r in holdout if r.recovery_class == recovery_class]
        thin = min(len(class_agent), len(class_baseline), len(class_holdout)) < THIN_CELL_THRESHOLD
        rate_agent = recovery_rate(class_agent)
        rate_baseline = recovery_rate(class_baseline)
        rows.append(
            ClassBreakdownRow(
                recovery_class=recovery_class,
                n_agent=len(class_agent),
                n_baseline=len(class_baseline),
                n_holdout=len(class_holdout),
                rate_agent=rate_agent,
                rate_baseline=rate_baseline,
                rate_holdout=recovery_rate(class_holdout),
                lift_vs_baseline=rate_agent - rate_baseline,
                thin_cell=thin,
            )
        )
    return rows


def _rate_by_horizon(records: list[OutcomeRecord], horizon_hours: float) -> float:
    if not records:
        return 0.0
    recovered_within = sum(
        1
        for r in records
        if r.recovered
        and r.recovered_at_hours is not None
        and r.recovered_at_hours <= horizon_hours
    )
    return recovered_within / len(records)


@dataclass
class HorizonCurveRow:
    horizon_hours: float
    rate_agent: float
    rate_baseline: float
    rate_holdout: float
    lift_vs_holdout: float
    lift_vs_baseline: float


def horizon_curve(
    agent: list[OutcomeRecord],
    baseline: list[OutcomeRecord],
    holdout: list[OutcomeRecord],
    horizons_hours: tuple[float, ...] = DEFAULT_HORIZONS_HOURS,
) -> list[HorizonCurveRow]:
    rows = []
    for horizon in horizons_hours:
        rate_agent = _rate_by_horizon(agent, horizon)
        rate_baseline = _rate_by_horizon(baseline, horizon)
        rate_holdout = _rate_by_horizon(holdout, horizon)
        rows.append(
            HorizonCurveRow(
                horizon_hours=horizon,
                rate_agent=rate_agent,
                rate_baseline=rate_baseline,
                rate_holdout=rate_holdout,
                lift_vs_holdout=rate_agent - rate_holdout,
                lift_vs_baseline=rate_agent - rate_baseline,
            )
        )
    return rows
