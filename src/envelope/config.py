"""Wire the envelope's rule set from `config/envelope.yaml` and
`config/templates.yaml` — the numbers stay in config, not hardcoded here.
"""

from pathlib import Path

import yaml

from src.envelope.engine import Envelope
from src.envelope.rules import (
    AmountBoundRule,
    ChannelConsentRule,
    ContactFrequencyRule,
    DeadNoChaseRule,
    EnvelopeRule,
    FatigueRule,
    QuietHoursRule,
    RetryCapRule,
    ScheduleSanityRule,
    TemplateAllowlistRule,
)

_DEFAULT_ENVELOPE_CONFIG_PATH = Path("config/envelope.yaml")
_DEFAULT_TEMPLATES_CONFIG_PATH = Path("config/templates.yaml")


def load_envelope_config(path: str | Path = _DEFAULT_ENVELOPE_CONFIG_PATH) -> dict:
    with open(path) as handle:
        return yaml.safe_load(handle)


def load_template_ids(path: str | Path = _DEFAULT_TEMPLATES_CONFIG_PATH) -> frozenset[str]:
    with open(path) as handle:
        data = yaml.safe_load(handle)
    return frozenset(template["template_id"] for template in data["templates"])


def build_default_envelope(
    envelope_config: dict | None = None, template_ids: frozenset[str] | None = None
) -> Envelope:
    config = envelope_config if envelope_config is not None else load_envelope_config()
    templates = template_ids if template_ids is not None else load_template_ids()

    rules: list[EnvelopeRule] = [
        RetryCapRule(max_attempts_per_mandate=config["retry_cap"]["max_attempts_per_mandate"]),
        ScheduleSanityRule(
            max_steps=config["schedule_sanity"]["max_retry_steps"],
            max_horizon_hours=config["schedule_sanity"]["max_horizon_hours"],
            require_monotonic=config["schedule_sanity"]["require_monotonic_delays"],
        ),
        QuietHoursRule(
            start_ist=config["quiet_hours"]["start_ist"],
            end_ist=config["quiet_hours"]["end_ist"],
        ),
        ContactFrequencyRule(
            max_contacts_per_7d=config["contact_frequency"]["max_contacts_per_7d"]
        ),
        ChannelConsentRule(),
        TemplateAllowlistRule(template_ids=templates),
        AmountBoundRule(),
        DeadNoChaseRule(),
        FatigueRule(
            block_after_contacts_and_failures=config["fatigue"]["block_after_contacts_and_failures"]
        ),
    ]
    return Envelope(rules=rules)
