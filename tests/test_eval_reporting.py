"""Offline tests for the report-building layer (BUILD.md tasks 8.2-8.10),
built directly on constructed `OutcomeRecord`s — no LLM, no executor,
no generator needed to exercise the math.
"""

import pytest

from src.envelope.rules import RuleOutcome, Verdict
from src.eval.breakdown import THIN_CELL_THRESHOLD, horizon_curve, per_class_breakdown
from src.eval.estimator import true_self_recovery_rate, validate_estimator
from src.eval.gates import BaselineInvariantViolation, check_baseline_invariant
from src.eval.lift import compute_lift, newcombe_diff_ci, recovery_rate, wilson_ci
from src.eval.money import compute_money_report
from src.eval.outcome_store import OutcomeRecord
from src.eval.suppression import suppression_breakdown
from src.simulator.schemas import LatentOutcome, RecoveryClass


def _record(**overrides) -> OutcomeRecord:
    defaults = dict(
        failure_id="f1",
        arm="agent",
        recovery_class=RecoveryClass.ACTION_RECOVERABLE,
        recovered=False,
        recovered_at_hours=None,
        retries_made=0,
        contacts_made=0,
        amount_paise=50_000,
        contact_cost_paise=0,
        would_self_recover=False,
    )
    defaults.update(overrides)
    return OutcomeRecord(**defaults)


def _latent(would_self_recover: bool, ltv_paise: int = 100_000) -> LatentOutcome:
    return LatentOutcome(
        would_self_recover=would_self_recover,
        self_recovery_delay_hours=10.0,
        responds_to_retry=False,
        responds_to_message=False,
        fatigue_threshold=3,
        fatigue_decay_per_contact=0.5,
        churn_prob_per_excess_contact=0.1,
        ltv_paise=ltv_paise,
    )


# ---- lift + CI (8.2, 8.3) -----------------------------------------------------


def test_recovery_rate_of_empty_list_is_zero():
    assert recovery_rate([]) == 0.0


def test_compute_lift_reports_both_contrasts():
    agent = [_record(recovered=True)] * 40 + [_record(recovered=False)] * 60
    baseline = [_record(arm="baseline", recovered=True)] * 25 + [
        _record(arm="baseline", recovered=False)
    ] * 75
    holdout = [_record(arm="holdout", recovered=True)] * 15 + [
        _record(arm="holdout", recovered=False)
    ] * 85

    lift = compute_lift(agent, baseline, holdout)

    assert lift.rate_agent == pytest.approx(0.40)
    assert lift.rate_baseline == pytest.approx(0.25)
    assert lift.rate_holdout == pytest.approx(0.15)
    assert lift.lift_vs_holdout == pytest.approx(0.25)
    assert lift.lift_vs_baseline == pytest.approx(0.15)
    assert lift.lift_vs_holdout_ci[0] < lift.lift_vs_holdout < lift.lift_vs_holdout_ci[1]
    assert lift.lift_vs_baseline_ci[0] < lift.lift_vs_baseline < lift.lift_vs_baseline_ci[1]


def test_wilson_ci_widens_for_smaller_samples():
    low_small, high_small = wilson_ci(5, 10)
    low_large, high_large = wilson_ci(500, 1000)

    assert (high_small - low_small) > (high_large - low_large)


def test_newcombe_diff_ci_covers_zero_when_rates_are_equal():
    low, high = newcombe_diff_ci(50, 100, 50, 100)
    assert low <= 0.0 <= high


# ---- baseline invariant gate (8.4) -------------------------------------------


def test_baseline_invariant_passes_when_baseline_at_least_matches_holdout():
    agent = [_record(recovered=True)]
    baseline = [_record(arm="baseline", recovered=True)]
    holdout = [_record(arm="holdout", recovered=False)]
    lift = compute_lift(agent, baseline, holdout)

    check_baseline_invariant(lift)  # must not raise


def test_baseline_invariant_raises_when_baseline_underperforms_holdout():
    agent = [_record(recovered=True)] * 10
    baseline = [_record(arm="baseline", recovered=True)] * 10 + [
        _record(arm="baseline", recovered=False)
    ] * 90
    holdout = [_record(arm="holdout", recovered=True)] * 50 + [
        _record(arm="holdout", recovered=False)
    ] * 50
    lift = compute_lift(agent, baseline, holdout)

    with pytest.raises(BaselineInvariantViolation):
        check_baseline_invariant(lift)


# ---- estimator validation (8.5) ----------------------------------------------


def test_true_self_recovery_rate_matches_the_latent_population():
    latent = {"f1": _latent(True), "f2": _latent(False), "f3": _latent(False), "f4": _latent(True)}
    assert true_self_recovery_rate(latent) == pytest.approx(0.5)


def test_validate_estimator_covers_the_truth_for_a_representative_sample():
    latent = {f"f{i}": _latent(i % 5 == 0) for i in range(1000)}  # true rate = 0.20
    holdout = [
        _record(failure_id=f"f{i}", arm="holdout", recovered=(i % 5 == 0)) for i in range(1000)
    ]

    validation = validate_estimator(holdout, latent)

    assert validation.true_rate == pytest.approx(0.20)
    assert validation.holdout_estimate == pytest.approx(0.20)
    assert validation.ci_covers_truth is True


# ---- per-class breakdown + thin cells (8.6) ----------------------------------


def test_per_class_breakdown_flags_thin_cells():
    agent = [_record(recovery_class=RecoveryClass.DEAD, recovered=False)] * 5
    baseline = [_record(arm="baseline", recovery_class=RecoveryClass.DEAD, recovered=False)] * 5
    holdout = [_record(arm="holdout", recovery_class=RecoveryClass.DEAD, recovered=False)] * 5

    rows = per_class_breakdown(agent, baseline, holdout)
    dead_row = next(r for r in rows if r.recovery_class == RecoveryClass.DEAD)

    assert dead_row.thin_cell is True
    assert dead_row.n_agent == 5 < THIN_CELL_THRESHOLD


def test_per_class_breakdown_covers_every_recovery_class():
    rows = per_class_breakdown([], [], [])
    assert {row.recovery_class for row in rows} == set(RecoveryClass)


# ---- horizon curve (8.7) ------------------------------------------------------


def test_horizon_curve_only_counts_recoveries_within_each_window():
    agent = [
        _record(recovered=True, recovered_at_hours=10.0),
        _record(recovered=True, recovered_at_hours=100.0),
        _record(recovered=False),
    ]
    rows = horizon_curve(agent, [], [], horizons_hours=(24.0, 168.0))

    at_24h = next(r for r in rows if r.horizon_hours == 24.0)
    at_168h = next(r for r in rows if r.horizon_hours == 168.0)

    assert at_24h.rate_agent == pytest.approx(1 / 3)
    assert at_168h.rate_agent == pytest.approx(2 / 3)


# ---- money (8.8) ---------------------------------------------------------------


def test_money_report_computes_gross_attributable_and_net():
    agent = [
        _record(failure_id="a1", recovered=True, amount_paise=100_000, contact_cost_paise=20),
        _record(failure_id="a2", recovered=False, amount_paise=100_000),
    ]
    baseline = [_record(arm="baseline", recovered=True)] * 25 + [
        _record(arm="baseline", recovered=False)
    ] * 75  # baseline rate 25%
    latent = {"a1": _latent(False, ltv_paise=50_000)}

    money = compute_money_report(agent, baseline, frozenset({"a1"}), latent)

    assert money.gross_agent_paise == 100_000
    # expected baseline recovery on the same 200,000 paise population @ 25% = 50,000
    assert money.attributable_vs_baseline_paise == 50_000
    assert money.contact_cost_paise == 20
    assert money.churn_cost_paise == 50_000  # a1 churned
    assert money.net_attributable_paise == 50_000 - 20 - 50_000


def test_money_report_ignores_churn_outside_the_agent_arm():
    agent = [_record(failure_id="a1", recovered=True, amount_paise=100_000)]
    latent = {"a1": _latent(False), "other_arm_failure": _latent(False, ltv_paise=999_999)}

    money = compute_money_report(agent, [], frozenset({"other_arm_failure"}), latent)

    assert money.churn_cost_paise == 0


# ---- suppression breakdown (8.9) ---------------------------------------------


def test_suppression_breakdown_counts_non_pass_verdicts_by_rule_id():
    all_rules_fired = [
        [RuleOutcome(rule_id="ENV_QUIET_HOURS", verdict=Verdict.CLAMPED)],
        [
            RuleOutcome(rule_id="ENV_QUIET_HOURS", verdict=Verdict.CLAMPED),
            RuleOutcome(rule_id="ENV_DEAD_NO_CHASE", verdict=Verdict.BLOCKED),
        ],
        [RuleOutcome(rule_id="ENV_RETRY_CAP", verdict=Verdict.PASS)],
    ]

    counts = suppression_breakdown(all_rules_fired)

    assert counts == {"ENV_QUIET_HOURS": 2, "ENV_DEAD_NO_CHASE": 1}
