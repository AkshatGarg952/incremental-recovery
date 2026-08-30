"""Agent pipeline: classify -> propose -> (envelope) -> execute.

Never imports src.simulator.latent — see tests/test_no_label_leak.py.
"""

from src.agent.classifier import (
    ClassificationAdjudication,
    ClassificationResult,
    adjudicate_with_llm,
    classify_batch,
    classify_failure,
    needs_llm_adjudication,
    rule_prior,
)
from src.agent.classifier_eval import ClassifierEvalReport, load_golden_set, run_classifier_eval

__all__ = [
    "ClassificationAdjudication",
    "ClassificationResult",
    "ClassifierEvalReport",
    "adjudicate_with_llm",
    "classify_batch",
    "classify_failure",
    "load_golden_set",
    "needs_llm_adjudication",
    "rule_prior",
    "run_classifier_eval",
]
