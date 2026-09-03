"""Click CLI Commands Submodule for HTTP Server Administration.

Provides CLI command group 'strata server' for launching the FastAPI REST API server
via uvicorn, probing server health, inspecting telemetry info, and reading live metrics.
"""

import click
import httpx

from basalt.cli.formatter import CLIFormatter
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


@click.group(name="server", help="Launch and manage Basalt FastAPI HTTP REST server.")
def server_group() -> None:
    """HTTP REST server administration command group."""
    pass


@server_group.command(name="start", help="Start the Basalt REST API HTTP server daemon.")
@click.option("--host", "-h", default="127.0.0.1", help="Bind IP address for HTTP server.")
@click.option("--port", "-p", default=8000, type=int, help="Bind port number for HTTP server.")
@click.option("--reload/--no-reload", default=False, help="Enable auto-reload on code change.")
@click.option("--workers", "-w", default=1, type=int, help="Number of worker processes.")
def start_server_cmd(host: str, port: int, reload: bool, workers: int) -> None:
    """Start uvicorn ASGI web server serving Basalt REST API."""
    click.secho(
        f"🚀 Launching Basalt REST API server on http://{host}:{port} (workers={workers}, reload={reload})...",
        fg="green",
        bold=True,
    )

    try:
        import uvicorn

        uvicorn.run(
            "basalt.api.app:app",
            host=host,
            port=port,
            reload=reload,
            workers=workers,
            log_level="info",
        )
    except ImportError:
        click.secho(
            "✖ Uvicorn is required to run the server. Install with `pip install uvicorn`.",
            fg="red",
            err=True,
        )
        raise click.Abort()
    except Exception as exc:
        click.secho(f"✖ Failed to launch server: {exc}", fg="red", err=True)
        raise click.Abort()


@server_group.command(name="status", help="Probe health status of a running Basalt server.")
@click.option("--url", default="http://127.0.0.1:8000", help="Basalt HTTP server base URL.")
def server_status_cmd(url: str) -> None:
    """Check health and ping response from a running Basalt API server instance."""
    target_url = f"{url.rstrip('/')}/health"
    click.echo(f"Probing server health at '{target_url}'...")

    try:
        response = httpx.get(target_url, timeout=3.0)
        if response.status_code == 200:
            data = response.json()
            click.secho("✔ Server is ONLINE and HEALTHY!", fg="green", bold=True)
            click.echo(f"  Version: {data.get('version')}")
            click.echo(f"  Storage Backend: {data.get('storage_backend')}")
            click.echo(f"  Active Runs: {data.get('active_runs')}")
        else:
            click.secho(f"✖ Server returned HTTP status code {response.status_code}", fg="yellow")
    except Exception as exc:
        click.secho(f"✖ Server is OFFLINE or unreachable at '{target_url}' ({exc}).", fg="red")


@server_group.command(name="info", help="Retrieve telemetry information from running server.")
@click.option("--url", default="http://127.0.0.1:8000", help="Basalt HTTP server base URL.")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "plain"]),
    default="json",
    help="Output formatting style.",
)
def server_info_cmd(url: str, output_format: str) -> None:
    """Query telemetry and system environment info from running API server."""
    target_url = f"{url.rstrip('/')}/info"
    try:
        response = httpx.get(target_url, timeout=3.0)
        if response.status_code == 200:
            data = response.json()
            click.echo(CLIFormatter.format_json(data))
        else:
            click.secho(
                f"✖ Failed retrieving server info (HTTP {response.status_code})", fg="red", err=True
            )
    except Exception as exc:
        click.secho(f"✖ Server is OFFLINE or unreachable: {exc}", fg="red", err=True)


@server_group.command(name="metrics", help="Retrieve live telemetry metrics from running server.")
@click.option("--url", default="http://127.0.0.1:8000", help="Basalt HTTP server base URL.")
def server_metrics_cmd(url: str) -> None:
    """Query worker pool telemetry metrics from running API server."""
    target_url = f"{url.rstrip('/')}/metrics"
    try:
        response = httpx.get(target_url, timeout=3.0)
        if response.status_code == 200:
            data = response.json()
            click.echo(CLIFormatter.format_json(data))
        else:
            click.secho(
                f"✖ Failed retrieving metrics (HTTP {response.status_code})", fg="red", err=True
            )
    except Exception as exc:
        click.secho(f"✖ Server is OFFLINE or unreachable: {exc}", fg="red", err=True)
