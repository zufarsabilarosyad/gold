"""Unit and Integration Test Suite for Click CLI Commands Subsystem.

Tests all CLI command groups ('strata dag', 'strata run', 'strata server', 'strata init', 'strata doctor')
using Click's CliRunner, validating exit codes, table outputs, JSON output formatting, and error handling.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from basalt.cli.main import cli


@pytest.fixture
def cli_runner() -> CliRunner:
    """Pytest fixture providing Click CliRunner instance."""
    return CliRunner()


# --- Main Entrypoint & System Commands Tests ---


def test_cli_version_and_doctor_commands(cli_runner: CliRunner) -> None:
    """Verify strata --version, strata version, strata doctor, and strata init commands."""
    # 1. Flag --version
    res_flag = cli_runner.invoke(cli, ["--version"])
    assert res_flag.exit_code == 0
    assert "1.0.0" in res_flag.output

    # 2. Command version
    res_ver = cli_runner.invoke(cli, ["version"])
    assert res_ver.exit_code == 0
    assert "Basalt Version: 1.0.0" in res_ver.output

    # 3. Command doctor
    res_doc = cli_runner.invoke(cli, ["doctor"])
    assert res_doc.exit_code == 0
    assert "Diagnostic" in res_doc.output
    assert "Python Runtime" in res_doc.output

    # 4. Command init
    with cli_runner.isolated_filesystem():
        res_init = cli_runner.invoke(cli, ["init", "--directory", "my_workspace"])
        assert res_init.exit_code == 0
        assert "Initialized Basalt workspace" in res_init.output


def test_cli_verbose_and_quiet_flags(cli_runner: CliRunner) -> None:
    """Verify global --verbose and --quiet flags handling."""
    res_v = cli_runner.invoke(cli, ["--verbose", "version"])
    assert res_v.exit_code == 0

    res_q = cli_runner.invoke(cli, ["--quiet", "version"])
    assert res_q.exit_code == 0


# --- Workflow DAG Commands Tests ---


def test_cli_dag_validate_command(cli_runner: CliRunner, tmp_path) -> None:
    """Verify strata dag validate command with valid and invalid YAML files."""
    valid_yaml = tmp_path / "valid_dag.yaml"
    valid_yaml.write_text("""
id: cli_dag_valid
name: Valid CLI DAG
steps:
  - id: s1
    executor_type: subprocess
    command: "echo ok"
""")

    # 1. Validate valid YAML with default table format
    res_val = cli_runner.invoke(cli, ["dag", "validate", str(valid_yaml)])
    assert res_val.exit_code == 0
    assert "VALID" in res_val.output

    # 2. Validate valid YAML with JSON format
    res_json = cli_runner.invoke(cli, ["dag", "validate", str(valid_yaml), "--format", "json"])
    assert res_json.exit_code == 0
    json_data = json.loads(res_json.output)
    assert json_data["valid"] is True
    assert json_data["dag_id"] == "cli_dag_valid"

    # 3. Validate invalid syntax
    invalid_yaml = tmp_path / "invalid_dag.yaml"
    invalid_yaml.write_text("invalid: [yaml: content: syntax error")
    res_err = cli_runner.invoke(cli, ["dag", "validate", str(invalid_yaml)])
    assert res_err.exit_code != 0


def test_cli_dag_lifecycle_commands(cli_runner: CliRunner, tmp_path) -> None:
    """Verify strata dag register, list, inspect, export, and delete commands."""
    db_file = tmp_path / "cli_dags.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    dag_file = tmp_path / "sample_dag.yaml"
    dag_file.write_text("""
id: cli_lifecycle_dag
name: Lifecycle DAG
tags: ["cli", "test"]
steps:
  - id: step1
    executor_type: subprocess
    command: "echo 'hello lifecycle'"
""")

    # 1. Register DAG
    res_reg = cli_runner.invoke(cli, ["dag", "register", str(dag_file), "--db-url", db_url])
    assert res_reg.exit_code == 0
    assert "Successfully registered DAG 'cli_lifecycle_dag'" in res_reg.output

    # 2. List DAGs
    res_list = cli_runner.invoke(cli, ["dag", "list", "--db-url", db_url])
    assert res_list.exit_code == 0
    assert "cli_lifecycle_dag" in res_list.output

    # 3. Inspect DAG
    res_insp = cli_runner.invoke(cli, ["dag", "inspect", "cli_lifecycle_dag", "--db-url", db_url])
    assert res_insp.exit_code == 0
    assert "Lifecycle DAG" in res_insp.output

    # 4. Export DAG to JSON
    export_file = tmp_path / "exported_dag.json"
    res_exp = cli_runner.invoke(
        cli, ["dag", "export", "cli_lifecycle_dag", "-o", str(export_file), "--db-url", db_url]
    )
    assert res_exp.exit_code == 0
    assert export_file.exists()

    # 5. Delete DAG
    res_del = cli_runner.invoke(cli, ["dag", "delete", "cli_lifecycle_dag", "--db-url", db_url])
    assert res_del.exit_code == 0
    assert "Successfully deleted DAG" in res_del.output


# --- Workflow Run Commands Tests ---


def test_cli_run_commands(cli_runner: CliRunner, tmp_path) -> None:
    """Verify strata run start, status, step, list, and cancel commands."""
    db_file = tmp_path / "cli_runs.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    dag_file = tmp_path / "run_target.yaml"
    dag_file.write_text("""
id: cli_run_target
name: Run Target DAG
steps:
  - id: s_calc
    executor_type: subprocess
    command: >-
      echo '{"val": 100}'
""")

    # 1. Run start from file
    res_start = cli_runner.invoke(
        cli,
        ["run", "start", str(dag_file), "--inputs", '{"x": 10}', "--db-url", db_url],
    )
    assert res_start.exit_code == 0
    assert "COMPLETED successfully" in res_start.output

    # 2. Run list
    res_list = cli_runner.invoke(
        cli, ["run", "list", "--dag-id", "cli_run_target", "--db-url", db_url]
    )
    assert res_list.exit_code == 0
    assert "cli_run_target" in res_list.output

    # 3. Cancel non-active run error handling
    res_cancel = cli_runner.invoke(cli, ["run", "cancel", "fake_run_id", "--db-url", db_url])
    assert res_cancel.exit_code != 0
    assert "not active" in res_cancel.output


def test_cli_run_status_and_step_details(cli_runner: CliRunner, tmp_path) -> None:
    """Verify strata run status and strata run step output inspection."""
    db_file = tmp_path / "cli_run_status.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    dag_file = tmp_path / "step_dag.yaml"
    dag_file.write_text("""
id: cli_step_dag
steps:
  - id: step_out
    executor_type: subprocess
    command: >-
      echo '{"res": 42}'
""")

    # Run start
    res_start = cli_runner.invoke(
        cli,
        [
            "run",
            "start",
            str(dag_file),
            "--run-id",
            "test_run_123",
            "--db-url",
            db_url,
            "--format",
            "json",
        ],
    )
    assert res_start.exit_code == 0

    # 1. Check run status by run ID
    res_status = cli_runner.invoke(
        cli, ["run", "status", "test_run_123", "--db-url", db_url, "--format", "json"]
    )
    assert res_status.exit_code == 0
    data_status = json.loads(res_status.output)
    assert data_status["run_id"] == "test_run_123"
    assert data_status["state"].upper() == "COMPLETED"

    # 2. Check step output details
    res_step = cli_runner.invoke(
        cli, ["run", "step", "test_run_123", "step_out", "--db-url", db_url]
    )
    assert res_step.exit_code == 0
    data_step = json.loads(res_step.output)
    assert data_step["step_id"] == "step_out"
    assert data_step["output"]["res"] == 42


def test_cli_run_retry_and_error_handling(cli_runner: CliRunner, tmp_path) -> None:
    """Verify strata run retry error handling for completed or missing run IDs."""
    db_file = tmp_path / "cli_run_retry.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    dag_file = tmp_path / "retry_dag.yaml"
    dag_file.write_text("""
id: cli_retry_dag
steps:
  - id: s1
    executor_type: subprocess
    command: "echo ok"
""")

    cli_runner.invoke(
        cli, ["run", "start", str(dag_file), "--run-id", "completed_run_1", "--db-url", db_url]
    )

    # 1. Retry completed run (expect error)
    res_retry_completed = cli_runner.invoke(
        cli, ["run", "retry", "completed_run_1", "--db-url", db_url]
    )
    assert res_retry_completed.exit_code != 0
    assert "cannot be retried" in res_retry_completed.output

    # 2. Retry non-existent run ID (expect error)
    res_retry_missing = cli_runner.invoke(
        cli, ["run", "retry", "missing_run_999", "--db-url", db_url]
    )
    assert res_retry_missing.exit_code != 0
    assert "not found" in res_retry_missing.output


# --- Server Administration Commands Tests ---


def test_cli_server_status_command(cli_runner: CliRunner) -> None:
    """Verify strata server status command when server is offline."""
    res_status = cli_runner.invoke(cli, ["server", "status", "--url", "http://127.0.0.1:59999"])
    assert res_status.exit_code == 0
    assert "OFFLINE" in res_status.output or "unreachable" in res_status.output


def test_cli_server_info_and_metrics_with_mock(cli_runner: CliRunner) -> None:
    """Verify strata server info and strata server metrics commands with HTTP mocks."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"version": "1.0.0", "active_workers": 2.0}

    with patch("httpx.get", return_value=mock_resp):
        res_info = cli_runner.invoke(cli, ["server", "info", "--url", "http://127.0.0.1:8000"])
        assert res_info.exit_code == 0
        assert "1.0.0" in res_info.output

        res_metrics = cli_runner.invoke(
            cli, ["server", "metrics", "--url", "http://127.0.0.1:8000"]
        )
        assert res_metrics.exit_code == 0
        assert "active_workers" in res_metrics.output


def test_cli_server_start_command_dry_run(cli_runner: CliRunner) -> None:
    """Verify strata server start command launching uvicorn with mocked runner."""
    with patch("uvicorn.run") as mock_uvicorn:
        res_start = cli_runner.invoke(
            cli, ["server", "start", "--port", "9000", "--host", "0.0.0.0"]
        )
        assert res_start.exit_code == 0
        mock_uvicorn.assert_called_once_with(
            "basalt.api.app:app",
            host="0.0.0.0",
            port=9000,
            reload=False,
            workers=1,
            log_level="info",
        )
