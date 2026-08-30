"""Build evals/golden_set.jsonl — BUILD.md task 5.7.

Selects 30 cases from a generated batch: half are DO_NOT_HONOR (the
ambiguous code the classifier actually earns its place on), the other half
stratified across the four recovery classes via their "clean" decline codes,
so every class is represented. Each case is labeled with the generator's
ground-truth recovery class as the "hand checked" answer.

Run: uv run python scripts/build_golden_set.py
"""

import json
import random
from pathlib import Path

from src.simulator.decline_codes import DECLINE_CODE_CLASS
from src.simulator.generator import GeneratedBatch, generate_batch
from src.simulator.schemas import PaymentFailure, RecoveryClass

_SEED = 20260901
_BATCH_N = 3000
_TOTAL_CASES = 30
_AMBIGUOUS_CASES = 15
# No decline code cleanly maps to ROUTE_RECOVERABLE (BUILD.md R1: GATEWAY_TIMEOUT
# is TIME/ROUTE-ambiguous and mapped to TIME here) — every ROUTE failure shows an
# ambiguous code. Reserve a few ambiguous slots by ground truth so the golden set
# still exercises ROUTE rather than leaving it to chance.
_GUARANTEED_AMBIGUOUS_ROUTE_CASES = 3
_CLEAN_CLASS_TARGETS: dict[RecoveryClass, int] = {
    RecoveryClass.ACTION_RECOVERABLE: 5,
    RecoveryClass.TIME_RECOVERABLE: 5,
    RecoveryClass.DEAD: 5,
}
_OUT_PATH = Path("evals/golden_set.jsonl")


def _select_cases(batch: GeneratedBatch, rng: random.Random) -> list[PaymentFailure]:
    ambiguous = [f for f in batch.failures if DECLINE_CODE_CLASS.get(f.decline_code) is None]

    route_ambiguous = [
        f
        for f in ambiguous
        if batch.recovery_classes[f.failure_id] == RecoveryClass.ROUTE_RECOVERABLE
    ]
    rng.shuffle(route_ambiguous)
    selected = route_ambiguous[:_GUARANTEED_AMBIGUOUS_ROUTE_CASES]

    remaining_ambiguous = [f for f in ambiguous if f not in selected]
    rng.shuffle(remaining_ambiguous)
    selected += remaining_ambiguous[: _AMBIGUOUS_CASES - len(selected)]

    for recovery_class, target in _CLEAN_CLASS_TARGETS.items():
        pool = [
            f
            for f in batch.failures
            if DECLINE_CODE_CLASS.get(f.decline_code) == recovery_class and f not in selected
        ]
        rng.shuffle(pool)
        selected.extend(pool[:target])

    rng.shuffle(selected)
    return selected


def main() -> None:
    batch = generate_batch(n=_BATCH_N, seed=_SEED)
    rng = random.Random(_SEED)

    selected = _select_cases(batch, rng)
    assert len(selected) == _TOTAL_CASES, f"expected {_TOTAL_CASES} cases, got {len(selected)}"

    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _OUT_PATH.open("w", encoding="utf-8") as handle:
        for failure in selected:
            gold = batch.recovery_classes[failure.failure_id]
            row = {"failure": failure.model_dump(mode="json"), "gold_recovery_class": gold.value}
            handle.write(json.dumps(row) + "\n")

    print(f"wrote {len(selected)} golden cases to {_OUT_PATH}")


if __name__ == "__main__":
    main()
