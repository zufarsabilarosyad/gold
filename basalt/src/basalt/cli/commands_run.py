"""Click CLI Commands Submodule for Workflow Execution Runs.

Provides CLI command group 'strata run' for initiating DAG workflow runs,
inspecting execution run status ledgers, querying step output logs, listing historical run records,
cancelling active runs, and retrying failed runs.
"""

import asyncio
import json
import os

import click

from basalt.cli.formatter import CLIFormatter, OutputFormat
from basalt.core.engine.engine import BasaltEngine, EngineConfig
from basalt.core.engine.state_machine import WorkflowState


def _run_async(coro):
    """Utility runner executing async coroutines in synchronous Click command callbacks."""
    return asyncio.run(coro)


@click.group(name="run", help="Trigger and inspect workflow DAG execution runs.")
def run_group() -> None:
    """Workflow execution run command group."""
    pass


@run_group.command(
    name="start", help="Start execution of a workflow DAG from file or registered ID."
)
@click.argument("target")
@click.option(
    "--inputs", "-i", default=None, help="JSON input parameters string (e.g. '{\"x\": 42}')."
)
@click.option("--run-id", default=None, help="Optional custom run identifier.")
@click.option(
    "--db-url", envvar="BASALT_DB_URL", default=None, help="SQLite database connection URL."
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "plain"]),
    default="table",
    help="Output formatting style.",
)
def start_run_cmd(
    target: str,
    inputs: str | None,
    run_id: str | None,
    db_url: str | None,
    output_format: str,
) -> None:
    """Execute workflow DAG and print run ledger results."""
    fmt = OutputFormat(output_format)
    input_dict = json.loads(inputs) if inputs else None

    async def _impl():
        config = (
            EngineConfig(db_url=db_url, enable_triggers=False)
            if db_url
            else EngineConfig(use_memory_storage=True)
        )
        async with BasaltEngine(config=config) as engine:
            # Check if target is a file path that exists
            if os.path.isfile(target):
                with open(target, encoding="utf-8") as f:
                    content = f.read()
                dag = await engine.register_dag(content, overwrite=True)
                target_id = dag.id
            else:
                target_id = target

            click.echo(f"Initiating execution run for workflow '{target_id}'...")
            result = await engine.run_dag(target_id, inputs=input_dict, run_id=run_id)

            if result.state == WorkflowState.COMPLETED:
                click.secho(
                    f"✔ Workflow run '{result.run_id}' COMPLETED successfully!",
                    fg="green",
                    bold=True,
                )
            else:
                click.secho(
                    f"✖ Workflow run '{result.run_id}' finished in state '{result.state.value.upper()}'",
                    fg="red",
                    bold=True,
                )

            click.echo(CLIFormatter.format_run_result(result, output_format=fmt))

    try:
        _run_async(_impl())
    except Exception as exc:
        click.secho(f"✖ Execution Failed: {exc}", fg="red", err=True)
        raise click.Abort()


@run_group.command(name="status", help="Get execution status for a specific run ID.")
@click.argument("run_id")
@click.option(
    "--db-url", envvar="BASALT_DB_URL", default=None, help="SQLite database connection URL."
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "plain"]),
    default="table",
    help="Output formatting style.",
)
def get_run_status_cmd(run_id: str, db_url: str | None, output_format: str) -> None:
    """Inspect status, outputs, and step execution details for a run ID."""
    fmt = OutputFormat(output_format)

    async def _impl():
        config = (
            EngineConfig(db_url=db_url, enable_triggers=False)
            if db_url
            else EngineConfig(use_memory_storage=True)
        )
        async with BasaltEngine(config=config) as engine:
            result = await engine.get_run_result(run_id)
            if not result:
                click.secho(f"✖ Execution run ID '{run_id}' not found.", fg="red", err=True)
                raise click.Abort()
            click.echo(CLIFormatter.format_run_result(result, output_format=fmt))

    try:
        _run_async(_impl())
    except click.Abort:
        raise
    except Exception as exc:
        click.secho(f"✖ Failed retrieving run status: {exc}", fg="red", err=True)
        raise click.Abort()


@run_group.command(
    name="step", help="Inspect step output payload for a specific run ID and step ID."
)
@click.argument("run_id")
@click.argument("step_id")
@click.option(
    "--db-url", envvar="BASALT_DB_URL", default=None, help="SQLite database connection URL."
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "plain"]),
    default="json",
    help="Output formatting style.",
)
def get_step_output_cmd(run_id: str, step_id: str, db_url: str | None, output_format: str) -> None:
    """Inspect output returned by a specific step within an execution run."""
    fmt = OutputFormat(output_format)

    async def _impl():
        config = (
            EngineConfig(db_url=db_url, enable_triggers=False)
            if db_url
            else EngineConfig(use_memory_storage=True)
        )
        async with BasaltEngine(config=config) as engine:
            result = await engine.get_run_result(run_id)
            if not result:
                click.secho(f"✖ Execution run ID '{run_id}' not found.", fg="red", err=True)
                raise click.Abort()

            if step_id not in result.step_states:
                click.secho(
                    f"✖ Step ID '{step_id}' was not executed in run '{run_id}'.", fg="red", err=True
                )
                raise click.Abort()

            step_data = {
                "run_id": run_id,
                "dag_id": result.dag_id,
                "step_id": step_id,
                "state": result.step_states[step_id].value,
                "attempt": result.step_attempts.get(step_id, 1),
                "output": result.outputs.get(step_id),
            }

            click.echo(CLIFormatter.format_json(step_data))

    try:
        _run_async(_impl())
    except click.Abort:
        raise
    except Exception as exc:
        click.secho(f"✖ Failed retrieving step output: {exc}", fg="red", err=True)
        raise click.Abort()


@run_group.command(name="list", help="List workflow execution run logs.")
@click.option("--dag-id", "-d", default=None, help="Filter run logs by DAG ID.")
@click.option(
    "--state", "-s", default=None, help="Filter run logs by state (completed, failed, etc)."
)
@click.option(
    "--db-url", envvar="BASALT_DB_URL", default=None, help="SQLite database connection URL."
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "plain"]),
    default="table",
    help="Output formatting style.",
)
def list_runs_cmd(
    dag_id: str | None,
    state: str | None,
    db_url: str | None,
    output_format: str,
) -> None:
    """Query and list execution run records."""
    fmt = OutputFormat(output_format)
    target_state = WorkflowState(state.lower()) if state else None

    async def _impl():
        config = (
            EngineConfig(db_url=db_url, enable_triggers=False)
            if db_url
            else EngineConfig(use_memory_storage=True)
        )
        async with BasaltEngine(config=config) as engine:
            runs = await engine.list_run_results(dag_id=dag_id, state=target_state)
            click.echo(CLIFormatter.format_run_list(runs, output_format=fmt))

    try:
        _run_async(_impl())
    except Exception as exc:
        click.secho(f"✖ Failed listing runs: {exc}", fg="red", err=True)
        raise click.Abort()


@run_group.command(name="cancel", help="Cancel an active workflow run.")
@click.argument("run_id")
@click.option(
    "--db-url", envvar="BASALT_DB_URL", default=None, help="SQLite database connection URL."
)
def cancel_run_cmd(run_id: str, db_url: str | None) -> None:
    """Request cancellation for active workflow run."""

    async def _impl():
        config = (
            EngineConfig(db_url=db_url, enable_triggers=False)
            if db_url
            else EngineConfig(use_memory_storage=True)
        )
        async with BasaltEngine(config=config) as engine:
            cancelled = engine.runner.cancel_run(run_id)
            if cancelled:
                click.secho(f"✔ Sent cancellation signal to active run '{run_id}'.", fg="green")
            else:
                click.secho(
                    f"✖ Run ID '{run_id}' is not active or cannot be cancelled.", fg="red", err=True
                )
                raise click.Abort()

    try:
        _run_async(_impl())
    except Exception as exc:
        click.secho(f"✖ Failed cancelling run: {exc}", fg="red", err=True)
        raise click.Abort()


@run_group.command(name="retry", help="Retry a failed workflow run.")
@click.argument("run_id")
@click.option(
    "--db-url", envvar="BASALT_DB_URL", default=None, help="SQLite database connection URL."
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "plain"]),
    default="table",
    help="Output formatting style.",
)
def retry_run_cmd(run_id: str, db_url: str | None, output_format: str) -> None:
    """Re-trigger execution of a failed workflow run."""
    fmt = OutputFormat(output_format)

    async def _impl():
        config = (
            EngineConfig(db_url=db_url, enable_triggers=False)
            if db_url
            else EngineConfig(use_memory_storage=True)
        )
        async with BasaltEngine(config=config) as engine:
            original = await engine.get_run_result(run_id)
            if not original:
                click.secho(f"✖ Execution run ID '{run_id}' not found.", fg="red", err=True)
                raise click.Abort()

            if original.state not in (
                WorkflowState.FAILED,
                WorkflowState.TIMEOUT,
                WorkflowState.CANCELLED,
            ):
                click.secho(
                    f"✖ Run '{run_id}' is in state '{original.state.value}' and cannot be retried.",
                    fg="red",
                    err=True,
                )
                raise click.Abort()

            click.echo(f"Retrying failed run '{run_id}' for DAG '{original.dag_id}'...")
            new_result = await engine.run_dag(original.dag_id, inputs=original.inputs)
            click.echo(CLIFormatter.format_run_result(new_result, output_format=fmt))

    try:
        _run_async(_impl())
    except click.Abort:
        raise
    except Exception as exc:
        click.secho(f"✖ Failed retrying run: {exc}", fg="red", err=True)
        raise click.Abort()
