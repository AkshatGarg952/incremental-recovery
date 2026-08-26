"""Task runner: lint, test, and batch entry points."""

import subprocess

import typer

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
) -> None:
    """Run a full simulate -> classify -> policy -> execute -> eval batch."""
    typer.echo(f"batch runner not wired yet (n={n}, seed={seed})")
    typer.echo("lands with the simulator and eval harness")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
