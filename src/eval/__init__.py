"""Evaluation: three-arm assignment, ledger schema, and the batch report
harness (outcome resolution, lift, gates, breakdowns, money, and the spam
counterfactual)."""

from src.eval.assignment import (
    ASSIGNMENT_SEED,
    DEFAULT_ALLOCATION,
    amount_band,
    assign_arms,
    build_assignment_ledger_entries,
    stratum_key,
)
from src.eval.breakdown import (
    THIN_CELL_THRESHOLD,
    ClassBreakdownRow,
    HorizonCurveRow,
    horizon_curve,
    per_class_breakdown,
)
from src.eval.estimator import EstimatorValidation, true_self_recovery_rate, validate_estimator
from src.eval.exception_list import ExceptionEntry
from src.eval.gates import BaselineInvariantViolation, check_baseline_invariant
from src.eval.harness import BatchRunResult, run_batch
from src.eval.lift import LiftReport, compute_lift, newcombe_diff_ci, recovery_rate, wilson_ci
from src.eval.metering import MeteringChatClient, RoutingMeteringChatClient
from src.eval.money import MoneyReport, compute_money_report
from src.eval.outcome_resolver import LatentBackedResolver
from src.eval.outcome_store import OutcomeRecord, OutcomeStore, build_outcome_record
from src.eval.report import (
    BatchReport,
    ModelUseReport,
    build_batch_report,
    render_console,
    render_json,
)
from src.eval.schemas import Arm, LedgerEntry
from src.eval.spam import SpamRunResult, run_spam_counterfactual
from src.eval.suppression import suppression_breakdown

__all__ = [
    "ASSIGNMENT_SEED",
    "DEFAULT_ALLOCATION",
    "THIN_CELL_THRESHOLD",
    "Arm",
    "BaselineInvariantViolation",
    "BatchReport",
    "BatchRunResult",
    "ClassBreakdownRow",
    "EstimatorValidation",
    "ExceptionEntry",
    "HorizonCurveRow",
    "LatentBackedResolver",
    "LedgerEntry",
    "LiftReport",
    "MeteringChatClient",
    "ModelUseReport",
    "MoneyReport",
    "OutcomeRecord",
    "OutcomeStore",
    "RoutingMeteringChatClient",
    "SpamRunResult",
    "amount_band",
    "assign_arms",
    "build_assignment_ledger_entries",
    "build_batch_report",
    "build_outcome_record",
    "check_baseline_invariant",
    "compute_lift",
    "compute_money_report",
    "horizon_curve",
    "newcombe_diff_ci",
    "per_class_breakdown",
    "recovery_rate",
    "render_console",
    "render_json",
    "run_batch",
    "run_spam_counterfactual",
    "stratum_key",
    "suppression_breakdown",
    "true_self_recovery_rate",
    "validate_estimator",
    "wilson_ci",
]
