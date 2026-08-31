"""BUILD GATE — baseline invariant (BUILD.md task 8.4): retrying cannot
beat doing nothing. `rate(baseline) < rate(holdout)` means something in the
generator or executor is wrong, and the batch must fail loudly rather than
report a nonsensical number.
"""

from src.eval.lift import LiftReport


class BaselineInvariantViolation(RuntimeError):
    pass


def check_baseline_invariant(lift: LiftReport) -> None:
    if lift.rate_baseline < lift.rate_holdout:
        raise BaselineInvariantViolation(
            f"baseline rate {lift.rate_baseline:.4f} < holdout rate {lift.rate_holdout:.4f} — "
            "a fixed retry schedule must never underperform doing nothing"
        )
