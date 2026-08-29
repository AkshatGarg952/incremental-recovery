"""Batch generator CLI — BUILD.md task 2.7.

uv run python -m src.simulator.cli generate --n 3000 --seed 20260901 --out data/batch.jsonl
uv run python -m src.simulator.cli summarize --n 3000 --seed 20260901 --out data/summary.md
"""

from pathlib import Path

import typer

from src.simulator.generator import generate_batch
from src.simulator.sanity_gate import SanityGateFailure
from src.simulator.summary import render_distribution_summary

app = typer.Typer(no_args_is_help=True)


@app.command()
def generate(
    n: int = typer.Option(3000, "--n", help="Number of failures to generate."),
    seed: int = typer.Option(20260901, "--seed", help="Random seed."),
    out: str = typer.Option("data/batch.jsonl", "--out", help="Output path for the JSONL batch."),
) -> None:
    """Generate a batch of payment failures and write it as JSONL.

    Aborts with no output written if the batch fails the sanity gate
    (BUILD.md task 2.8) — a bad batch must never reach disk.
    """
    try:
        batch = generate_batch(n=n, seed=seed)
    except SanityGateFailure as exc:
        typer.echo(f"sanity gate failed, aborting generation: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for failure in batch.failures:
            handle.write(failure.model_dump_json() + "\n")

    typer.echo(f"wrote {len(batch.failures)} failures to {out_path}")


@app.command()
def summarize(
    n: int = typer.Option(3000, "--n", help="Number of failures to generate."),
    seed: int = typer.Option(20260901, "--seed", help="Random seed."),
    out: str = typer.Option(
        "data/summary.md", "--out", help="Output path for the markdown summary."
    ),
) -> None:
    """Generate a batch (in memory) and write its distribution summary as markdown."""
    try:
        batch = generate_batch(n=n, seed=seed)
    except SanityGateFailure as exc:
        typer.echo(f"sanity gate failed, aborting generation: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_distribution_summary(batch), encoding="utf-8")

    typer.echo(f"wrote distribution summary to {out_path}")


if __name__ == "__main__":
    app()
