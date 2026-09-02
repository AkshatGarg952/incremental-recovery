# CLAUDE.md

Project context for working in this repo. `docs/BUILD.md` is the full build
plan (commit-by-commit history and the reference spec, "R1"-"R9") and is not
part of the submission (gitignored) — this file is the durable summary of
what matters day to day.

## What this is

An incremental recovery agent for failed payments: classify why a payment
failed, propose a recovery policy (retry / message / neither), run it
through a deterministic safety envelope, execute it, and honestly measure
how much it added over (a) doing nothing and (b) the fixed retry schedule a
merchant already runs. Everything is simulated end to end — see
"Simulation boundary" below.

## Where things live

```
src/simulator/   Failure generation + the latent (ground-truth) outcome model.
                 latent.py is the ONLY module allowed to encode ground truth.
src/agent/       classifier.py (rule prior + LLM adjudication) and
                 policy.py (LLM proposal + economic stopping rules).
src/envelope/    Deterministic rule engine — the actual safety layer.
src/executor/    Three arm executors (agent/baseline/holdout) + the
                 append-only ledger. Resolves outcomes only through the
                 OutcomeResolver protocol — never imports simulator.latent.
src/eval/        Assignment, the batch harness, lift/CI/money/breakdown
                 report sections, and outcome_resolver.py — the ONLY module
                 in src/eval allowed to import simulator.latent (it's the
                 eval-only path where realized outcomes join ground truth).
src/llm/         Provider-agnostic chat client, Gemini/Groq adapters,
                 FakeProvider, response cache, throttle, structured output.
src/perturb/     Live perturbation CLI (issuer outage, decline-code spike,
                 clock shift) with selective cache invalidation.
config/          envelope.yaml, economics.yaml, templates.yaml,
                 providers.yaml, pricing.yaml — every numeric constant that
                 isn't a code-level default lives here, with a provenance
                 comment.
prompts/         Versioned prompt files (classify.v1.md, policy.v1.md) —
                 never an inline string literal.
evals/           golden_set.jsonl — 30 hand-checked classifier cases.
data/            reference_batch.jsonl + DISTRIBUTION_SUMMARY.md — the only
                 two files under data/ that are actually committed (see
                 .gitignore: data/* is ignored, these two are the exception).
tests/           Mirrors src/ one file per module, plus the six build-gate
                 tests (see below).
```

## The one rule that matters more than the others

**`src/agent`, `src/envelope`, and `src/executor` must never import
`src.simulator.latent`.** `tests/test_no_label_leak.py` AST-walks all three
directories and fails the build if any of them do. The agent proposes,
deterministic code disposes, and neither ever gets to peek at the answer
key. When you need an executor or eval module to know whether something
"worked," it goes through `src.executor.outcomes.OutcomeResolver` (a
`Protocol`) — the concrete implementation
(`src.eval.outcome_resolver.LatentBackedResolver`) is the one place ground
truth and decision-making are allowed to touch.

## The six build gates

Run automatically in the test suite — not warnings, hard failures:

| Gate | Test | Asserts |
|---|---|---|
| Simulator sanity | `test_simulator_sanity.py` | `rate[TIME] - rate[ACTION] >= 30pp` at N=20,000 |
| No label leak | `test_no_label_leak.py` | AST-walk finds zero `simulator.latent` imports in agent/envelope/executor |
| Envelope escapes | `test_envelope.py` | Zero adversarial proposals survive the envelope unmodified |
| Idempotent replay | `test_executor_replay.py` | Re-running a batch writes zero duplicate ledger rows |
| Baseline invariant | `src/eval/gates.py` (`check_baseline_invariant`) | `rate(baseline) >= rate(holdout)`, checked live inside `build_batch_report` |
| Restraint pays | `test_restraint_gate.py` | The spam counterfactual wins on gross, loses on net |

## Conventions

- **One commit per logical unit, Conventional Commits** (`feat(scope): ...`,
  `test(scope): ...`, `docs: ...`). Branch per phase, merge `--no-ff` into
  `main`.
- **`uv run pytest` and `uv run ruff check .` green before every push.**
  Every test runs offline against `FakeProvider` — nothing in `tests/`
  burns free-tier quota. The only real network calls in this repo are the
  `tasks.py batch` and `src/perturb/cli.py` entry points, and they're
  gated behind actually having `GEMINI_API_KEY`/`GROQ_API_KEY` set.
- **Config over constants.** A number that a judge, a regulator, or a
  provider price list could change lives in `config/*.yaml` with a comment
  saying where it came from — not hardcoded in `src/`.
- **Versioned prompts as files**, `prompts/{name}.v{n}.md` — never an
  inline string. Bumping the prompt bumps the filename.
- **The response cache is content-addressed**: `(role, provider, model,
  prompt_version, sha256(payload))`. Changing a prompt file, a model, or a
  failure's rendered fields naturally busts the cache for exactly the
  affected requests — nothing needs to invalidate anything by hand except
  the perturbation CLI's deliberate re-fetch (`src/perturb/cache_invalidation.py`),
  which exists for demo freshness, not correctness.
- **Simulated time, not wall-clock time** (`src/executor/clock.py`). A
  7-day recovery horizon runs in however long the actual LLM calls take,
  not seven simulated days of wall time.
- **Seeds are committed, not incidental.** `ASSIGNMENT_SEED = 20260901` in
  `src/eval/assignment.py` is the project-wide default seed, reused by the
  simulator, the golden-set builder, and `tasks.py batch`. Reproducing a
  reported number means passing the same seed, not hoping for the best.

## Running things

```bash
uv run pytest                              # full suite, offline, ~15s
uv run ruff check . && uv run ruff format --check .
uv run python tasks.py batch --n 3000      # full batch, needs real API keys,
                                            # ~45-90 min on free-tier throttling
uv run python -m src.perturb.cli outage --issuer HDFC --outage 45m
```

See `README.md` for the full walkthrough and `skills/batch-report/SKILL.md`
for how to reproduce a batch report exactly.

## Simulation boundary

No real payment integration exists anywhere in this repo. `PaymentFailure`
records, decline codes, customer histories, and recovery outcomes are all
generated by `src/simulator`. "Sending" a message renders a template to a
log line, not an SMS/email/WhatsApp API call. See the README's "What's
simulated" section before citing any number from this project as if it
came from production traffic.
