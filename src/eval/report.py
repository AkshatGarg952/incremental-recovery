"""Batch report: aggregates every section and renders it to console or JSON
— BUILD.md task 8.12. Format follows BUILD.md R8.
"""

import json
from dataclasses import asdict, dataclass

from src.eval.breakdown import (
    ClassBreakdownRow,
    HorizonCurveRow,
    horizon_curve,
    per_class_breakdown,
)
from src.eval.estimator import EstimatorValidation, validate_estimator
from src.eval.exception_list import ExceptionEntry
from src.eval.gates import check_baseline_invariant
from src.eval.harness import BatchRunResult
from src.eval.lift import LiftReport, compute_lift
from src.eval.metering import MeteringChatClient
from src.eval.money import MoneyReport, compute_money_report
from src.eval.suppression import suppression_breakdown
from src.simulator.schemas import LatentOutcome


@dataclass
class ModelUseReport:
    llm_calls: int
    cache_hit_rate: float
    failures_needing_a_model_call_rate: float
    total_input_tokens: int
    total_output_tokens: int
    shadow_cost_usd: float
    shadow_cost_inr: float


@dataclass
class BatchReport:
    lift: LiftReport
    estimator: EstimatorValidation
    class_breakdown: list[ClassBreakdownRow]
    horizon_curve: list[HorizonCurveRow]
    money: MoneyReport
    suppression: dict[str, int]
    exceptions: list[ExceptionEntry]
    model_use: ModelUseReport
    seed: int = 0
    total_failures: int = 0


def build_batch_report(
    run_result: BatchRunResult,
    latent_outcomes: dict[str, LatentOutcome],
    metering: MeteringChatClient,
    ambiguous_rate: float,
    seed: int,
) -> BatchReport:
    """Assemble every report section. Raises `BaselineInvariantViolation`
    (BUILD.md task 8.4) before returning anything if the batch fails it."""
    agent = run_result.store.by_arm("agent")
    baseline = run_result.store.by_arm("baseline")
    holdout = run_result.store.by_arm("holdout")

    lift = compute_lift(agent, baseline, holdout)
    check_baseline_invariant(lift)

    estimator = validate_estimator(holdout, latent_outcomes)
    class_rows = per_class_breakdown(agent, baseline, holdout)
    horizon_rows = horizon_curve(agent, baseline, holdout)
    money = compute_money_report(agent, baseline, run_result.churned_failure_ids, latent_outcomes)
    suppression = suppression_breakdown(list(run_result.rules_fired_by_failure.values()))

    accountant = metering.accountant
    model_use = ModelUseReport(
        llm_calls=metering.calls,
        cache_hit_rate=metering.cache_hit_rate,
        failures_needing_a_model_call_rate=ambiguous_rate,
        total_input_tokens=accountant.prompt_tokens,
        total_output_tokens=accountant.completion_tokens,
        shadow_cost_usd=accountant.usd,
        shadow_cost_inr=accountant.inr,
    )

    return BatchReport(
        lift=lift,
        estimator=estimator,
        class_breakdown=class_rows,
        horizon_curve=horizon_rows,
        money=money,
        suppression=suppression,
        exceptions=run_result.exceptions,
        model_use=model_use,
        seed=seed,
        total_failures=len(run_result.store.records()),
    )


def render_json(report: BatchReport) -> str:
    return json.dumps(asdict(report), indent=2, default=str)


def _rupees(paise: int) -> str:
    return f"Rs {paise / 100:,.0f}"


def render_console(report: BatchReport) -> str:
    lift = report.lift
    money = report.money
    lines = [
        f"BATCH REPORT — seed: {report.seed}",
        f"Failures: {report.total_failures}    "
        f"agent {lift.n_agent} / baseline {lift.n_baseline} / holdout {lift.n_holdout}",
        "",
        "RECOVERY RATES",
        f"  Holdout   (no action)              {lift.rate_holdout:.1%}",
        f"  Baseline  (fixed T+1/T+2/T+3)      {lift.rate_baseline:.1%}",
        f"  Agent                              {lift.rate_agent:.1%}",
        "",
        "LIFT",
        f"  vs holdout    {lift.lift_vs_holdout:+.1%}  "
        f"[95% CI: {lift.lift_vs_holdout_ci[0]:.1%} - {lift.lift_vs_holdout_ci[1]:.1%}]",
        f"  vs baseline   {lift.lift_vs_baseline:+.1%}  "
        f"[95% CI: {lift.lift_vs_baseline_ci[0]:.1%} - {lift.lift_vs_baseline_ci[1]:.1%}]"
        "  ** HEADLINE **",
        "",
        f"  Estimator check: true self-recovery = {report.estimator.true_rate:.1%} "
        f"(CI covers truth: {'YES' if report.estimator.ci_covers_truth else 'NO'})",
        "",
        "LIFT BY HORIZON",
        *(
            f"  {row.horizon_hours:.0f}h  vs holdout {row.lift_vs_holdout:+.1%}  "
            f"vs baseline {row.lift_vs_baseline:+.1%}"
            for row in report.horizon_curve
        ),
        "",
        "PER-CLASS BREAKDOWN",
        *(
            f"  {row.recovery_class.value:8s} agent {row.rate_agent:.1%} (n={row.n_agent})  "
            f"baseline {row.rate_baseline:.1%} (n={row.n_baseline})  "
            f"lift {row.lift_vs_baseline:+.1%}" + ("  [thin cell]" if row.thin_cell else "")
            for row in report.class_breakdown
        ),
        "",
        "MONEY",
        f"  Agent gross recovery                      {_rupees(money.gross_agent_paise)}",
        f"  Attributable vs baseline                  "
        f"{_rupees(money.attributable_vs_baseline_paise)}",
        f"  Cost of contact                           {_rupees(money.contact_cost_paise)}",
        f"  Churn cost from fatigue                   {_rupees(money.churn_cost_paise)}",
        f"  NET ATTRIBUTABLE                          {_rupees(money.net_attributable_paise)}",
        "",
        "SUPPRESSED BY ENVELOPE RULE",
        *(f"    {rule_id:24s} {count}" for rule_id, count in sorted(report.suppression.items())),
        "",
        f"EXCEPTIONS: {len(report.exceptions)}",
        "",
        "MODEL USE",
        f"  LLM calls                     {report.model_use.llm_calls}   "
        f"(cache hits {report.model_use.cache_hit_rate:.0%})",
        f"  Failures needing a model call    "
        f"{report.model_use.failures_needing_a_model_call_rate:.0%}",
        f"  Shadow cost                     Rs {report.model_use.shadow_cost_inr:.2f}  "
        f"(${report.model_use.shadow_cost_usd:.4f})",
    ]
    return "\n".join(lines) + "\n"
