"""Re-plan the affected slice and print decision diffs — BUILD.md task 9.3.

Classifies and proposes a policy for each affected failure both before and
after a perturbation, so the change in decision is visible side by side —
the "hand the judge the keyboard" moment.
"""

from dataclasses import dataclass

from src.agent.classifier import classify_failure
from src.agent.policy import propose_policy
from src.llm.client import ChatClient
from src.simulator.schemas import PaymentFailure, RecoveryClass


@dataclass
class DecisionDiff:
    failure_id: str
    before_decline_code: str
    after_decline_code: str
    before_recovery_class: RecoveryClass | None
    after_recovery_class: RecoveryClass | None
    before_should_retry: bool | None
    before_should_contact: bool | None
    after_should_retry: bool | None
    after_should_contact: bool | None

    @property
    def changed(self) -> bool:
        return (
            self.before_recovery_class != self.after_recovery_class
            or self.before_should_retry != self.after_should_retry
            or self.before_should_contact != self.after_should_contact
        )


def _plan_one(
    failure: PaymentFailure,
    classify_client: ChatClient,
    classify_model: str,
    policy_client: ChatClient,
    policy_model: str,
    economics_config: dict,
) -> tuple[RecoveryClass | None, bool | None, bool | None]:
    classification = classify_failure(failure, classify_client, classify_model)
    recovery_class = classification.recovery_class
    if recovery_class is None:
        return None, None, None

    proposal_result = propose_policy(
        failure, recovery_class, policy_client, policy_model, economics_config
    )
    if proposal_result.proposal is None:
        return recovery_class, None, None

    return (
        recovery_class,
        proposal_result.proposal.should_retry,
        proposal_result.proposal.should_contact,
    )


def replan_affected_failures(
    original_by_id: dict[str, PaymentFailure],
    perturbed_by_id: dict[str, PaymentFailure],
    classify_client: ChatClient,
    classify_model: str,
    policy_client: ChatClient,
    policy_model: str,
    economics_config: dict,
) -> list[DecisionDiff]:
    diffs = []
    for failure_id, original in original_by_id.items():
        perturbed = perturbed_by_id[failure_id]

        before_class, before_retry, before_contact = _plan_one(
            original, classify_client, classify_model, policy_client, policy_model, economics_config
        )
        after_class, after_retry, after_contact = _plan_one(
            perturbed,
            classify_client,
            classify_model,
            policy_client,
            policy_model,
            economics_config,
        )

        diffs.append(
            DecisionDiff(
                failure_id=failure_id,
                before_decline_code=original.decline_code,
                after_decline_code=perturbed.decline_code,
                before_recovery_class=before_class,
                after_recovery_class=after_class,
                before_should_retry=before_retry,
                before_should_contact=before_contact,
                after_should_retry=after_retry,
                after_should_contact=after_contact,
            )
        )

    return diffs


def _label(recovery_class: RecoveryClass | None, retry: bool | None, contact: bool | None) -> str:
    class_label = recovery_class.value if recovery_class is not None else "exception"
    return f"class={class_label:8s} retry={retry!s:5s} contact={contact!s:5s}"


def render_decision_diffs(diffs: list[DecisionDiff]) -> str:
    lines = ["DECISION DIFFS", ""]
    changed = 0
    for diff in diffs:
        if diff.changed:
            changed += 1
        marker = "  <- CHANGED" if diff.changed else ""
        lines.append(
            f"  {diff.failure_id}: {diff.before_decline_code} -> {diff.after_decline_code}"
        )
        before_label = _label(
            diff.before_recovery_class, diff.before_should_retry, diff.before_should_contact
        )
        after_label = _label(
            diff.after_recovery_class, diff.after_should_retry, diff.after_should_contact
        )
        lines.append(f"    before: {before_label}")
        lines.append(f"    after:  {after_label}{marker}")
    lines.append("")
    lines.append(f"{changed}/{len(diffs)} decisions changed")
    return "\n".join(lines)
