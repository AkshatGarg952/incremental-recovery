"""Shared sanity-gate assertions — BUILD.md R5.

Used both by `tests/test_simulator_sanity.py` (task 1.1, the pytest build
gate) and by the batch generator (task 2.8, wiring the same gate in at
generation time so a bad batch aborts before anything is written). Keeping
the thresholds in one place means the two can never drift apart.
"""

from src.simulator.schemas import RecoveryClass

BAND: dict[RecoveryClass, tuple[float, float]] = {
    RecoveryClass.TIME_RECOVERABLE: (48.0, 65.0),
    RecoveryClass.ROUTE_RECOVERABLE: (25.0, 40.0),
    RecoveryClass.ACTION_RECOVERABLE: (8.0, 18.0),
    RecoveryClass.DEAD: (0.0, 3.0),
}

MIN_TIME_ACTION_SPREAD = 30.0
MAX_MIXTURE_DRIFT = 2.0
AGGREGATE_BAND = (15.0, 25.0)


class SanityGateFailure(RuntimeError):
    """Raised when a generated population fails the simulator sanity gate."""


def check_sanity_gate(outcomes_by_class: dict[RecoveryClass, list[bool]]) -> None:
    """Raise `SanityGateFailure` if `outcomes_by_class` (per-class
    `would_self_recover` draws) fails any of the R5 checks."""
    problems: list[str] = []

    rate_pct = {c: 100.0 * sum(vals) / len(vals) for c, vals in outcomes_by_class.items() if vals}

    for recovery_class, (low, high) in BAND.items():
        if recovery_class not in rate_pct:
            problems.append(f"{recovery_class}: no samples generated")
            continue
        if not (low <= rate_pct[recovery_class] <= high):
            problems.append(
                f"{recovery_class}: {rate_pct[recovery_class]:.1f}% outside band [{low}, {high}]"
            )

    if RecoveryClass.TIME_RECOVERABLE in rate_pct and RecoveryClass.ACTION_RECOVERABLE in rate_pct:
        spread = (
            rate_pct[RecoveryClass.TIME_RECOVERABLE] - rate_pct[RecoveryClass.ACTION_RECOVERABLE]
        )
        if spread < MIN_TIME_ACTION_SPREAD:
            problems.append(f"TIME - ACTION spread {spread:.1f}pp < {MIN_TIME_ACTION_SPREAD}pp")

    total = sum(len(vals) for vals in outcomes_by_class.values())
    if total > 0:
        share = {c: len(vals) / total for c, vals in outcomes_by_class.items()}
        expected_aggregate = sum(share[c] * rate_pct.get(c, 0.0) for c in RecoveryClass)
        actual_aggregate = 100.0 * sum(sum(vals) for vals in outcomes_by_class.values()) / total

        if abs(actual_aggregate - expected_aggregate) >= MAX_MIXTURE_DRIFT:
            problems.append(
                f"mixture arithmetic drift: actual {actual_aggregate:.1f}% vs "
                f"expected {expected_aggregate:.1f}%"
            )
        low, high = AGGREGATE_BAND
        if not (low <= actual_aggregate <= high):
            problems.append(
                f"aggregate {actual_aggregate:.1f}% outside plausibility band [{low}, {high}]"
            )

    if problems:
        raise SanityGateFailure("; ".join(problems))
