"""Offline tests for the batch generator (BUILD.md tasks 2.1-2.8)."""

import pytest

from src.simulator.decline_codes import DECLINE_CODE_CLASS
from src.simulator.generator import generate_batch
from src.simulator.sanity_gate import SanityGateFailure

_SEED = 20260901


_N = 3000  # BUILD.md R2: the real batch size, ~3,000. The sanity gate's
# aggregate band is only statistically meaningful at this scale — see R5's
# note that the gate itself is specified at N=20,000 for the same reason.


def test_generate_batch_produces_valid_failures_and_passes_the_gate():
    batch = generate_batch(n=_N, seed=_SEED)

    assert len(batch.failures) == _N
    assert len(batch.latent_outcomes) == _N
    assert len(batch.recovery_classes) == _N

    for failure in batch.failures:
        assert failure.decline_code in DECLINE_CODE_CLASS
        assert failure.amount_paise > 0
        assert failure.method in {"upi", "card", "netbanking", "emandate", "wallet"}
        if failure.context.source == "subscription":
            assert failure.context.subscription_mrr_paise is not None
        if failure.context.source == "invoice":
            assert failure.context.invoice_due_date is not None


def test_generate_batch_is_seed_deterministic():
    first = generate_batch(n=_N, seed=_SEED)
    second = generate_batch(n=_N, seed=_SEED)

    assert [f.model_dump() for f in first.failures] == [f.model_dump() for f in second.failures]


def test_generate_batch_emandate_failures_are_always_mandate_sourced():
    batch = generate_batch(n=_N, seed=_SEED)

    emandate_sources = {f.context.source for f in batch.failures if f.method == "emandate"}
    assert emandate_sources == {"mandate"}


def test_generate_batch_raises_sanity_gate_failure_on_a_broken_population(monkeypatch):
    import src.simulator.generator as generator_module

    def _flat_outcome(*_args, **_kwargs):
        from src.simulator.schemas import LatentOutcome

        return LatentOutcome(
            would_self_recover=True,
            self_recovery_delay_hours=1.0,
            responds_to_retry=True,
            responds_to_message=True,
            fatigue_threshold=3,
            fatigue_decay_per_contact=0.7,
            churn_prob_per_excess_contact=0.05,
            ltv_paise=0,
        )

    monkeypatch.setattr(generator_module, "generate_latent_outcome", _flat_outcome)

    with pytest.raises(SanityGateFailure):
        generate_batch(n=500, seed=_SEED)
