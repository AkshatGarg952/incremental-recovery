"""The concrete `OutcomeResolver` — BUILD.md task 8.1.

This is the eval-only path where realized outcomes join latent ground
truth: the only place in `src/eval` allowed to import `src.simulator.latent`.
`src/agent`, `src/envelope`, and `src/executor` never see this module —
see tests/test_no_label_leak.py.

Self-recovery, retry/message responsiveness, and fatigue/churn from
excess contacts are all resolved here, behind the `OutcomeResolver`
protocol the executors already depend on.
"""

import random

from src.simulator.latent import churn_probability, remaining_recovery_probability
from src.simulator.schemas import LatentOutcome

# Base per-attempt success probability when the latent flag says this
# customer is/isn't receptive — a fixed dichotomy, not a trained model,
# consistent with the rest of the simulator's hand-set constants.
_RESPONSIVE_BASE_PROBABILITY = 0.65
_UNRESPONSIVE_BASE_PROBABILITY = 0.03


class LatentBackedResolver:
    def __init__(self, latent_outcomes: dict[str, LatentOutcome], seed: int) -> None:
        self._latent_outcomes = latent_outcomes
        self._rng = random.Random(seed)
        self._churned: set[str] = set()
        self._retry_draws: dict[tuple[str, int], bool] = {}
        self._contact_draws: dict[tuple[str, int], bool] = {}

    def recovered_by(
        self,
        failure_id: str,
        at_hours: float,
        retries_attempted: int,
        contacts_made: int,
    ) -> bool:
        if failure_id in self._churned:
            return False

        outcome = self._latent_outcomes[failure_id]

        if outcome.would_self_recover and outcome.self_recovery_delay_hours <= at_hours:
            return True

        for index in range(1, retries_attempted + 1):
            if self._retry_succeeds(failure_id, outcome, index):
                return True

        for index in range(1, contacts_made + 1):
            if self._contact_succeeds(failure_id, outcome, index):
                return True

        return False

    def churned_failure_ids(self) -> frozenset[str]:
        return frozenset(self._churned)

    def _retry_succeeds(self, failure_id: str, outcome: LatentOutcome, index: int) -> bool:
        key = (failure_id, index)
        if key not in self._retry_draws:
            base = (
                _RESPONSIVE_BASE_PROBABILITY
                if outcome.responds_to_retry
                else _UNRESPONSIVE_BASE_PROBABILITY
            )
            self._retry_draws[key] = self._rng.random() < base
        return self._retry_draws[key]

    def _contact_succeeds(self, failure_id: str, outcome: LatentOutcome, index: int) -> bool:
        key = (failure_id, index)
        if key not in self._contact_draws:
            base = (
                _RESPONSIVE_BASE_PROBABILITY
                if outcome.responds_to_message
                else _UNRESPONSIVE_BASE_PROBABILITY
            )
            probability = remaining_recovery_probability(outcome, index, base)
            self._contact_draws[key] = self._rng.random() < probability

            if index > outcome.fatigue_threshold and failure_id not in self._churned:
                # Fatigue with teeth (BUILD.md R6): each contact past the
                # threshold independently risks churn, priced from ltv_paise
                # in the money report, not just a probability decay.
                cumulative_before = churn_probability(outcome, index - 1)
                cumulative_after = churn_probability(outcome, index)
                marginal_churn_prob = cumulative_after - cumulative_before
                if self._rng.random() < marginal_churn_prob:
                    self._churned.add(failure_id)

        return self._contact_draws[key]
