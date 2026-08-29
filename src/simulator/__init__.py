"""Failure simulator: latent outcome model, decline taxonomy, and batch generator."""

from src.simulator.distributions import RECOVERY_CLASS_SHARE, sample_recovery_class
from src.simulator.generator import GeneratedBatch, generate_batch
from src.simulator.latent import generate_latent_outcome
from src.simulator.sanity_gate import SanityGateFailure, check_sanity_gate
from src.simulator.schemas import FailureContext, LatentOutcome, PaymentFailure, RecoveryClass

__all__ = [
    "RECOVERY_CLASS_SHARE",
    "FailureContext",
    "GeneratedBatch",
    "LatentOutcome",
    "PaymentFailure",
    "RecoveryClass",
    "SanityGateFailure",
    "check_sanity_gate",
    "generate_batch",
    "generate_latent_outcome",
    "sample_recovery_class",
]
