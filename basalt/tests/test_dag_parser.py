"""Unit Tests for DAG Parser Module in Basalt Workflow Engine.

Validates JSON/YAML file parsing, string parsing, schema instantiation,
error line reporting, serialization, directory scanning, and trigger validation.
"""

import json
from pathlib import Path

import pytest

from basalt.core.dag.ast import DAGSpec, ExecutorType, TriggerType
from basalt.core.dag.exceptions import DAGParseError, DAGValidationError
from basalt.core.dag.parser import DAGParser, dump_dag_to_json, dump_dag_to_yaml


@pytest.fixture
def valid_yaml_content() -> str:
    """Fixture returning a valid YAML workflow definition."""
    return """
id: etl_pipeline
name: ETL Data Processing Pipeline
version: 1.0.0
owner: data-eng@company.com
timeout_seconds: 1800
steps:
  - id: extract_data
    name: Extract raw dataset
    executor_type: subprocess
    command: echo "extracting"
    timeout_seconds: 120
  - id: transform_data
    name: Transform records
    executor_type: subprocess
    command: echo "transforming"
    depends_on:
      - extract_data
  - id: load_data
    name: Load into warehouse
    executor_type: subprocess
    command: echo "loading"
    depends_on:
      - transform_data
triggers:
  - id: daily_cron
    type: cron
    cron: "0 0 * * *"
"""


@pytest.fixture
def valid_json_content() -> str:
    """Fixture returning a valid JSON workflow definition."""
    return json.dumps(
        {
            "id": "http_ping_dag",
            "name": "HTTP Endpoint Monitor",
            "steps": [
                {
                    "id": "ping_api",
                    "executor_type": "http",
                    "url": "https://api.example.com/health",
                    "method": "GET",
                }
            ],
            "triggers": [
                {
                    "id": "interval_check",
                    "type": "interval",
                    "interval_seconds": 60.0,
                }
            ],
        }
    )


def test_parse_valid_yaml_string(valid_yaml_content: str) -> None:
    """Verify parsing a valid YAML string into a DAGSpec object."""
    dag = DAGParser.parse_string(valid_yaml_content, format_type="yaml")

    assert isinstance(dag, DAGSpec)
    assert dag.id == "etl_pipeline"
    assert dag.name == "ETL Data Processing Pipeline"
    assert len(dag.steps) == 3
    assert dag.steps[0].id == "extract_data"
    assert dag.steps[1].depends_on == ["extract_data"]
    assert len(dag.triggers) == 1
    assert dag.triggers[0].type == TriggerType.CRON


def test_parse_valid_json_string(valid_json_content: str) -> None:
    """Verify parsing a valid JSON string into a DAGSpec object."""
    dag = DAGParser.parse_string(valid_json_content, format_type="json")

    assert dag.id == "http_ping_dag"
    assert len(dag.steps) == 1
    assert dag.steps[0].executor_type == ExecutorType.HTTP
    assert dag.steps[0].url == "https://api.example.com/health"
    assert len(dag.triggers) == 1
    assert dag.triggers[0].interval_seconds == 60.0


def test_parse_file_from_tmp_path(tmp_path: Path, valid_yaml_content: str) -> None:
    """Verify parsing a workflow file from disk."""
    file_path = tmp_path / "test_pipeline.yaml"
    file_path.write_text(valid_yaml_content, encoding="utf-8")

    dag = DAGParser.parse_file(file_path)

    assert dag.id == "etl_pipeline"
    assert len(dag.steps) == 3


@pytest.mark.asyncio
async def test_parse_file_async(tmp_path: Path, valid_yaml_content: str) -> None:
    """Verify asynchronous file parsing."""
    file_path = tmp_path / "async_pipeline.yaml"
    file_path.write_text(valid_yaml_content, encoding="utf-8")

    dag = await DAGParser.parse_file_async(file_path)

    assert dag.id == "etl_pipeline"


def test_parse_empty_content_raises_error() -> None:
    """Verify parsing empty string raises DAGParseError."""
    with pytest.raises(DAGParseError) as exc_info:
        DAGParser.parse_string("", format_type="yaml")
    assert "empty" in str(exc_info.value.message).lower()


def test_parse_invalid_yaml_syntax() -> None:
    """Verify invalid YAML syntax raises DAGParseError."""
    invalid_yaml = "id: test\nsteps:\n  - id: step1\n    command: [unclosed list"
    with pytest.raises(DAGParseError) as exc_info:
        DAGParser.parse_string(invalid_yaml, format_type="yaml")
    assert exc_info.value.code == "DAG_PARSE_ERROR"


def test_parse_invalid_json_syntax() -> None:
    """Verify invalid JSON syntax raises DAGParseError."""
    invalid_json = "{'invalid': 'single quotes'}"
    with pytest.raises(DAGParseError) as exc_info:
        DAGParser.parse_string(invalid_json, format_type="json")
    assert exc_info.value.code == "DAG_PARSE_ERROR"


def test_parse_non_existent_file() -> None:
    """Verify loading non-existent file path raises DAGParseError."""
    with pytest.raises(DAGParseError) as exc_info:
        DAGParser.parse_file("/tmp/non_existent_strata_workflow_12345.yaml")
    assert "not found" in str(exc_info.value.message).lower()


def test_validation_error_on_missing_required_fields() -> None:
    """Verify schema validation error when required fields are missing."""
    incomplete_dict = {"name": "No ID Workflow", "steps": []}
    with pytest.raises(DAGValidationError) as exc_info:
        DAGParser.parse_dict(incomplete_dict)
    assert exc_info.value.code == "DAG_VALIDATION_ERROR"


def test_validation_error_invalid_executor_params() -> None:
    """Verify validation error when step missing command for subprocess executor."""
    invalid_step_dict = {
        "id": "bad_dag",
        "name": "Bad Subprocess DAG",
        "steps": [
            {
                "id": "step1",
                "executor_type": "subprocess",
                # missing 'command'
            }
        ],
    }
    with pytest.raises(DAGValidationError) as exc_info:
        DAGParser.parse_dict(invalid_step_dict)
    assert "command" in str(exc_info.value.message).lower()


def test_validation_error_invalid_cron_trigger() -> None:
    """Verify validation error on malformed cron expression."""
    invalid_cron_dict = {
        "id": "bad_cron_dag",
        "name": "Bad Cron DAG",
        "steps": [{"id": "step1", "command": "echo 1"}],
        "triggers": [{"id": "trg1", "type": "cron", "cron": "invalid cron syntax"}],
    }
    with pytest.raises(DAGValidationError) as exc_info:
        DAGParser.parse_dict(invalid_cron_dict)
    assert "cron" in str(exc_info.value.message).lower()


def test_dump_dag_to_yaml_and_json(valid_yaml_content: str) -> None:
    """Verify serializing DAGSpec AST back to YAML and JSON strings."""
    dag = DAGParser.parse_string(valid_yaml_content, format_type="yaml")

    yaml_dump = dump_dag_to_yaml(dag)
    assert "id: etl_pipeline" in yaml_dump
    assert "extract_data" in yaml_dump

    json_dump = dump_dag_to_json(dag)
    json_obj = json.loads(json_dump)
    assert json_obj["id"] == "etl_pipeline"
    assert len(json_obj["steps"]) == 3


def test_parse_directory(tmp_path: Path, valid_yaml_content: str, valid_json_content: str) -> None:
    """Verify scanning directory for valid workflow files."""
    (tmp_path / "dag1.yaml").write_text(valid_yaml_content, encoding="utf-8")
    (tmp_path / "dag2.json").write_text(valid_json_content, encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("not a dag", encoding="utf-8")

    parsed_map = DAGParser.parse_directory(tmp_path)

    assert len(parsed_map) == 2
    assert "etl_pipeline" in parsed_map
    assert "http_ping_dag" in parsed_map


def test_parse_directory_invalid_path() -> None:
    """Verify scanning invalid directory path raises DAGParseError."""
    with pytest.raises(DAGParseError) as exc_info:
        DAGParser.parse_directory("/tmp/non_existent_dir_99999")
    assert "not exist" in str(exc_info.value.message).lower()
