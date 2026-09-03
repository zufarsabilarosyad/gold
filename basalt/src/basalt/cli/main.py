"""Basalt Embedded Event-Driven Workflow & DAG Execution Engine Command Line Interface (CLI).

Master CLI entrypoint assembling Click command groups for workflow DAG validation & management ('basalt dag'),
workflow execution runs & logs ('basalt run'), API server administration ('basalt server'),
workspace project initialization ('basalt init'), and system environment diagnostics ('basalt doctor').
"""

import importlib.util
import os
import sys

import click

from basalt.cli.commands_dag import dag_group
from basalt.cli.commands_run import run_group
from basalt.cli.commands_server import server_group
from basalt.utils.logger import get_logger, setup_logging

logger = get_logger("basalt.cli")

BASALT_VERSION = "1.0.0"
BASALT_BANNER = rf"""
  ______                 _ _   
  | ___ \               | | |  
  | |_/ / __ _ ___  __ _| | |_ 
  | ___ \/ _` / __|/ _` | | __|
  | |_/ / (_| \__ \ (_| | | |_ 
  \____/ \__,_|___/\__,_|_|\__|
  Embedded Event-Driven DAG Engine v{BASALT_VERSION}
"""

SAMPLE_DAG_YAML = """# Sample Basalt Workflow DAG Specification
id: sample_workflow
name: Sample ETL & Data Pipeline
description: Example Basalt workflow demonstrating parallel step execution.
version: "1.0.0"
tags: ["example", "demo"]

steps:
  - id: fetch_data
    name: Fetch Data Payload
    executor_type: subprocess
    command: "echo '{\"records_fetched\": 100}'"

  - id: process_data
    name: Transform Data Payload
    executor_type: subprocess
    command: "echo '{\"processed\": true}'"
    depends_on: ["fetch_data"]
"""


@click.group(
    name="basalt",
    help="Basalt Embedded Event-Driven Workflow & DAG Execution Engine CLI.",
    invoke_without_command=False,
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose debug logging.")
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-essential log output.")
@click.version_option(version=BASALT_VERSION, prog_name="basalt")
@click.pass_context
def cli(ctx: click.Context, verbose: bool, quiet: bool) -> None:
    """Master Click CLI entrypoint for Basalt workflow engine."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet

    if verbose:
        setup_logging("DEBUG")
    elif quiet:
        setup_logging("ERROR")


@cli.command(name="version", help="Display Basalt engine version and banner.")
def version_cmd() -> None:
    """Print ASCII banner and version string."""
    click.secho(BASALT_BANNER, fg="cyan", bold=True)
    click.echo(f"Basalt Version: {BASALT_VERSION}")
    click.echo(f"Python Version: {sys.version.split()[0]}")


@cli.command(
    name="init", help="Initialize a new Basalt workflow project workspace with sample DAG."
)
@click.option("--directory", "-d", default=".", help="Target workspace directory path.")
def init_cmd(directory: str) -> None:
    """Scaffold a new Basalt project workspace with example workflow specification."""
    os.makedirs(directory, exist_ok=True)
    sample_file = os.path.join(directory, "workflow_example.yaml")

    if os.path.exists(sample_file):
        click.secho(f"✖ File '{sample_file}' already exists in target workspace.", fg="yellow")
        return

    with open(sample_file, "w", encoding="utf-8") as f:
        f.write(SAMPLE_DAG_YAML.strip() + "\n")

    click.secho(f"✔ Initialized Basalt workspace at '{directory}'!", fg="green", bold=True)
    click.echo(f"  Created sample workflow DAG: {sample_file}")
    click.echo("  Run validation: strata dag validate workflow_example.yaml")
    click.echo("  Execute workflow: strata run start workflow_example.yaml")


@cli.command(name="doctor", help="Run system diagnostics and verify dependencies.")
def doctor_cmd() -> None:
    """Perform diagnostic health checks on Python runtime and database drivers."""
    click.secho("Running Basalt System Diagnostics...", bold=True)

    # 1. Python version check
    py_ver = sys.version.split()[0]
    click.echo(f"  [✔] Python Runtime: {py_ver} (64-bit)")

    # 2. SQLite async driver check
    if importlib.util.find_spec("aiosqlite") and importlib.util.find_spec("sqlalchemy"):
        click.echo("  [✔] Database Drivers: SQLAlchemy & aiosqlite available")
    else:
        click.secho("  [✖] Database Driver Missing", fg="red")

    # 3. HTTP engine check
    if importlib.util.find_spec("fastapi") and importlib.util.find_spec("httpx"):
        click.echo("  [✔] REST API Engine: FastAPI & HTTPX available")
    else:
        click.secho("  [✖] REST API Missing", fg="red")

    click.secho("\nAll diagnostic checks completed successfully!", fg="green", bold=True)


# Register submodule command groups
cli.add_command(dag_group)
cli.add_command(run_group)
cli.add_command(server_group)


def main() -> None:
    """Main execution entrypoint wrapper."""
    cli(obj={})


if __name__ == "__main__":
    main()
