"""Deterministic policy envelope: the safety layer, not the LLM.

Prompt instructions are advisory; an envelope is enforced. Every rule here
is deterministic — no model call, no ambiguity about whether it fired.
"""

from src.envelope.config import build_default_envelope, load_envelope_config, load_template_ids
from src.envelope.engine import Envelope, EnvelopeResult
from src.envelope.rules import (
    AmountBoundRule,
    ChannelConsentRule,
    ContactFrequencyRule,
    DeadNoChaseRule,
    EnvelopeContext,
    EnvelopeRule,
    FatigueRule,
    QuietHoursRule,
    RetryCapRule,
    RuleOutcome,
    ScheduleSanityRule,
    SchemaValidRule,
    TemplateAllowlistRule,
    Verdict,
)
from src.envelope.schemas import MessageSpec, ProposedPolicy, RetryStep

__all__ = [
    "AmountBoundRule",
    "ChannelConsentRule",
    "ContactFrequencyRule",
    "DeadNoChaseRule",
    "Envelope",
    "EnvelopeContext",
    "EnvelopeResult",
    "EnvelopeRule",
    "FatigueRule",
    "MessageSpec",
    "ProposedPolicy",
    "QuietHoursRule",
    "RetryCapRule",
    "RetryStep",
    "RuleOutcome",
    "ScheduleSanityRule",
    "SchemaValidRule",
    "TemplateAllowlistRule",
    "Verdict",
    "build_default_envelope",
    "load_envelope_config",
    "load_template_ids",
]
