---
name: batch-report
description: Reproduce the incremental-recovery-engine's batch report (recovery rates, lift vs holdout/baseline, money, model use) from a committed seed, and explain what each section means. Use when asked to run a batch, regenerate the report, check today's numbers, or explain what the report says.
---

# Batch report

Runs the full pipeline — generate failures → assign arms → classify →
propose → envelope → execute → report — and produces the artifact the pitch
stands on. See `docs/BUILD.md` R8 for the full format spec and `README.md`
for the project's headline claim.

## Reproducing a report

```bash
uv run python tasks.py batch --n 3000 --seed 20260901 --out data/batch_report.json
```

Requirements:

- `GEMINI_API_KEY` and `GROQ_API_KEY` set (`.env`, copy `.env.example`).
  Both are read via `python-dotenv`; `tasks.py` calls `load_dotenv()` at
  import time, so a `.env` file at the repo root is picked up automatically.
- First run at a given `(n, seed)`: expect ~45-90 minutes at `n=3000`. Every
  classify/policy call is cached by `(role, provider, model, prompt_version,
  sha256(payload))` — a second run of the *same* `n`/`seed` makes zero new
  network calls and finishes in seconds, reporting identically.
- To make the first run faster or cheaper, prewarm the cache ahead of time:
  `uv run python -m src.perturb.cli prewarm --limit 500` populates the
  cache for a slice of the reference batch without running the full harness.

Smaller batches (`n < ~2000` with the committed seed) can fail the
simulator's sanity gate (`SanityGateFailure`) — the per-class self-recovery
bands only hold at enough scale. If you need a fast/cheap run for testing
the pipeline itself rather than the numbers, use `FakeProvider` (see
`tests/test_harness.py` for the wiring) instead of shrinking `n`.

## Reading the console output

```
BATCH REPORT — seed: 20260901
Failures: 3000    agent 1500 / baseline 750 / holdout 750

RECOVERY RATES
  Holdout   (no action)              19.1%
  Baseline  (fixed T+1/T+2/T+3)      24.0%
  Agent                              31.4%

LIFT
  vs holdout    +12.3%  [95% CI: 8.1% - 16.5%]
  vs baseline    +7.4%  [95% CI: 3.4% - 11.4%]  ** HEADLINE **
```

- **`vs baseline` is the number to quote.** A merchant already runs the
  fixed retry schedule; `vs holdout` is the honesty story (how much of the
  gross number was never ours), `vs baseline` is the product claim (what
  the agent adds on top of what already exists). Quoting `vs holdout` as
  the headline is the same overclaim this project exists to call out, one
  level up.
- **Estimator check** compares the holdout arm's *sampled* rate against the
  generator's *true* self-recovery rate. If `CI covers truth: NO`, something
  is wrong with either the batch size or the estimator — do not present the
  report until this says `YES`.
- **Per-class breakdown** flags `[thin cell]` when any arm has fewer than
  30 rows in that class — `DEAD` is usually the thin one. Report the wide
  interval and say so; don't round a thin cell's rate to false precision.
- **Money → NET ATTRIBUTABLE** is gross minus what baseline would have
  gotten on the same population, minus contact cost, minus churn cost. This
  is the number that survives the "restraint pays" gate — it's why a
  maximal-contact strategy loses even though it recovers more gross rupees
  (see `tests/test_restraint_gate.py` and `src/eval/spam.py`).
- **Model use** reports real cost (Rs 0, free tier) and a separately-labeled
  shadow cost from `config/pricing.yaml`'s committed list prices. Never
  conflate the two when presenting this.

## If the batch fails a gate

- `SanityGateFailure` at generation time → the population is too small or
  the seed changed; see `src/simulator/sanity_gate.py`.
- `BaselineInvariantViolation` at report time → `rate(baseline) <
  rate(holdout)`, which should be structurally impossible (a fixed retry
  schedule can't do worse than nothing). This means a real bug in the
  generator or executor, not a number to explain away.

Both are hard failures by design (BUILD.md's six build gates) — fix the
underlying cause, don't catch and suppress either exception.
