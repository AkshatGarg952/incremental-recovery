"""Perturbation CLI — BUILD.md tasks 9.3-9.4.

    uv run python -m src.perturb.cli outage --issuer HDFC --outage 45m
    uv run python -m src.perturb.cli prewarm --limit 200

Live network calls only happen here, against the real Gemini/Groq clients
— everything these commands call (the engine, invalidation, re-plan) is
unit-tested offline against FakeProvider; this module itself is not.
"""

from pathlib import Path

import typer

from src.agent.classifier import classify_failure
from src.agent.policy import load_economics_config, propose_policy
from src.llm.cache import ResponseCache
from src.perturb.cache_invalidation import invalidate_cache_for_failures
from src.perturb.config import build_role_clients, load_providers_config
from src.perturb.engine import apply_issuer_outage
from src.perturb.replan import render_decision_diffs, replan_affected_failures
from src.simulator.schemas import PaymentFailure

app = typer.Typer(no_args_is_help=True)

_DEFAULT_BATCH_PATH = "data/reference_batch.jsonl"
_DEFAULT_CACHE_PATH = "cache/llm_responses.sqlite3"


def _load_batch(path: str) -> list[PaymentFailure]:
    failures = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                failures.append(PaymentFailure.model_validate_json(line))
    return failures


def _parse_duration_hours(text: str) -> float:
    text = text.strip().lower()
    if text.endswith("m"):
        return float(text[:-1]) / 60
    if text.endswith("h"):
        return float(text[:-1])
    return float(text)


@app.command()
def outage(
    issuer: str = typer.Option(..., "--issuer", help="Issuer code, e.g. HDFC"),
    outage_duration: str = typer.Option(..., "--outage", help="Duration, e.g. 45m or 2h"),
    batch_path: str = typer.Option(_DEFAULT_BATCH_PATH, "--batch"),
    cache_path: str = typer.Option(_DEFAULT_CACHE_PATH, "--cache"),
    max_rows: int = typer.Option(40, "--max-rows"),
) -> None:
    """Inject a live issuer outage and re-plan the affected slice."""
    failures = _load_batch(batch_path)
    duration_hours = _parse_duration_hours(outage_duration)

    result = apply_issuer_outage(failures, issuer, duration_hours, max_affected=max_rows)
    if not result.affected_failure_ids:
        typer.echo(f"no pending failures found for issuer {issuer!r} in {batch_path}")
        raise typer.Exit(code=1)

    typer.echo(
        f"{result.description} — {len(result.affected_failure_ids)} failures affected, "
        "re-planning..."
    )

    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    cache = ResponseCache(cache_path)
    providers_config = load_providers_config()
    classify_client, classify_model, policy_client, policy_model = build_role_clients(
        cache, providers_config
    )

    # Ensure the "after" state always makes a genuinely live call, even if
    # this exact perturbation was already run once before (BUILD.md 9.2).
    recovery_classes: dict = {}
    for failure_id, perturbed in result.perturbed_by_id.items():
        classification = classify_failure(perturbed, classify_client, classify_model)
        if classification.recovery_class is not None:
            recovery_classes[failure_id] = classification.recovery_class
    invalidate_cache_for_failures(
        cache,
        list(result.perturbed_by_id.values()),
        recovery_classes,
        classify_model,
        providers_config["roles"]["classify"]["provider"],
        policy_model,
        providers_config["roles"]["policy"]["provider"],
    )

    economics_config = load_economics_config()
    diffs = replan_affected_failures(
        result.original_by_id,
        result.perturbed_by_id,
        classify_client,
        classify_model,
        policy_client,
        policy_model,
        economics_config,
    )
    typer.echo(render_decision_diffs(diffs))


@app.command()
def prewarm(
    batch_path: str = typer.Option(_DEFAULT_BATCH_PATH, "--batch"),
    cache_path: str = typer.Option(_DEFAULT_CACHE_PATH, "--cache"),
    limit: int = typer.Option(0, "--limit", help="Only prewarm the first N failures (0 = all)"),
) -> None:
    """Populate the cache for the demo batch ahead of time, so the live
    demo and any re-plan hit cache instead of the free-tier rate limit.
    """
    failures = _load_batch(batch_path)
    if limit > 0:
        failures = failures[:limit]

    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    cache = ResponseCache(cache_path)
    providers_config = load_providers_config()
    classify_client, classify_model, policy_client, policy_model = build_role_clients(
        cache, providers_config
    )
    economics_config = load_economics_config()

    with typer.progressbar(failures, label="prewarming") as progress:
        for failure in progress:
            classification = classify_failure(failure, classify_client, classify_model)
            if classification.recovery_class is not None:
                propose_policy(
                    failure,
                    classification.recovery_class,
                    policy_client,
                    policy_model,
                    economics_config,
                )

    typer.echo(f"prewarmed cache for {len(failures)} failures -> {cache_path}")


if __name__ == "__main__":
    app()
