"""Agent pipeline: classify -> propose -> (envelope) -> execute.

Never imports src.simulator.latent — see tests/test_no_label_leak.py.
"""

from src.agent.classifier import (
    ClassificationAdjudication,
    ClassificationResult,
    adjudicate_with_llm,
    build_classification_request,
    classify_batch,
    classify_failure,
    needs_llm_adjudication,
    rule_prior,
)
from src.agent.classifier_eval import ClassifierEvalReport, load_golden_set, run_classifier_eval
from src.agent.policy import (
    PolicyProposalResult,
    UpliftLogEntry,
    apply_stopping_rules,
    build_policy_request,
    build_uplift_log_entry,
    contact_is_worth_it,
    load_economics_config,
    propose_policy,
    retry_is_worth_it,
)

__all__ = [
    "ClassificationAdjudication",
    "ClassificationResult",
    "ClassifierEvalReport",
    "PolicyProposalResult",
    "UpliftLogEntry",
    "adjudicate_with_llm",
    "apply_stopping_rules",
    "build_classification_request",
    "build_policy_request",
    "build_uplift_log_entry",
    "classify_batch",
    "classify_failure",
    "contact_is_worth_it",
    "load_economics_config",
    "load_golden_set",
    "needs_llm_adjudication",
    "propose_policy",
    "retry_is_worth_it",
    "rule_prior",
    "run_classifier_eval",
]
