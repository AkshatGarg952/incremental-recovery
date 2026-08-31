"""Selective cache invalidation — BUILD.md task 9.2.

The response cache is content-addressed (BUILD.md task 0.8), so a
perturbed failure's changed payload naturally misses the cache on its own
— nothing here is needed for *correctness*. It exists so a demo re-run of
the same perturbation always makes a visibly live call for the affected
slice, instead of silently serving a cached response from a previous run
of the same command, while every other failure in the batch keeps its
cached entry untouched.
"""

from src.agent.classifier import build_classification_request
from src.agent.policy import build_policy_request
from src.llm.cache import ResponseCache
from src.simulator.schemas import PaymentFailure, RecoveryClass


def invalidate_cache_for_failures(
    cache: ResponseCache,
    failures: list[PaymentFailure],
    recovery_classes: dict[str, RecoveryClass],
    classify_model: str,
    classify_provider: str,
    policy_model: str,
    policy_provider: str,
    prompt_version: str = "v1",
) -> int:
    """Delete the classify/policy cache entries for exactly these failures.
    Returns the number of rows actually deleted.
    """
    invalidated = 0
    for failure in failures:
        classify_request = build_classification_request(failure, classify_model, prompt_version)
        if cache.delete("classify", classify_provider, classify_request, prompt_version):
            invalidated += 1

        recovery_class = recovery_classes.get(failure.failure_id)
        if recovery_class is not None:
            policy_request = build_policy_request(
                failure, recovery_class, policy_model, prompt_version
            )
            if cache.delete("policy", policy_provider, policy_request, prompt_version):
                invalidated += 1

    return invalidated
