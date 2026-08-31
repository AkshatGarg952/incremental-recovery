"""Policy agent — BUILD.md tasks 6.1-6.6.

An LLM proposes a `ProposedPolicy`; two deterministic stopping rules (contact
economics, retry mandate cap + decline-rate penalty) bound what it proposed
regardless of what the model said. Unparseable output falls back to
baseline behaviour rather than crashing the batch, logged via
`ENV_SCHEMA_VALID`. The envelope (Phase 3) is the actual safety/compliance
layer; these stopping rules are the model's own economics.

`ProposedPolicy` / `RetryStep` / `MessageSpec` (task 6.1's schemas) already
live in `src/envelope/schemas.py` — built in Phase 3, since the envelope
needed them to validate against before this module existed.

Never imports `src.simulator.latent` — see tests/test_no_label_leak.py.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml
from pydantic import BaseModel

from src.envelope.rules import RuleOutcome, SchemaValidRule
from src.envelope.schemas import ProposedPolicy
from src.llm.client import ChatClient, ChatMessage, ChatRequest
from src.llm.structured import StructuredParseError, parse_structured
from src.simulator.schemas import PaymentFailure, RecoveryClass

_DEFAULT_PROMPT_DIR = Path("prompts")
_DEFAULT_ECONOMICS_PATH = Path("config/economics.yaml")


def load_economics_config(path: str | Path = _DEFAULT_ECONOMICS_PATH) -> dict:
    with open(path) as handle:
        return yaml.safe_load(handle)


class UpliftLogEntry(BaseModel):
    """One row of calibration data: logged predicted_uplift per failure,
    joined against realized outcomes later (BUILD.md task 6.6, R7)."""

    failure_id: str
    recovery_class: RecoveryClass
    predicted_uplift: float
    confidence: float


def build_uplift_log_entry(proposal: ProposedPolicy) -> UpliftLogEntry:
    return UpliftLogEntry(
        failure_id=proposal.failure_id,
        recovery_class=proposal.recovery_class,
        predicted_uplift=proposal.predicted_uplift,
        confidence=proposal.confidence,
    )


def contact_is_worth_it(
    predicted_uplift: float, recoverable_amount_paise: int, channel: str, economics_config: dict
) -> bool:
    """`predicted_uplift x recoverable_amount > contact_cost(channel)` (R7)."""
    cost = economics_config["contact_cost_paise"][channel]
    return predicted_uplift * recoverable_amount_paise > cost


def retry_is_worth_it(
    recovery_class: RecoveryClass,
    predicted_uplift: float,
    attempts_used: int,
    economics_config: dict,
) -> bool:
    """Bounded by mandate cap and decline-rate penalty, not rupee cost — a
    retry costs approximately zero rupees, so an uplift-vs-cost rule alone
    could never decline one (R7). The real constraint is burning mandate
    attempts and degrading issuer standing.
    """
    if recovery_class == RecoveryClass.DEAD:
        return False
    if attempts_used >= economics_config["mandate_retry_cap"]:
        return False
    return predicted_uplift > economics_config["decline_rate_penalty_threshold"]


def apply_stopping_rules(
    proposal: ProposedPolicy,
    failure: PaymentFailure,
    economics_config: dict,
    attempts_used: int = 0,
) -> ProposedPolicy:
    """Downgrade `should_contact`/`should_retry` when the model's own
    proposal doesn't clear the stopping rules — independent of, and prior
    to, whatever the envelope separately enforces.
    """
    updates: dict = {}

    if proposal.should_contact and proposal.customer_message is not None:
        if not contact_is_worth_it(
            proposal.predicted_uplift,
            failure.amount_paise,
            proposal.customer_message.channel,
            economics_config,
        ):
            updates["should_contact"] = False
            updates["customer_message"] = None

    if proposal.should_retry and not retry_is_worth_it(
        proposal.recovery_class, proposal.predicted_uplift, attempts_used, economics_config
    ):
        updates["should_retry"] = False
        updates["retry_schedule"] = []

    return proposal.model_copy(update=updates) if updates else proposal


@dataclass
class PolicyProposalResult:
    proposal: ProposedPolicy | None  # None -> unparseable, fall back to baseline behaviour
    uplift_log: UpliftLogEntry | None
    fallback_outcome: RuleOutcome | None  # set only when proposal is None


def _load_prompt(prompt_version: str, prompt_dir: Path) -> str:
    return (prompt_dir / f"policy.{prompt_version}.md").read_text(encoding="utf-8")


def _render_failure(failure: PaymentFailure, recovery_class: RecoveryClass) -> str:
    context = failure.context
    return (
        f"failure_id: {failure.failure_id}\n"
        f"recovery_class: {recovery_class.value}\n"
        f"decline_code: {failure.decline_code}\n"
        f"decline_message_raw: {failure.decline_message_raw!r}\n"
        f"method: {failure.method}\n"
        f"amount_paise: {failure.amount_paise}\n"
        f"context.source: {context.source}\n"
        f"context.customer_tenure_days: {context.customer_tenure_days}\n"
        f"context.prior_failures_90d: {context.prior_failures_90d}\n"
        f"context.prior_successful_payments: {context.prior_successful_payments}\n"
        f"context.contacts_last_7d: {context.contacts_last_7d}\n"
        f"context.consent_channels: {sorted(context.consent_channels)}\n"
    )


def build_policy_request(
    failure: PaymentFailure,
    recovery_class: RecoveryClass,
    model: str,
    prompt_version: str = "v1",
    prompt_dir: Path = _DEFAULT_PROMPT_DIR,
) -> ChatRequest:
    """The exact request `propose_policy` would send — exposed so callers
    (e.g. the perturbation CLI's selective cache invalidation, BUILD.md
    task 9.2) can compute the same cache key without duplicating
    prompt-rendering logic.
    """
    prompt = _load_prompt(prompt_version, prompt_dir)
    return ChatRequest(
        model=model,
        messages=[
            ChatMessage(role="system", content=prompt),
            ChatMessage(role="user", content=_render_failure(failure, recovery_class)),
        ],
        temperature=0.2,
        response_format="json_object",
    )


def propose_policy(
    failure: PaymentFailure,
    recovery_class: RecoveryClass,
    client: ChatClient,
    model: str,
    economics_config: dict | None = None,
    attempts_used: int = 0,
    prompt_version: str = "v1",
    prompt_dir: Path = _DEFAULT_PROMPT_DIR,
) -> PolicyProposalResult:
    economics_config = economics_config if economics_config is not None else load_economics_config()
    request = build_policy_request(failure, recovery_class, model, prompt_version, prompt_dir)

    try:
        raw = parse_structured(client, request, ProposedPolicy, max_retries=2)
    except StructuredParseError as exc:
        outcome = SchemaValidRule.blocked_outcome(
            f"policy proposal unparseable after retries: {exc}"
        )
        return PolicyProposalResult(proposal=None, uplift_log=None, fallback_outcome=outcome)

    proposal = cast(ProposedPolicy, raw)
    adjusted = apply_stopping_rules(proposal, failure, economics_config, attempts_used)
    return PolicyProposalResult(
        proposal=adjusted, uplift_log=build_uplift_log_entry(adjusted), fallback_outcome=None
    )
