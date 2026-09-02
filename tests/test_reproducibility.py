"""BUILD.md task 10.7 — clean-clone reproducibility, verified offline.

Two separate claims, both checked directly rather than asserted in prose:

1. Everything except the LLM call content is deterministic from the seed
   alone — the simulator, arm assignment, and the executor's idempotency
   scheme all use caller-seeded `random.Random`, never the global module
   (already covered individually in test_simulator_generator.py,
   test_assignment.py, test_executor_replay.py; re-asserted here end to end
   through generate_batch + assign_arms together).
2. The LLM-dependent path is made reproducible by the response cache, not
   by trusting a live model to return byte-identical output twice. This is
   the part a "clean clone" actually depends on: the first run against a
   fresh clone (no cache) makes real calls; every run after that — on the
   same clone or a different one that received the populated cache file —
   is byte-identical and makes zero further calls, because the cache is
   what's being replayed, not the model.
"""

import json

from src.eval.assignment import ASSIGNMENT_SEED, assign_arms
from src.eval.harness import run_batch
from src.eval.metering import MeteringChatClient
from src.eval.report import build_batch_report, render_json
from src.executor.clock import SimulatedClock
from src.executor.ledger import Ledger
from src.llm.cache import CachingChatClient, ResponseCache
from src.llm.cost import TokenAccountant, load_pricing
from src.llm.fake import FakeProvider
from src.simulator.generator import generate_batch
from tests.test_harness import (
    _CLASSIFY_MODEL,
    _CLASSIFY_RESPONSE,
    _POLICY_MODEL,
    _POLICY_RESPONSE,
    _START,
)
from tests.test_harness import _build_batch as _build_harness_batch


def test_generate_batch_and_assign_arms_are_deterministic_end_to_end():
    first = generate_batch(n=3000, seed=ASSIGNMENT_SEED)
    second = generate_batch(n=3000, seed=ASSIGNMENT_SEED)

    assert [f.model_dump() for f in first.failures] == [f.model_dump() for f in second.failures]

    first_assignment = assign_arms(first.failures, seed=ASSIGNMENT_SEED)
    second_assignment = assign_arms(second.failures, seed=ASSIGNMENT_SEED)
    assert first_assignment == second_assignment


def test_a_cached_batch_replay_is_byte_identical_and_makes_zero_new_calls(tmp_path):
    """Simulates exactly what running `tasks.py batch` twice against the
    same committed seed does: first run populates the cache with real
    (here, scripted) responses; second run — a fresh harness invocation,
    same as a second `uv run python tasks.py batch` — hits the cache for
    every request and never calls the provider again.
    """
    failures, assignment, latent_outcomes = _build_harness_batch()
    economics = {
        "contact_cost_paise": {"sms": 20, "email": 2, "whatsapp": 35, "in_app": 1},
        "mandate_retry_cap": 4,
        "decline_rate_penalty_threshold": 0.15,
    }
    cache_path = tmp_path / "shared_cache.sqlite3"

    def run_once():
        provider = FakeProvider(
            [
                _CLASSIFY_RESPONSE,
                _POLICY_RESPONSE.replace("PLACEHOLDER", "agent_1"),
                _POLICY_RESPONSE.replace("PLACEHOLDER", "agent_2"),
            ]
        )
        cache = ResponseCache(cache_path)
        caching_client = CachingChatClient(
            provider, cache, role="classify_and_policy", provider="fake", prompt_version="v1"
        )
        accountant = TokenAccountant(load_pricing())
        client = MeteringChatClient(caching_client, accountant)
        ledger = Ledger(":memory:")
        clock = SimulatedClock(_START)

        result = run_batch(
            failures,
            assignment,
            latent_outcomes,
            client,
            _CLASSIFY_MODEL,
            _POLICY_MODEL,
            ledger,
            clock,
            seed=1,
            economics_config=economics,
        )
        report = build_batch_report(result, latent_outcomes, client, ambiguous_rate=1 / 6, seed=1)
        return render_json(report), len(provider.calls)

    # First run: a fresh cache, like a clean clone — makes real (scripted) calls.
    first_json, first_calls = run_once()
    assert first_calls == 3

    # Second run against the SAME cache file: zero new provider calls, and
    # every decision-relevant section is byte-identical. model_use legitimately
    # differs — cache_hit_rate goes to 1.0 and token/shadow-cost spend drops to
    # ~0, which is the whole point of the cache (BUILD.md R8: "cache hits 71%
    # on re-run"), not a reproducibility failure.
    second_json, second_calls = run_once()
    assert second_calls == 0

    first_report = json.loads(first_json)
    second_report = json.loads(second_json)
    assert first_report["model_use"]["llm_calls"] == second_report["model_use"]["llm_calls"]
    assert second_report["model_use"]["cache_hit_rate"] == 1.0

    del first_report["model_use"]
    del second_report["model_use"]
    assert first_report == second_report
