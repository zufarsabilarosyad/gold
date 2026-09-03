"""Click CLI Commands Submodule for Workflow DAG Management.

Provides CLI command group 'strata dag' for validating DAG YAML/JSON files,
registering workflow definitions, listing registered DAGs, inspecting DAG step structures,
exporting DAG specifications, and deleting DAGs.
"""

import asyncio

import click

from basalt.cli.formatter import CLIFormatter, OutputFormat
from basalt.core.dag.exceptions import BasaltError
from basalt.core.dag.parser import DAGParser
from basalt.core.dag.sorter import DAGSorter
from basalt.core.dag.validator import DAGValidator
from basalt.core.engine.engine import BasaltEngine, EngineConfig


def _run_async(coro):
    """Utility runner executing async coroutines in synchronous Click command callbacks."""
    return asyncio.run(coro)


@click.group(name="dag", help="Manage and validate workflow DAG specifications.")
def dag_group() -> None:
    """Workflow DAG management command group."""
    pass


@dag_group.command(name="validate", help="Validate a YAML/JSON workflow specification file.")
@click.argument("filepath", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "plain"]),
    default="table",
    help="Output formatting style.",
)
def validate_dag_cmd(filepath: str, output_format: str) -> None:
    """Validate AST structure, executor config, and dependency cycle freedom."""
    fmt = OutputFormat(output_format)
    try:
        dag = DAGParser.parse_file(filepath)
        DAGValidator.validate_dag(dag)
        execution_levels = DAGSorter.get_execution_levels(dag)

        if fmt == OutputFormat.JSON:
            res = {
                "valid": True,
                "filepath": filepath,
                "dag_id": dag.id,
                "name": dag.name,
                "step_count": len(dag.steps),
                "execution_stages": len(execution_levels),
            }
            click.echo(CLIFormatter.format_json(res))
        else:
            click.secho(f"✔ Specification '{filepath}' is VALID!", fg="green", bold=True)
            click.echo(CLIFormatter.format_dag_summary(dag, output_format=fmt))

    except BasaltError as exc:
        click.secho(f"✖ Validation Error: [{exc.code}] {exc.message}", fg="red", err=True)
        if fmt == OutputFormat.JSON:
            click.echo(
                CLIFormatter.format_json({"valid": False, "error": exc.message, "code": exc.code})
            )
        raise click.Abort()
    except Exception as exc:
        click.secho(f"✖ Unexpected Validation Failure: {exc}", fg="red", err=True)
        raise click.Abort()


@dag_group.command(
    name="register", help="Register or update a workflow DAG in database repository."
)
@click.argument("filepath", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--db-url", envvar="BASALT_DB_URL", default=None, help="SQLite database connection URL."
)
@click.option(
    "--overwrite/--no-overwrite",
    default=True,
    help="Overwrite existing registered DAG with same ID.",
)
def register_dag_cmd(filepath: str, db_url: str | None, overwrite: bool) -> None:
    """Register workflow DAG specification into database storage."""

    async def _impl():
        config = (
            EngineConfig(db_url=db_url, enable_triggers=False)
            if db_url
            else EngineConfig(use_memory_storage=True)
        )
        async with BasaltEngine(config=config) as engine:
            with open(filepath, encoding="utf-8") as f:
                content = f.read()
            dag = await engine.register_dag(content, overwrite=overwrite)
            click.secho(
                f"✔ Successfully registered DAG '{dag.id}' ({dag.name})", fg="green", bold=True
            )

    try:
        _run_async(_impl())
    except Exception as exc:
        click.secho(f"✖ Registration Failed: {exc}", fg="red", err=True)
        raise click.Abort()


@dag_group.command(name="list", help="List registered workflow DAGs.")
@click.option("--tag", "-t", default=None, help="Filter workflows by tag.")
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
def list_dags_cmd(tag: str | None, db_url: str | None, output_format: str) -> None:
    """List registered workflow DAG definitions."""
    fmt = OutputFormat(output_format)

    async def _impl():
        config = (
            EngineConfig(db_url=db_url, enable_triggers=False)
            if db_url
            else EngineConfig(use_memory_storage=True)
        )
        async with BasaltEngine(config=config) as engine:
            dags = await engine.list_dags(tag=tag)
            click.echo(CLIFormatter.format_dag_list(dags, output_format=fmt))

    try:
        _run_async(_impl())
    except Exception as exc:
        click.secho(f"✖ Failed listing DAGs: {exc}", fg="red", err=True)
        raise click.Abort()


@dag_group.command(name="inspect", help="Inspect a registered workflow DAG definition.")
@click.argument("dag_id")
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
def inspect_dag_cmd(dag_id: str, db_url: str | None, output_format: str) -> None:
    """Inspect specific registered DAG definition."""
    fmt = OutputFormat(output_format)

    async def _impl():
        config = (
            EngineConfig(db_url=db_url, enable_triggers=False)
            if db_url
            else EngineConfig(use_memory_storage=True)
        )
        async with BasaltEngine(config=config) as engine:
            dag = await engine.get_dag(dag_id)
            if not dag:
                click.secho(f"✖ Workflow DAG '{dag_id}' not found.", fg="red", err=True)
                raise click.Abort()
            click.echo(CLIFormatter.format_dag_summary(dag, output_format=fmt))

    try:
        _run_async(_impl())
    except click.Abort:
        raise
    except Exception as exc:
        click.secho(f"✖ Failed inspecting DAG: {exc}", fg="red", err=True)
        raise click.Abort()


@dag_group.command(name="export", help="Export a registered workflow DAG specification to JSON.")
@click.argument("dag_id")
@click.option(
    "--output",
    "-o",
    "output_path",
    type=click.Path(dir_okay=False),
    required=True,
    help="Destination output file path.",
)
@click.option(
    "--db-url", envvar="BASALT_DB_URL", default=None, help="SQLite database connection URL."
)
def export_dag_cmd(dag_id: str, output_path: str, db_url: str | None) -> None:
    """Export registered workflow DAG AST model to JSON file."""

    async def _impl():
        config = (
            EngineConfig(db_url=db_url, enable_triggers=False)
            if db_url
            else EngineConfig(use_memory_storage=True)
        )
        async with BasaltEngine(config=config) as engine:
            dag = await engine.get_dag(dag_id)
            if not dag:
                click.secho(f"✖ Workflow DAG '{dag_id}' not found.", fg="red", err=True)
                raise click.Abort()

            json_str = CLIFormatter.format_json(dag)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(json_str)
            click.secho(f"✔ Successfully exported DAG '{dag_id}' to '{output_path}'.", fg="green")

    try:
        _run_async(_impl())
    except click.Abort:
        raise
    except Exception as exc:
        click.secho(f"✖ Export Failed: {exc}", fg="red", err=True)
        raise click.Abort()


@dag_group.command(name="delete", help="Delete a registered workflow DAG.")
@click.argument("dag_id")
@click.option(
    "--db-url", envvar="BASALT_DB_URL", default=None, help="SQLite database connection URL."
)
def delete_dag_cmd(dag_id: str, db_url: str | None) -> None:
    """Delete registered workflow DAG definition."""

    async def _impl():
        config = (
            EngineConfig(db_url=db_url, enable_triggers=False)
            if db_url
            else EngineConfig(use_memory_storage=True)
        )
        async with BasaltEngine(config=config) as engine:
            deleted = await engine.delete_dag(dag_id)
            if deleted:
                click.secho(f"✔ Successfully deleted DAG '{dag_id}'.", fg="green")
            else:
                click.secho(f"✖ Workflow DAG '{dag_id}' not found.", fg="red", err=True)

    try:
        _run_async(_impl())
    except Exception as exc:
        click.secho(f"✖ Failed deleting DAG: {exc}", fg="red", err=True)
        raise click.Abort()
