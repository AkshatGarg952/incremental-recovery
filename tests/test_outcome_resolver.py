"""Offline tests for the latent-backed outcome resolver (BUILD.md task 8.1)."""

from src.eval.outcome_resolver import LatentBackedResolver
from src.simulator.schemas import LatentOutcome


def _outcome(**overrides) -> LatentOutcome:
    defaults = dict(
        would_self_recover=False,
        self_recovery_delay_hours=999.0,
        responds_to_retry=False,
        responds_to_message=False,
        fatigue_threshold=3,
        fatigue_decay_per_contact=0.5,
        churn_prob_per_excess_contact=0.3,
        ltv_paise=100_000,
    )
    defaults.update(overrides)
    return LatentOutcome(**defaults)


def test_self_recovery_is_observed_only_once_the_delay_has_elapsed():
    outcome = _outcome(would_self_recover=True, self_recovery_delay_hours=10.0)
    resolver = LatentBackedResolver({"f1": outcome}, seed=1)

    assert resolver.recovered_by("f1", at_hours=5.0, retries_attempted=0, contacts_made=0) is False
    assert resolver.recovered_by("f1", at_hours=10.0, retries_attempted=0, contacts_made=0) is True


def test_never_recovers_with_no_self_recovery_and_no_actions():
    outcome = _outcome()
    resolver = LatentBackedResolver({"f1": outcome}, seed=1)

    assert (
        resolver.recovered_by("f1", at_hours=1000.0, retries_attempted=0, contacts_made=0) is False
    )


def test_responsive_customers_recover_much_more_often_via_retry():
    responsive = _outcome(responds_to_retry=True)
    unresponsive = _outcome(responds_to_retry=False)

    def recovery_rate(outcome, seed_range):
        hits = 0
        for seed in seed_range:
            resolver = LatentBackedResolver({"f1": outcome}, seed=seed)
            if resolver.recovered_by("f1", at_hours=10.0, retries_attempted=1, contacts_made=0):
                hits += 1
        return hits / len(seed_range)

    seeds = range(500)
    responsive_rate = recovery_rate(responsive, seeds)
    unresponsive_rate = recovery_rate(unresponsive, seeds)

    assert responsive_rate > 0.4
    assert unresponsive_rate < 0.1
    assert responsive_rate > unresponsive_rate


def test_recovered_by_is_consistent_across_repeated_calls_same_state():
    """The same (failure_id, index) draw must not flip-flop across calls —
    otherwise a batch that checks recovery at multiple checkpoints would
    see a failure "un-recover"."""
    outcome = _outcome(responds_to_retry=True)
    resolver = LatentBackedResolver({"f1": outcome}, seed=7)

    first = resolver.recovered_by("f1", at_hours=5.0, retries_attempted=1, contacts_made=0)
    second = resolver.recovered_by("f1", at_hours=5.0, retries_attempted=1, contacts_made=0)

    assert first == second


def test_fatigue_reduces_the_marginal_success_probability_of_a_later_contact():
    """BUILD.md R6 — fatigue must affect outcomes, not just decisions.

    `recovered_by` checks *cumulative* success across every contact made so
    far, which only ever goes up with more attempts — that's not where
    fatigue shows up. Fatigue decays each contact's own *marginal*
    probability (`remaining_recovery_probability`), so it has to be
    measured in isolation, one fresh resolver per trial.
    """
    outcome = _outcome(responds_to_message=True, fatigue_threshold=1, fatigue_decay_per_contact=0.1)

    def marginal_success_rate(contact_index, seed_range):
        hits = 0
        for seed in seed_range:
            resolver = LatentBackedResolver({"f1": outcome}, seed=seed)
            if resolver._contact_succeeds("f1", outcome, contact_index):
                hits += 1
        return hits / len(seed_range)

    seeds = range(500)
    rate_at_threshold = marginal_success_rate(1, seeds)  # excess contacts = 0, undecayed
    rate_well_past_threshold = marginal_success_rate(4, seeds)  # excess contacts = 3

    assert rate_well_past_threshold < rate_at_threshold * 0.5


def test_churn_can_occur_after_excess_contacts_and_then_blocks_recovery():
    outcome = _outcome(
        responds_to_message=True,
        fatigue_threshold=0,
        churn_prob_per_excess_contact=0.9,
    )
    resolver = LatentBackedResolver({"f1": outcome}, seed=3)

    # Drive enough contacts that churn is overwhelmingly likely.
    for contacts in range(1, 6):
        resolver.recovered_by("f1", at_hours=1.0, retries_attempted=0, contacts_made=contacts)

    assert "f1" in resolver.churned_failure_ids()
    assert (
        resolver.recovered_by("f1", at_hours=1000.0, retries_attempted=0, contacts_made=10) is False
    )


def test_retries_never_trigger_fatigue_or_churn():
    """Only contacts (messages) carry fatigue/churn risk — retries are
    silent and cheap (BUILD.md R6/R7)."""
    outcome = _outcome(
        responds_to_retry=True, fatigue_threshold=0, churn_prob_per_excess_contact=1.0
    )
    resolver = LatentBackedResolver({"f1": outcome}, seed=3)

    for retries in range(1, 10):
        resolver.recovered_by("f1", at_hours=1.0, retries_attempted=retries, contacts_made=0)

    assert resolver.churned_failure_ids() == frozenset()
