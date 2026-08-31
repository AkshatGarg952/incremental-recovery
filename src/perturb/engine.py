"""Perturbation engine — BUILD.md task 9.1.

Three kinds of live injection into an already-generated batch: an issuer
outage, a clock shift, and a spike in a specific decline code's incidence.
These are recovery-queue failures awaiting action, not settled history —
"HDFC is down right now" means every pending HDFC failure in the queue is
affected, not just ones that happened to fail in a literal historical
time window (which, spread over a 30-day batch, would almost never land
the ~20-50 rows a demo needs).
"""

import random
from dataclasses import dataclass, field

from src.executor.clock import SimulatedClock
from src.simulator.schemas import PaymentFailure

_DEFAULT_MAX_AFFECTED = 40


@dataclass
class PerturbationResult:
    description: str
    affected_failure_ids: list[str]
    original_by_id: dict[str, PaymentFailure]
    perturbed_by_id: dict[str, PaymentFailure] = field(default_factory=dict)


def _outage_message(issuer_code: str, duration_hours: float) -> str:
    minutes = round(duration_hours * 60)
    return f"Issuer or switch is inoperative — {issuer_code} outage, ~{minutes} min"


def apply_issuer_outage(
    failures: list[PaymentFailure],
    issuer_code: str,
    duration_hours: float,
    max_affected: int = _DEFAULT_MAX_AFFECTED,
) -> PerturbationResult:
    """Every pending failure for `issuer_code`, up to `max_affected`, gets
    forced to `ISSUER_DOWN` with a message naming the live outage.
    """
    matching = [f for f in failures if f.issuer_code == issuer_code][:max_affected]

    original_by_id = {f.failure_id: f for f in matching}
    perturbed_by_id = {
        f.failure_id: f.model_copy(
            update={
                "decline_code": "ISSUER_DOWN",
                "decline_message_raw": _outage_message(issuer_code, duration_hours),
            }
        )
        for f in matching
    }

    return PerturbationResult(
        description=f"{issuer_code} outage for {duration_hours:.2f}h",
        affected_failure_ids=list(original_by_id),
        original_by_id=original_by_id,
        perturbed_by_id=perturbed_by_id,
    )


def apply_decline_spike(
    failures: list[PaymentFailure],
    decline_code: str,
    max_affected: int = _DEFAULT_MAX_AFFECTED,
    seed: int = 0,
) -> PerturbationResult:
    """A random slice of the queue suddenly shows `decline_code` instead of
    whatever it originally had — e.g. a sudden spike in `INSUFFICIENT_FUNDS`
    around an unmodeled event.
    """
    rng = random.Random(seed)
    candidates = [f for f in failures if f.decline_code != decline_code]
    rng.shuffle(candidates)
    matching = candidates[:max_affected]

    original_by_id = {f.failure_id: f for f in matching}
    perturbed_by_id = {
        f.failure_id: f.model_copy(update={"decline_code": decline_code}) for f in matching
    }

    return PerturbationResult(
        description=f"decline-code spike: {decline_code}",
        affected_failure_ids=list(original_by_id),
        original_by_id=original_by_id,
        perturbed_by_id=perturbed_by_id,
    )


def apply_clock_shift(clock: SimulatedClock, delta_hours: float) -> None:
    """Fast-forward (or rewind, with a negative delta) the simulated clock
    — e.g. "let's jump 3 days ahead and see who's recovered by then."
    """
    clock.advance_hours(delta_hours)
