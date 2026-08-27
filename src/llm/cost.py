"""Token accounting and shadow cost.

Real cost is Rs 0 on the free tier, so usage is logged and priced against a
committed list-price table instead (`config/pricing.yaml`). Report both, and
say plainly that the shadow figure is hypothetical — see BUILD.md R9.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel

from src.llm.client import Usage

_DEFAULT_PRICING_PATH = Path("config/pricing.yaml")


class ShadowCost(BaseModel):
    usd: float
    inr: float


def load_pricing(path: str | Path = _DEFAULT_PRICING_PATH) -> dict:
    with open(path) as handle:
        return yaml.safe_load(handle)


def shadow_cost(usage: Usage, model: str, pricing: dict) -> ShadowCost:
    """Price `usage` against `pricing`'s committed list-price table.

    Raises `KeyError` if `model` has no entry — a missing price should surface,
    not silently report Rs 0 as if the call were free by policy.
    """
    rates = pricing["usd_per_million_tokens"][model]
    usd = (
        usage.prompt_tokens * rates["input"] + usage.completion_tokens * rates["output"]
    ) / 1_000_000
    inr = usd * pricing["usd_to_inr"]
    return ShadowCost(usd=usd, inr=inr)


class TokenAccountant:
    """Accumulates call count, token usage, and shadow cost — e.g. across a batch."""

    def __init__(self, pricing: dict) -> None:
        self._pricing = pricing
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.usd = 0.0
        self.inr = 0.0

    def record(self, usage: Usage, model: str) -> ShadowCost:
        cost = shadow_cost(usage, model, self._pricing)
        self.calls += 1
        self.prompt_tokens += usage.prompt_tokens
        self.completion_tokens += usage.completion_tokens
        self.usd += cost.usd
        self.inr += cost.inr
        return cost
