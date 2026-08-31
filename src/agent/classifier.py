"""Failure classifier — BUILD.md tasks 5.1-5.6.

A deterministic rule prior handles "clean" decline codes for free. Only
genuinely ambiguous cases — `DO_NOT_HONOR`, a raw message that contradicts
the code's typical class, or a code/context conflict — go to an LLM. A
low-confidence LLM call routes to the exception list rather than forcing a
guess. Never imports `src.simulator.latent` — see tests/test_no_label_leak.py.
"""

from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel

from src.llm.client import ChatClient, ChatMessage, ChatRequest
from src.llm.structured import StructuredParseError, parse_structured
from src.simulator.decline_codes import DECLINE_CODE_CLASS
from src.simulator.schemas import PaymentFailure, RecoveryClass

_DEFAULT_PROMPT_DIR = Path("prompts")
_CONFIDENCE_THRESHOLD = 0.6

# Keywords in decline_message_raw that suggest a class other than the code's
# rule prior — a code/message conflict routes to the LLM instead of trusting
# the code. Deliberately coarse: false positives just mean one extra LLM
# call, which is cheap next to guessing wrong on a class that governs
# whether a customer gets chased at all.
_CLASS_HINT_KEYWORDS: dict[RecoveryClass, tuple[str, ...]] = {
    RecoveryClass.ACTION_RECOVERABLE: ("expired", "insufficient", "low bal", "invalid vpa"),
    RecoveryClass.TIME_RECOVERABLE: ("temporary", "congestion", "try again later", "issuer down"),
    RecoveryClass.ROUTE_RECOVERABLE: ("alternate", "restricted rail", "different payment method"),
    RecoveryClass.DEAD: ("fraud", "disputed", "revoked", "cancelled"),
}


class ClassificationAdjudication(BaseModel):
    """The LLM's structured output for one ambiguous case."""

    recovery_class: RecoveryClass
    confidence: float
    rationale: str


class ClassificationResult(BaseModel):
    failure_id: str
    recovery_class: RecoveryClass | None  # None -> exception list, never a forced guess
    confidence: float
    source: Literal["rule", "llm"]
    rationale: str


def rule_prior(failure: PaymentFailure) -> RecoveryClass | None:
    """Deterministic class for a "clean" decline code. `None` for codes the
    taxonomy itself marks ambiguous (`DO_NOT_HONOR`)."""
    return DECLINE_CODE_CLASS.get(failure.decline_code)


def _message_conflicts_with_prior(failure: PaymentFailure, prior: RecoveryClass) -> bool:
    text = failure.decline_message_raw.lower()
    for other_class, keywords in _CLASS_HINT_KEYWORDS.items():
        if other_class == prior:
            continue
        if any(keyword in text for keyword in keywords):
            return True
    return False


def _context_conflicts_with_prior(failure: PaymentFailure, prior: RecoveryClass) -> bool:
    if prior != RecoveryClass.DEAD:
        return False
    # A long-tenured customer with a clean recent history is a poor fit for
    # "permanently dead" — worth a second look rather than trusting the code.
    context = failure.context
    return (
        context.customer_tenure_days > 365
        and context.prior_successful_payments > 20
        and context.prior_failures_90d == 0
    )


def needs_llm_adjudication(failure: PaymentFailure) -> bool:
    """Route only ambiguous cases to the LLM (BUILD.md task 5.2)."""
    prior = rule_prior(failure)
    if prior is None:
        return True
    return _message_conflicts_with_prior(failure, prior) or _context_conflicts_with_prior(
        failure, prior
    )


def _load_prompt(prompt_version: str, prompt_dir: Path = _DEFAULT_PROMPT_DIR) -> str:
    return (prompt_dir / f"classify.{prompt_version}.md").read_text(encoding="utf-8")


def _render_failure(failure: PaymentFailure) -> str:
    context = failure.context
    return (
        f"decline_code: {failure.decline_code}\n"
        f"decline_message_raw: {failure.decline_message_raw!r}\n"
        f"method: {failure.method}\n"
        f"issuer_code: {failure.issuer_code}\n"
        f"amount_paise: {failure.amount_paise}\n"
        f"context.source: {context.source}\n"
        f"context.customer_tenure_days: {context.customer_tenure_days}\n"
        f"context.prior_failures_90d: {context.prior_failures_90d}\n"
        f"context.prior_successful_payments: {context.prior_successful_payments}\n"
        f"context.contacts_last_7d: {context.contacts_last_7d}\n"
    )


def build_classification_request(
    failure: PaymentFailure,
    model: str,
    prompt_version: str = "v1",
    prompt_dir: Path = _DEFAULT_PROMPT_DIR,
) -> ChatRequest:
    """The exact request `adjudicate_with_llm` would send — exposed so
    callers (e.g. the perturbation CLI's selective cache invalidation,
    BUILD.md task 9.2) can compute the same cache key without duplicating
    prompt-rendering logic.
    """
    prompt = _load_prompt(prompt_version, prompt_dir)
    return ChatRequest(
        model=model,
        messages=[
            ChatMessage(role="system", content=prompt),
            ChatMessage(role="user", content=_render_failure(failure)),
        ],
        temperature=0.0,
        response_format="json_object",
    )


def adjudicate_with_llm(
    failure: PaymentFailure,
    client: ChatClient,
    model: str,
    prompt_version: str = "v1",
    prompt_dir: Path = _DEFAULT_PROMPT_DIR,
) -> ClassificationAdjudication:
    request = build_classification_request(failure, model, prompt_version, prompt_dir)
    result = parse_structured(client, request, ClassificationAdjudication, max_retries=2)
    return cast(ClassificationAdjudication, result)


def classify_failure(
    failure: PaymentFailure,
    client: ChatClient,
    model: str,
    prompt_version: str = "v1",
    prompt_dir: Path = _DEFAULT_PROMPT_DIR,
) -> ClassificationResult:
    prior = rule_prior(failure)
    if prior is not None and not needs_llm_adjudication(failure):
        return ClassificationResult(
            failure_id=failure.failure_id,
            recovery_class=prior,
            confidence=1.0,
            source="rule",
            rationale=f"deterministic rule prior for {failure.decline_code}",
        )

    try:
        adjudication = adjudicate_with_llm(failure, client, model, prompt_version, prompt_dir)
    except StructuredParseError as exc:
        return ClassificationResult(
            failure_id=failure.failure_id,
            recovery_class=None,
            confidence=0.0,
            source="llm",
            rationale=f"unparseable llm output after retries: {exc}",
        )

    if adjudication.confidence < _CONFIDENCE_THRESHOLD:
        return ClassificationResult(
            failure_id=failure.failure_id,
            recovery_class=None,
            confidence=adjudication.confidence,
            source="llm",
            rationale=f"low confidence ({adjudication.confidence:.2f}): {adjudication.rationale}",
        )

    return ClassificationResult(
        failure_id=failure.failure_id,
        recovery_class=adjudication.recovery_class,
        confidence=adjudication.confidence,
        source="llm",
        rationale=adjudication.rationale,
    )


def classify_batch(
    failures: list[PaymentFailure],
    client: ChatClient,
    model: str,
    prompt_version: str = "v1",
    prompt_dir: Path = _DEFAULT_PROMPT_DIR,
) -> dict[str, ClassificationResult]:
    """Classify every failure regardless of arm (BUILD.md task 5.6).

    Holdout and baseline get labels too — needed to compute per-class
    lift — but this function has no notion of arms at all; only the
    caller's executor decides what to act on.
    """
    return {
        failure.failure_id: classify_failure(failure, client, model, prompt_version, prompt_dir)
        for failure in failures
    }
