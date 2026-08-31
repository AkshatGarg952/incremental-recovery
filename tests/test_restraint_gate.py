"""BUILD GATE — restraint pays (BUILD.md task 8.14, gate R6).

    assert gross(spam) >= gross(agent)   # spam recovers more, as it should
    assert net(spam)   <  net(agent)     # and still loses, once fatigue is priced

A deliberately naive maximal-contact agent is replayed as a counterfactual
on the exact same seed and population as a restrained agent that contacts
at most once, gated by the uplift-driven contact stopping rule (BUILD.md
task 6.3). If this fails, fatigue has no teeth (task 1.5) or churn pricing
is too small, and "recovery net of the cost of chasing" has no number
behind it.

Both agents use the same retry behavior (retries are cheap and
unconditional per R7 — that's not what this gate is about) and the same
direct resolver loop as the spam module, so the *only* variable is contact
repetition and its economic gate — isolating exactly the mechanism R6
describes, with no confound from unrelated stopping-rule differences.
"""

from src.agent.policy import contact_is_worth_it, load_economics_config
from src.eval.outcome_resolver import LatentBackedResolver
from src.eval.outcome_store import OutcomeStore, build_outcome_record
from src.eval.spam import run_spam_counterfactual
from src.executor.outcomes import RECOVERY_HORIZON_HOURS
from src.executor.result import ExecutionResult
from src.simulator.generator import generate_batch
from src.simulator.schemas import PaymentFailure, RecoveryClass

_SEED = 20260901
_N = 3000
_RETRY_ATTEMPTS = 4

# Same heuristic across both agents — the difference under test is contact
# repetition and its economic gate, not the uplift estimate itself.
_HEURISTIC_UPLIFT = {
    RecoveryClass.ACTION_RECOVERABLE: 0.35,
    RecoveryClass.TIME_RECOVERABLE: 0.20,
    RecoveryClass.ROUTE_RECOVERABLE: 0.20,
    RecoveryClass.DEAD: 0.0,
}


def _run_restrained_one(failure: PaymentFailure, recovery_class, resolver, economics):
    if recovery_class == RecoveryClass.DEAD:
        return (
            ExecutionResult(failure.failure_id, "agent", False, None, 0, 0),
            0,
        )

    channel = next(iter(sorted(failure.context.consent_channels)), None)
    uplift = _HEURISTIC_UPLIFT[recovery_class]

    retries_attempted = 0
    contacts_made = 0
    recovered = False
    recovered_at_hours = None

    for hour in range(1, _RETRY_ATTEMPTS + 1):
        if resolver.recovered_by(failure.failure_id, float(hour), retries_attempted, contacts_made):
            recovered, recovered_at_hours = True, float(hour)
            break
        retries_attempted += 1

    contact_cost_paise = 0
    if (
        not recovered
        and channel is not None
        and contact_is_worth_it(uplift, failure.amount_paise, channel, economics)
    ):
        hour = float(_RETRY_ATTEMPTS + 1)
        if not resolver.recovered_by(failure.failure_id, hour, retries_attempted, contacts_made):
            contacts_made = 1
            contact_cost_paise = economics["contact_cost_paise"][channel]

    if not recovered:
        recovered = resolver.recovered_by(
            failure.failure_id, RECOVERY_HORIZON_HOURS, retries_attempted, contacts_made
        )
        if recovered:
            recovered_at_hours = RECOVERY_HORIZON_HOURS

    result = ExecutionResult(
        failure_id=failure.failure_id,
        arm="agent",
        recovered=recovered,
        recovered_at_hours=recovered_at_hours,
        retries_made=retries_attempted,
        contacts_made=contacts_made,
    )
    return result, contact_cost_paise


def _run_restrained_agent(batch, economics: dict) -> tuple[OutcomeStore, frozenset[str]]:
    resolver = LatentBackedResolver(batch.latent_outcomes, seed=_SEED)
    store = OutcomeStore()

    for failure in batch.failures:
        recovery_class = batch.recovery_classes[failure.failure_id]
        result, contact_cost = _run_restrained_one(failure, recovery_class, resolver, economics)
        store.add(
            build_outcome_record(
                failure,
                result,
                recovery_class,
                batch.latent_outcomes[failure.failure_id].would_self_recover,
                contact_cost,
            )
        )

    return store, resolver.churned_failure_ids()


def _net_value(records, churned_failure_ids, latent_outcomes) -> int:
    gross = sum(r.amount_paise for r in records if r.recovered)
    contact_cost = sum(r.contact_cost_paise for r in records)
    record_ids = {r.failure_id for r in records}
    churn_cost = sum(
        latent_outcomes[fid].ltv_paise for fid in churned_failure_ids if fid in record_ids
    )
    return gross - contact_cost - churn_cost


def test_spam_agent_wins_gross_but_loses_net():
    batch = generate_batch(n=_N, seed=_SEED)
    economics = load_economics_config()

    agent_store, agent_churned = _run_restrained_agent(batch, economics)
    spam_result = run_spam_counterfactual(
        batch.failures,
        batch.recovery_classes,
        batch.latent_outcomes,
        seed=_SEED,
        economics_config=economics,
    )

    agent_records = agent_store.by_arm("agent")
    spam_records = spam_result.store.by_arm("agent")

    gross_agent = sum(r.amount_paise for r in agent_records if r.recovered)
    gross_spam = sum(r.amount_paise for r in spam_records if r.recovered)

    net_agent = _net_value(agent_records, agent_churned, batch.latent_outcomes)
    net_spam = _net_value(spam_records, spam_result.churned_failure_ids, batch.latent_outcomes)

    contacts_agent = sum(r.contacts_made for r in agent_records)
    contacts_spam = sum(r.contacts_made for r in spam_records)

    # THE thesis, as an assertion (BUILD.md R6).
    assert gross_spam >= gross_agent
    assert net_spam < net_agent

    # And it should be true for the reason the gate claims, not by accident.
    assert contacts_spam > contacts_agent
    assert len(spam_result.churned_failure_ids) > 0
    assert len(agent_churned) < len(spam_result.churned_failure_ids)
