"""Money section — gross, attributable, contact cost, churn cost, net —
BUILD.md task 8.8.

`net_attributable_paise` is the number the pitch stands behind: what the
agent added over baseline, minus what it cost to get there. The baseline
arm never contacts anyone, so it carries zero fatigue cost — the agent has
to beat it on net, not gross (BUILD.md R6).
"""

from dataclasses import dataclass

from src.eval.outcome_store import OutcomeRecord
from src.simulator.schemas import LatentOutcome


@dataclass
class MoneyReport:
    gross_agent_paise: int
    attributable_vs_baseline_paise: int
    contact_cost_paise: int
    churn_cost_paise: int
    net_attributable_paise: int


def compute_money_report(
    agent: list[OutcomeRecord],
    baseline: list[OutcomeRecord],
    churned_failure_ids: frozenset[str],
    latent_outcomes: dict[str, LatentOutcome],
) -> MoneyReport:
    gross = sum(r.amount_paise for r in agent if r.recovered)

    total_agent_amount = sum(r.amount_paise for r in agent)
    baseline_successes = sum(1 for r in baseline if r.recovered)
    baseline_rate = baseline_successes / len(baseline) if baseline else 0.0
    expected_baseline_on_agent_population = int(baseline_rate * total_agent_amount)
    attributable = gross - expected_baseline_on_agent_population

    contact_cost = sum(r.contact_cost_paise for r in agent)

    agent_failure_ids = {r.failure_id for r in agent}
    churn_cost = sum(
        latent_outcomes[fid].ltv_paise
        for fid in churned_failure_ids
        if fid in agent_failure_ids and fid in latent_outcomes
    )

    net = attributable - contact_cost - churn_cost

    return MoneyReport(
        gross_agent_paise=gross,
        attributable_vs_baseline_paise=attributable,
        contact_cost_paise=contact_cost,
        churn_cost_paise=churn_cost,
        net_attributable_paise=net,
    )
