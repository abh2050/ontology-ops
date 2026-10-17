"""`ops` command line. Every command exits nonzero with a clear message on failure."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from ops.settings import REPO_ROOT

app = typer.Typer(no_args_is_help=True, add_completion=False, pretty_exceptions_enable=False)
data_app = typer.Typer(no_args_is_help=True, help="Import, validate, and inspect source data.")
scenario_app = typer.Typer(no_args_is_help=True, help="Synthetic scenario overlay.")
app.add_typer(data_app, name="data")
app.add_typer(scenario_app, name="scenario")


class OpsError(Exception):
    """An expected failure with a message safe to print."""


def _fail(message: str) -> None:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


@app.command()
def migrate() -> None:
    """Apply Alembic migrations as the migration/admin role."""
    import os

    from alembic import command
    from alembic.config import Config

    if os.environ.get("OPS_BOOTSTRAP_ROLES") == "1":
        from ops.data.bootstrap import bootstrap_roles

        try:
            typer.echo("runtime roles ready: " + ", ".join(bootstrap_roles()))
        except Exception as exc:  # noqa: BLE001
            _fail(f"role bootstrap failed: {exc}")
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "db"))
    try:
        command.upgrade(cfg, "head")
    except Exception as exc:  # noqa: BLE001 - surface the reason, exit nonzero
        _fail(f"migration failed: {exc}")
    typer.echo("migrations applied")


@data_app.command("import")
def data_import(
    directory: Annotated[Path, typer.Option(help="Directory holding the five source CSVs.")],
    batch: Annotated[
        str | None,
        typer.Option(help="Batch id. Only 'fixtures-v1' may be named; Olist ids are derived."),
    ] = None,
    download_date: Annotated[
        str | None, typer.Option(help="Kaggle download date YYYY-MM-DD (default: file mtime).")
    ] = None,
) -> None:
    """Validate and import the five source files into a new batch."""
    from ops.data.importer import ImportError_, run_import

    try:
        dl = date.fromisoformat(download_date) if download_date else None
        if str(directory).startswith("s3:/"):
            from ops.data.s3 import download_sources

            directory = download_sources(str(directory).replace("s3:/", "s3://", 1)
                                         if not str(directory).startswith("s3://")
                                         else str(directory))
        result = run_import(directory, batch_id=batch, download_date=dl)
    except (ImportError_, ValueError, FileNotFoundError) as exc:
        _fail(str(exc))
    typer.echo(result.summary())


@data_app.command("validate")
def data_validate(
    batch: Annotated[
        str | None, typer.Option(help="Batch id (default: latest Olist batch).")
    ] = None,
) -> None:
    """Recheck an imported batch against its manifest and integrity rules."""
    from ops.data.validate import ValidationFailed, validate_batch

    try:
        report = validate_batch(batch)
    except ValidationFailed as exc:
        _fail(str(exc))
    typer.echo(report)


@data_app.command("pick-as-of")
def data_pick_as_of(
    batch: Annotated[
        str | None, typer.Option(help="Batch id (default: latest Olist batch).")
    ] = None,
) -> None:
    """Evaluate every day in the demo window and record the default demo as_of."""
    from ops.data.as_of import AsOfError, pick_as_of

    try:
        chosen = pick_as_of(batch)
    except AsOfError as exc:
        _fail(str(exc))
    typer.echo(chosen)


@scenario_app.command("generate")
def scenario_generate(
    seed: Annotated[int, typer.Option(help="Generator seed.")],
    scenario: Annotated[str, typer.Option(help="Scenario id, e.g. base-v1.")],
) -> None:
    """Generate the deterministic synthetic carrier and disruption overlay."""
    from ops.data.scenario import ScenarioError, generate

    try:
        summary = generate(seed=seed, scenario_id=scenario)
    except ScenarioError as exc:
        _fail(str(exc))
    typer.echo(summary)


def _not_yet(milestone: str) -> None:
    _fail(f"not implemented until {milestone}")


@app.command("seed-users")
def seed_users(mode: Annotated[str, typer.Option(help="local or aws")]) -> None:
    """Provision operator_a, operator_b, reviewer, viewer and seller grants."""
    from ops.data.users import SeedError
    from ops.data.users import seed_users as run

    try:
        typer.echo(run(mode))
    except SeedError as exc:
        _fail(str(exc))


@app.command("eval")
def eval_(suite: Annotated[str, typer.Option(help="Evaluation suite, e.g. frozen.")]) -> None:
    """Run the frozen evaluation within the eval budget."""
    _not_yet("M5")


@app.command()
def worker(
    queue: Annotated[str, typer.Option(help="fixture or sqs")],
    provider: Annotated[str, typer.Option(help="fixture or bedrock")],
) -> None:
    """Run the outbox relay and the bounded job consumer."""
    from ops.worker import run

    try:
        run(queue, provider)
    except RuntimeError as exc:
        _fail(str(exc))


@app.command("recover-job")
def recover_job(
    job_id: Annotated[str, typer.Argument(help="Job UUID")],
    mark_failed: Annotated[bool, typer.Option(help="Resolve the unknown hold as failed.")] = False,
    note: Annotated[str, typer.Option(help="Reconciliation note for the audit log.")] = "",
) -> None:
    """Reconcile a job stage held in sent or unknown state."""
    from ops.jobs.recovery import RecoveryError, describe
    from ops.jobs.recovery import mark_failed as resolve

    try:
        typer.echo(describe(job_id))
        if mark_failed:
            typer.echo(resolve(job_id, note or "reconciled by operator"))
    except (RecoveryError, ValueError) as exc:
        _fail(str(exc))


@app.command("export-demo")
def export_demo() -> None:
    """Export sanitized static evidence for the public replay."""
    _not_yet("M6")


@app.command()
def preflight(cloud: Annotated[str, typer.Option(help="Cloud target: aws")]) -> None:
    """Verify cloud inputs and model access; print an estimated cost table."""
    from ops.preflight import run_preflight

    ok, report = run_preflight(cloud)
    typer.echo(report)
    if not ok:
        raise typer.Exit(code=1)


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
