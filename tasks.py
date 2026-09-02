"""Task runner: lint, test, and batch entry points."""

import subprocess
from pathlib import Path

import typer
from dotenv import load_dotenv

load_dotenv()

app = typer.Typer(no_args_is_help=True)


@app.command()
def lint() -> None:
    """Run ruff check and format --check."""
    subprocess.run(["ruff", "check", "."], check=True)
    subprocess.run(["ruff", "format", "--check", "."], check=True)


@app.command()
def test() -> None:
    """Run the pytest suite."""
    subprocess.run(["pytest"], check=True)


@app.command()
def batch(
    n: int = typer.Option(3000, help="Number of failures to generate."),
    seed: int = typer.Option(20260901, help="Random seed."),
    out: str = typer.Option("data/batch_report.json", help="Where to write the JSON report."),
    cache_path: str = typer.Option("cache/llm_responses.sqlite3", help="Response cache path."),
) -> None:
    """Run a full simulate -> assign -> classify -> policy -> execute -> eval batch.

    Requires GEMINI_API_KEY and GROQ_API_KEY (see .env.example) the first
    time a given seed/n is run; every classify/policy call is cached by
    (role, provider, model, prompt_version, payload), so a repeat run of
    the same batch makes zero new network calls and reports identically.
    """
    from src.agent.classifier import needs_llm_adjudication
    from src.agent.policy import load_economics_config
    from src.eval.assignment import DEFAULT_ALLOCATION, assign_arms
    from src.eval.harness import run_batch
    from src.eval.metering import RoutingMeteringChatClient
    from src.eval.report import build_batch_report, render_console, render_json
    from src.executor.clock import SimulatedClock
    from src.executor.ledger import Ledger
    from src.llm.cache import ResponseCache
    from src.llm.cost import TokenAccountant, load_pricing
    from src.perturb.config import build_role_clients, load_providers_config
    from src.simulator.generator import generate_batch

    typer.echo(f"generating batch: n={n} seed={seed}")
    generated = generate_batch(n=n, seed=seed)
    assignment = assign_arms(generated.failures, seed=seed, allocation=DEFAULT_ALLOCATION)
    ambiguous_rate = sum(1 for f in generated.failures if needs_llm_adjudication(f)) / len(
        generated.failures
    )

    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    cache = ResponseCache(cache_path)
    providers_config = load_providers_config()
    classify_client, classify_model, policy_client, policy_model = build_role_clients(
        cache, providers_config
    )

    accountant = TokenAccountant(load_pricing())
    client = RoutingMeteringChatClient(
        {classify_model: classify_client, policy_model: policy_client}, accountant
    )

    ledger = Ledger(":memory:")
    clock = SimulatedClock(generated.failures[0].failed_at)
    economics_config = load_economics_config()

    typer.echo("running batch...")
    result = run_batch(
        generated.failures,
        assignment,
        generated.latent_outcomes,
        client,
        classify_model,
        policy_model,
        ledger,
        clock,
        seed=seed,
        economics_config=economics_config,
    )

    report = build_batch_report(result, generated.latent_outcomes, client, ambiguous_rate, seed)

    typer.echo(render_console(report))

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_json(report), encoding="utf-8")
    typer.echo(f"wrote {out_path}")


if __name__ == "__main__":
    app()
