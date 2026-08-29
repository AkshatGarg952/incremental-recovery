"""Rule interface and pass/clamped/blocked verdicts — BUILD.md task 3.1, R4.

Each rule receives the current proposal and an `EnvelopeContext` and returns
the (possibly adjusted) proposal plus a `RuleOutcome` carrying its rule ID and
verdict. Rules only ever see `PaymentFailure` and caller-supplied history
counters — never `LatentOutcome` (see tests/test_no_label_leak.py).

Why an envelope and not prompt constraints: prompt instructions are
advisory; an envelope is enforced. The prompt states the constraints too,
only so the model proposes sensible things and the block rate stays low.
"""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel

from src.envelope.schemas import ProposedPolicy
from src.simulator.schemas import PaymentFailure, RecoveryClass

IST_OFFSET = timedelta(hours=5, minutes=30)


class Verdict(StrEnum):
    PASS = "pass"
    CLAMPED = "clamped"
    BLOCKED = "blocked"


class RuleOutcome(BaseModel):
    rule_id: str
    verdict: Verdict
    detail: str = ""


@dataclass(frozen=True)
class EnvelopeContext:
    """Per-failure data a rule needs beyond the proposal itself.

    Populated by the caller (executor/ledger, Phase 7) from history it
    already tracks — the envelope never computes these counters itself.
    """

    failure: PaymentFailure
    now: datetime
    attempts_used: int
    contacts_used_7d: int
    consent_channels: frozenset[str]


class EnvelopeRule(ABC):
    rule_id: str

    @abstractmethod
    def apply(
        self, proposal: ProposedPolicy, context: EnvelopeContext
    ) -> tuple[ProposedPolicy, RuleOutcome]:
        """Return the (possibly adjusted) proposal and this rule's outcome."""


def _passed(rule_id: str) -> RuleOutcome:
    return RuleOutcome(rule_id=rule_id, verdict=Verdict.PASS)


def _format_amount_paise(amount_paise: int) -> str:
    return f"INR {amount_paise / 100:.2f}"


class RetryCapRule(EnvelopeRule):
    """`ENV_RETRY_CAP` — retry attempts per mandate within window <= configured cap."""

    rule_id = "ENV_RETRY_CAP"

    def __init__(self, max_attempts_per_mandate: int) -> None:
        self._max_attempts = max_attempts_per_mandate

    def apply(
        self, proposal: ProposedPolicy, context: EnvelopeContext
    ) -> tuple[ProposedPolicy, RuleOutcome]:
        if not proposal.should_retry or not proposal.retry_schedule:
            return proposal, _passed(self.rule_id)

        remaining = self._max_attempts - context.attempts_used
        if remaining <= 0:
            clamped = proposal.model_copy(update={"should_retry": False, "retry_schedule": []})
            return clamped, RuleOutcome(
                rule_id=self.rule_id, verdict=Verdict.BLOCKED, detail="mandate retry cap exhausted"
            )

        if len(proposal.retry_schedule) > remaining:
            clamped = proposal.model_copy(
                update={"retry_schedule": proposal.retry_schedule[:remaining]}
            )
            return clamped, RuleOutcome(
                rule_id=self.rule_id,
                verdict=Verdict.CLAMPED,
                detail=f"truncated retry schedule to {remaining} remaining attempt(s)",
            )

        return proposal, _passed(self.rule_id)


class ScheduleSanityRule(EnvelopeRule):
    """`ENV_SCHEDULE_SANITY` — delays monotonic, <= max steps, <= horizon."""

    rule_id = "ENV_SCHEDULE_SANITY"

    def __init__(self, max_steps: int, max_horizon_hours: int, require_monotonic: bool) -> None:
        self._max_steps = max_steps
        self._max_horizon_hours = max_horizon_hours
        self._require_monotonic = require_monotonic

    def apply(
        self, proposal: ProposedPolicy, context: EnvelopeContext
    ) -> tuple[ProposedPolicy, RuleOutcome]:
        schedule = proposal.retry_schedule
        if not schedule:
            return proposal, _passed(self.rule_id)

        delays = [step.delay_hours for step in schedule]
        problems = []
        if len(schedule) > self._max_steps:
            problems.append(f"{len(schedule)} steps > max {self._max_steps}")
        if any(d < 0 for d in delays):
            problems.append("negative delay")
        pairs = zip(delays, delays[1:], strict=False)
        if self._require_monotonic and any(b <= a for a, b in pairs):
            problems.append("delays not strictly increasing")
        if any(d > self._max_horizon_hours for d in delays):
            problems.append(f"delay exceeds {self._max_horizon_hours}h horizon")

        if not problems:
            return proposal, _passed(self.rule_id)

        cleaned: list = []
        last_delay = -1
        for step in schedule:
            delay = min(max(step.delay_hours, 0), self._max_horizon_hours)
            if self._require_monotonic and delay <= last_delay:
                delay = last_delay + 1
            if delay > self._max_horizon_hours:
                break
            cleaned.append(step.model_copy(update={"delay_hours": delay}))
            last_delay = delay
            if len(cleaned) >= self._max_steps:
                break

        clamped = proposal.model_copy(
            update={"retry_schedule": cleaned, "should_retry": bool(cleaned)}
        )
        return clamped, RuleOutcome(
            rule_id=self.rule_id, verdict=Verdict.CLAMPED, detail="; ".join(problems)
        )


class QuietHoursRule(EnvelopeRule):
    """`ENV_QUIET_HOURS` — no customer contact outside the allowed IST window."""

    rule_id = "ENV_QUIET_HOURS"

    def __init__(self, start_ist: str, end_ist: str) -> None:
        self._start_hour = int(start_ist.split(":")[0])
        self._end_hour = int(end_ist.split(":")[0])

    def _in_quiet_hours(self, moment: datetime) -> bool:
        ist_hour = (moment + IST_OFFSET).hour
        return ist_hour >= self._start_hour or ist_hour < self._end_hour

    def _hours_until_allowed(self, moment: datetime) -> int:
        ist = moment + IST_OFFSET
        candidate = ist.replace(hour=self._end_hour, minute=0, second=0, microsecond=0)
        if candidate <= ist:
            candidate += timedelta(days=1)
        return math.ceil((candidate - ist).total_seconds() / 3600)

    def apply(
        self, proposal: ProposedPolicy, context: EnvelopeContext
    ) -> tuple[ProposedPolicy, RuleOutcome]:
        if not proposal.should_contact or proposal.customer_message is None:
            return proposal, _passed(self.rule_id)

        message = proposal.customer_message
        send_at = context.now + timedelta(hours=message.send_after_hours)
        if not self._in_quiet_hours(send_at):
            return proposal, _passed(self.rule_id)

        shift_hours = self._hours_until_allowed(send_at)
        clamped_message = message.model_copy(
            update={"send_after_hours": message.send_after_hours + shift_hours}
        )
        clamped = proposal.model_copy(update={"customer_message": clamped_message})
        return clamped, RuleOutcome(
            rule_id=self.rule_id,
            verdict=Verdict.CLAMPED,
            detail="shifted send time past quiet hours",
        )


class ContactFrequencyRule(EnvelopeRule):
    """`ENV_CONTACT_FREQ` — <= N contacts per customer per 7 days, all channels."""

    rule_id = "ENV_CONTACT_FREQ"

    def __init__(self, max_contacts_per_7d: int) -> None:
        self._max_contacts = max_contacts_per_7d

    def apply(
        self, proposal: ProposedPolicy, context: EnvelopeContext
    ) -> tuple[ProposedPolicy, RuleOutcome]:
        if not proposal.should_contact:
            return proposal, _passed(self.rule_id)

        if context.contacts_used_7d < self._max_contacts:
            return proposal, _passed(self.rule_id)

        clamped = proposal.model_copy(update={"should_contact": False, "customer_message": None})
        return clamped, RuleOutcome(
            rule_id=self.rule_id, verdict=Verdict.BLOCKED, detail="contact frequency cap reached"
        )


class ChannelConsentRule(EnvelopeRule):
    """`ENV_CHANNEL_CONSENT` — channel must be in the customer's consent set."""

    rule_id = "ENV_CHANNEL_CONSENT"

    def apply(
        self, proposal: ProposedPolicy, context: EnvelopeContext
    ) -> tuple[ProposedPolicy, RuleOutcome]:
        if not proposal.should_contact or proposal.customer_message is None:
            return proposal, _passed(self.rule_id)

        if proposal.customer_message.channel in context.consent_channels:
            return proposal, _passed(self.rule_id)

        clamped = proposal.model_copy(update={"should_contact": False, "customer_message": None})
        return clamped, RuleOutcome(
            rule_id=self.rule_id,
            verdict=Verdict.BLOCKED,
            detail=f"channel {proposal.customer_message.channel!r} not in consent set",
        )


class TemplateAllowlistRule(EnvelopeRule):
    """`ENV_TEMPLATE_ALLOWLIST` — `template_id` must exist in the approved catalogue."""

    rule_id = "ENV_TEMPLATE_ALLOWLIST"

    def __init__(self, template_ids: frozenset[str]) -> None:
        self._template_ids = template_ids

    def apply(
        self, proposal: ProposedPolicy, context: EnvelopeContext
    ) -> tuple[ProposedPolicy, RuleOutcome]:
        if not proposal.should_contact or proposal.customer_message is None:
            return proposal, _passed(self.rule_id)

        if proposal.customer_message.template_id in self._template_ids:
            return proposal, _passed(self.rule_id)

        clamped = proposal.model_copy(update={"should_contact": False, "customer_message": None})
        return clamped, RuleOutcome(
            rule_id=self.rule_id,
            verdict=Verdict.BLOCKED,
            detail=f"template {proposal.customer_message.template_id!r} not in catalogue",
        )


class AmountBoundRule(EnvelopeRule):
    """`ENV_AMOUNT_BOUND` — a message's amount reference must equal the original, exactly."""

    rule_id = "ENV_AMOUNT_BOUND"

    def apply(
        self, proposal: ProposedPolicy, context: EnvelopeContext
    ) -> tuple[ProposedPolicy, RuleOutcome]:
        if not proposal.should_contact or proposal.customer_message is None:
            return proposal, _passed(self.rule_id)

        variables = proposal.customer_message.variables
        if "amount" not in variables:
            return proposal, _passed(self.rule_id)

        expected = _format_amount_paise(context.failure.amount_paise)
        if variables["amount"] == expected:
            return proposal, _passed(self.rule_id)

        corrected = dict(variables)
        corrected["amount"] = expected
        clamped_message = proposal.customer_message.model_copy(update={"variables": corrected})
        clamped = proposal.model_copy(update={"customer_message": clamped_message})
        return clamped, RuleOutcome(
            rule_id=self.rule_id,
            verdict=Verdict.CLAMPED,
            detail="amount variable overwritten to match the original authorization",
        )


class DeadNoChaseRule(EnvelopeRule):
    """`ENV_DEAD_NO_CHASE` — DEAD class gets zero intervention, no exceptions."""

    rule_id = "ENV_DEAD_NO_CHASE"

    def apply(
        self, proposal: ProposedPolicy, context: EnvelopeContext
    ) -> tuple[ProposedPolicy, RuleOutcome]:
        if proposal.recovery_class != RecoveryClass.DEAD:
            return proposal, _passed(self.rule_id)

        if not proposal.should_retry and not proposal.should_contact:
            return proposal, _passed(self.rule_id)

        clamped = proposal.model_copy(
            update={
                "should_retry": False,
                "should_contact": False,
                "retry_schedule": [],
                "customer_message": None,
            }
        )
        return clamped, RuleOutcome(
            rule_id=self.rule_id, verdict=Verdict.BLOCKED, detail="dead class — no exceptions"
        )


class FatigueRule(EnvelopeRule):
    """`ENV_FATIGUE` — block contact once failure and contact history exceed the bound."""

    rule_id = "ENV_FATIGUE"

    def __init__(self, block_after_contacts_and_failures: int) -> None:
        self._threshold = block_after_contacts_and_failures

    def apply(
        self, proposal: ProposedPolicy, context: EnvelopeContext
    ) -> tuple[ProposedPolicy, RuleOutcome]:
        if not proposal.should_contact:
            return proposal, _passed(self.rule_id)

        history = context.failure.context.prior_failures_90d + context.contacts_used_7d
        if history < self._threshold:
            return proposal, _passed(self.rule_id)

        clamped = proposal.model_copy(update={"should_contact": False, "customer_message": None})
        return clamped, RuleOutcome(
            rule_id=self.rule_id, verdict=Verdict.BLOCKED, detail="fatigue bound exceeded"
        )


class SchemaValidRule:
    """`ENV_SCHEMA_VALID` — proposal must parse against `ProposedPolicy` after
    bounded retries (see `src/llm/structured.py`).

    Not an `EnvelopeRule`: it fires before a proposal exists at all, when
    `parse_structured` exhausts its retries. The caller (Phase 6's policy
    agent) catches `StructuredParseError` and uses `blocked_outcome` to log
    the fallback to baseline behaviour.
    """

    rule_id = "ENV_SCHEMA_VALID"

    @classmethod
    def blocked_outcome(cls, detail: str) -> RuleOutcome:
        return RuleOutcome(rule_id=cls.rule_id, verdict=Verdict.BLOCKED, detail=detail)
