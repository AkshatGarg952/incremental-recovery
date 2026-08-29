"""Envelope evaluation engine — BUILD.md task 3.9.

Runs the full rule set against a proposal, and after any rule changes it,
re-runs the entire set again from the top: a quiet-hours clamp must not
create a contact-frequency breach, and a schedule-sanity clamp must not
re-open a retry-cap violation. Loops to a fixed point rather than a single
pass, bounded so a pathological proposal can't loop forever.
"""

from dataclasses import dataclass, field

from src.envelope.rules import EnvelopeContext, EnvelopeRule, RuleOutcome, Verdict
from src.envelope.schemas import ProposedPolicy

_MAX_PASSES = 10


@dataclass
class EnvelopeResult:
    approved: ProposedPolicy
    verdict: Verdict
    rules_fired: list[RuleOutcome] = field(default_factory=list)


class Envelope:
    def __init__(self, rules: list[EnvelopeRule]) -> None:
        self._rules = rules

    def evaluate(self, proposal: ProposedPolicy, context: EnvelopeContext) -> EnvelopeResult:
        current = proposal
        rules_fired: list[RuleOutcome] = []

        for _pass_number in range(_MAX_PASSES):
            changed = False

            for rule in self._rules:
                before = current
                current, outcome = rule.apply(current, context)
                if outcome.verdict != Verdict.PASS:
                    rules_fired.append(outcome)
                if current != before:
                    changed = True

            if not changed:
                break

        return EnvelopeResult(
            approved=current, verdict=_overall_verdict(rules_fired), rules_fired=rules_fired
        )


def _overall_verdict(rules_fired: list[RuleOutcome]) -> Verdict:
    if any(outcome.verdict == Verdict.BLOCKED for outcome in rules_fired):
        return Verdict.BLOCKED
    if any(outcome.verdict == Verdict.CLAMPED for outcome in rules_fired):
        return Verdict.CLAMPED
    return Verdict.PASS
