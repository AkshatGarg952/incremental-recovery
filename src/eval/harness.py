"""Batch run orchestrator — classify -> propose -> envelope -> execute per
failure, arm-dispatched.

Not itself a numbered BUILD.md task; it is the connective tissue tasks
8.1-8.11 need to have real data to report on. Classification runs on every
arm (task 5.6); only the agent arm's proposal goes through the policy
agent and envelope. Unparseable policy output — or no usable
classification at all — falls back to the same fixed schedule the
baseline arm runs, per BUILD.md task 6.5 and R9's provider-outage note.
"""

from dataclasses import dataclass, field

from src.agent.classifier import classify_failure
from src.agent.policy import propose_policy
from src.envelope.config import build_default_envelope
from src.envelope.rules import EnvelopeContext, RuleOutcome
from src.envelope.schemas import ProposedPolicy, RetryStep
from src.eval.exception_list import ExceptionEntry
from src.eval.outcome_resolver import LatentBackedResolver
from src.eval.outcome_store import OutcomeStore, build_outcome_record
from src.eval.schemas import Arm
from src.executor.agent_executor import AgentExecutor
from src.executor.baseline_executor import BaselineExecutor
from src.executor.clock import SimulatedClock
from src.executor.holdout_observer import HoldoutObserver
from src.executor.ledger import Ledger
from src.llm.client import ChatClient
from src.simulator.schemas import LatentOutcome, PaymentFailure, RecoveryClass

_BASELINE_STYLE_RETRY_HOURS = (24, 48, 72)


def _baseline_style_proposal(
    failure: PaymentFailure, recovery_class: RecoveryClass
) -> ProposedPolicy:
    """The fixed fallback used when the agent arm has no usable proposal —
    either the classifier fell to the exception list, or the policy
    output was unparseable after bounded retries (BUILD.md task 6.5).
    """
    return ProposedPolicy(
        failure_id=failure.failure_id,
        recovery_class=recovery_class,
        should_retry=True,
        should_contact=False,
        retry_schedule=[
            RetryStep(delay_hours=h, route_hint="same", reason="fallback to baseline behaviour")
            for h in _BASELINE_STYLE_RETRY_HOURS
        ],
        customer_message=None,
        predicted_uplift=0.0,
        rationale="fallback to baseline behaviour",
        confidence=0.0,
    )


@dataclass
class BatchRunResult:
    store: OutcomeStore
    rules_fired_by_failure: dict[str, list[RuleOutcome]] = field(default_factory=dict)
    exceptions: list[ExceptionEntry] = field(default_factory=list)
    churned_failure_ids: frozenset[str] = frozenset()


def run_batch(
    failures: list[PaymentFailure],
    assignment: dict[str, Arm],
    latent_outcomes: dict[str, LatentOutcome],
    client: ChatClient,
    classify_model: str,
    policy_model: str,
    ledger: Ledger,
    clock: SimulatedClock,
    seed: int,
    economics_config: dict,
) -> BatchRunResult:
    resolver = LatentBackedResolver(latent_outcomes, seed=seed)
    envelope = build_default_envelope()

    agent_executor = AgentExecutor(ledger, clock, resolver)
    baseline_executor = BaselineExecutor(ledger, clock, resolver)
    holdout_observer = HoldoutObserver(ledger, clock, resolver)

    store = OutcomeStore()
    rules_fired_by_failure: dict[str, list[RuleOutcome]] = {}
    exceptions: list[ExceptionEntry] = []

    for failure in failures:
        arm = assignment[failure.failure_id]

        classification = classify_failure(failure, client, classify_model)
        recovery_class = classification.recovery_class
        if recovery_class is None:
            exceptions.append(
                ExceptionEntry(failure.failure_id, "classify", classification.rationale)
            )

        contact_cost_paise = 0

        if arm == "agent":
            effective_class = recovery_class or RecoveryClass.ACTION_RECOVERABLE
            proposal_result = propose_policy(
                failure, effective_class, client, policy_model, economics_config
            )

            if proposal_result.proposal is None:
                if proposal_result.fallback_outcome is not None:
                    exceptions.append(
                        ExceptionEntry(
                            failure.failure_id, "propose", proposal_result.fallback_outcome.detail
                        )
                    )
                raw_proposal = _baseline_style_proposal(failure, effective_class)
            else:
                raw_proposal = proposal_result.proposal

            context = EnvelopeContext(
                failure=failure,
                now=clock.now(),
                attempts_used=0,
                contacts_used_7d=failure.context.contacts_last_7d,
                consent_channels=frozenset(failure.context.consent_channels),
            )
            envelope_result = envelope.evaluate(raw_proposal, context)
            rules_fired_by_failure[failure.failure_id] = envelope_result.rules_fired

            approved = envelope_result.approved
            result = agent_executor.execute(failure, approved, arm="agent")

            if (
                approved.should_contact
                and approved.customer_message is not None
                and result.contacts_made > 0
            ):
                cost_per_contact = economics_config["contact_cost_paise"][
                    approved.customer_message.channel
                ]
                contact_cost_paise = cost_per_contact * result.contacts_made

        elif arm == "baseline":
            result = baseline_executor.execute(failure)
        else:
            result = holdout_observer.execute(failure)

        record = build_outcome_record(
            failure,
            result,
            recovery_class,
            latent_outcomes[failure.failure_id].would_self_recover,
            contact_cost_paise,
        )
        store.add(record)

    return BatchRunResult(
        store=store,
        rules_fired_by_failure=rules_fired_by_failure,
        exceptions=exceptions,
        churned_failure_ids=resolver.churned_failure_ids(),
    )
