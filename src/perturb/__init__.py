"""Perturbation: inject a live change into a batch and re-plan the
affected slice — the "hand the judge the keyboard" demo moment.
"""

from src.perturb.cache_invalidation import invalidate_cache_for_failures
from src.perturb.config import build_role_clients, load_providers_config
from src.perturb.engine import (
    PerturbationResult,
    apply_clock_shift,
    apply_decline_spike,
    apply_issuer_outage,
)
from src.perturb.replan import DecisionDiff, render_decision_diffs, replan_affected_failures

__all__ = [
    "DecisionDiff",
    "PerturbationResult",
    "apply_clock_shift",
    "apply_decline_spike",
    "apply_issuer_outage",
    "build_role_clients",
    "invalidate_cache_for_failures",
    "load_providers_config",
    "render_decision_diffs",
    "replan_affected_failures",
]
