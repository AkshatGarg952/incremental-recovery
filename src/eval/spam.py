"""The spam agent — BUILD.md task 8.14, gate R6 (restraint pays).

A deliberately naive strategy that retries maximally and keeps contacting
well past where any real policy proposal would stop, run as a
counterfactual replay on the same seed and population as the real agent
arm — no extra randomised arm, so no statistical power cost.

`ProposedPolicy` carries at most one message, so a real proposal can never
even express "keep messaging" — which is exactly the repeated-contact
fatigue dynamic BUILD.md R6 is about. Spam is deliberately not
schema-constrained: it drives the resolver directly, attempting several
contacts per failure instead of the one message a real policy could ever
propose. DEAD class and channel consent are still respected — those are
compliance facts, not economics.

    assert gross(spam) >= gross(agent)   # spam recovers more, as it should
    assert net(spam)   <  net(agent)     # and still loses, once fatigue is priced
"""

from dataclasses import dataclass

from src.eval.outcome_resolver import LatentBackedResolver
from src.eval.outcome_store import OutcomeStore, build_outcome_record
from src.executor.outcomes import RECOVERY_HORIZON_HOURS
from src.executor.result import ExecutionResult
from src.simulator.schemas import LatentOutcome, PaymentFailure, RecoveryClass

_SPAM_RETRY_ATTEMPTS = 4
_SPAM_CONTACT_ATTEMPTS = 6  # comfortably past the simulator's default fatigue_threshold (3)


@dataclass
class SpamRunResult:
    store: OutcomeStore
    churned_failure_ids: frozenset[str]


def run_spam_counterfactual(
    failures: list[PaymentFailure],
    recovery_classes: dict[str, RecoveryClass],
    latent_outcomes: dict[str, LatentOutcome],
    seed: int,
    economics_config: dict,
) -> SpamRunResult:
    """Replay `failures` (the agent arm's own population) through the spam
    strategy, on a fresh resolver seeded identically to the real run — same
    seed and population, independent state, so nothing here leaks into or
    is contaminated by the real agent-arm execution.
    """
    resolver = LatentBackedResolver(latent_outcomes, seed=seed)
    store = OutcomeStore()

    for failure in failures:
        recovery_class = recovery_classes[failure.failure_id]
        result, contact_cost_paise = _run_one(failure, recovery_class, resolver, economics_config)
        store.add(
            build_outcome_record(
                failure,
                result,
                recovery_class,
                latent_outcomes[failure.failure_id].would_self_recover,
                contact_cost_paise,
            )
        )

    return SpamRunResult(store=store, churned_failure_ids=resolver.churned_failure_ids())


def _run_one(
    failure: PaymentFailure,
    recovery_class: RecoveryClass,
    resolver: LatentBackedResolver,
    economics_config: dict,
) -> tuple[ExecutionResult, int]:
    if recovery_class == RecoveryClass.DEAD:
        result = ExecutionResult(
            failure_id=failure.failure_id,
            arm="agent",
            recovered=False,
            recovered_at_hours=None,
            retries_made=0,
            contacts_made=0,
        )
        return result, 0

    channel = next(iter(sorted(failure.context.consent_channels)), None)

    retries_attempted = 0
    contacts_made = 0
    recovered = False
    recovered_at_hours: float | None = None

    # Retries first, cheap and unconditional (BUILD.md R7): spam ignores
    # the mandate-cap/decline-rate economics, not just the contact economics.
    for hour in range(1, _SPAM_RETRY_ATTEMPTS + 1):
        if resolver.recovered_by(failure.failure_id, float(hour), retries_attempted, contacts_made):
            recovered, recovered_at_hours = True, float(hour)
            break
        retries_attempted += 1

    if not recovered and channel is not None:
        for offset in range(1, _SPAM_CONTACT_ATTEMPTS + 1):
            hour = float(_SPAM_RETRY_ATTEMPTS + offset)
            if resolver.recovered_by(failure.failure_id, hour, retries_attempted, contacts_made):
                recovered, recovered_at_hours = True, hour
                break
            contacts_made += 1

    if not recovered:
        recovered = resolver.recovered_by(
            failure.failure_id, RECOVERY_HORIZON_HOURS, retries_attempted, contacts_made
        )
        if recovered:
            recovered_at_hours = RECOVERY_HORIZON_HOURS

    contact_cost_paise = 0
    if channel is not None and contacts_made > 0:
        contact_cost_paise = economics_config["contact_cost_paise"][channel] * contacts_made

    result = ExecutionResult(
        failure_id=failure.failure_id,
        arm="agent",
        recovered=recovered,
        recovered_at_hours=recovered_at_hours,
        retries_made=retries_attempted,
        contacts_made=contacts_made,
    )
    return result, contact_cost_paise
