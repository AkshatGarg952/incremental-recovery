"""Suppression breakdown by envelope rule ID — BUILD.md task 8.9."""

from src.envelope.rules import RuleOutcome, Verdict


def suppression_breakdown(all_rules_fired: list[list[RuleOutcome]]) -> dict[str, int]:
    """Count how many times each rule fired with a non-pass verdict across
    the batch. `all_rules_fired` is one `EnvelopeResult.rules_fired` list
    per agent-arm failure that went through the envelope.
    """
    counts: dict[str, int] = {}
    for rules_fired in all_rules_fired:
        for outcome in rules_fired:
            if outcome.verdict != Verdict.PASS:
                counts[outcome.rule_id] = counts.get(outcome.rule_id, 0) + 1
    return counts
