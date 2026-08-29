"""Render a human-readable distribution summary for a generated batch —
BUILD.md task 2.9, the artifact the panel can read without running anything.
"""

from collections import Counter

from src.simulator.generator import GeneratedBatch
from src.simulator.schemas import RecoveryClass


def _self_recovery_pct(outcomes: list[bool]) -> float:
    return 100.0 * sum(outcomes) / max(len(outcomes), 1)


def render_distribution_summary(batch: GeneratedBatch) -> str:
    n = len(batch.failures)
    method_counts = Counter(f.method for f in batch.failures)
    decline_counts = Counter(f.decline_code for f in batch.failures)
    class_counts = Counter(batch.recovery_classes.values())

    self_recovery_by_class: dict[RecoveryClass, list[bool]] = {c: [] for c in RecoveryClass}
    for failure_id, outcome in batch.latent_outcomes.items():
        self_recovery_by_class[batch.recovery_classes[failure_id]].append(
            outcome.would_self_recover
        )

    lines = [
        f"# Reference batch distribution summary (N={n})",
        "",
        "## Method",
        *(
            f"- {method}: {count} ({100 * count / n:.1f}%)"
            for method, count in method_counts.most_common()
        ),
        "",
        "## Decline code",
        *(
            f"- {code}: {count} ({100 * count / n:.1f}%)"
            for code, count in decline_counts.most_common()
        ),
        "",
        "## Recovery class (ground truth, holdout only — not used by the agent)",
        *(
            f"- {cls.value}: {count} ({100 * count / n:.1f}%), "
            f"self-recovery {_self_recovery_pct(self_recovery_by_class[cls]):.1f}%"
            for cls, count in class_counts.most_common()
        ),
    ]
    return "\n".join(lines) + "\n"
