"""DAG Specification File and String Parser Module for Basalt Workflow Engine.

Provides loaders for JSON, YAML, and Python dictionary workflow definitions,
converting raw input into validated DAGSpec AST objects with explicit error handling,
async file parsing, directory scanning, and serialization helpers.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from basalt.core.dag.ast import DAGSpec
from basalt.core.dag.exceptions import DAGParseError, DAGValidationError
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class DAGParser:
    """Parser and deserializer for Basalt workflow DAG definitions."""

    @classmethod
    def parse_file(cls, filepath: str | Path) -> DAGSpec:
        """Load and parse a workflow definition file from disk (JSON or YAML).

        Args:
            filepath: Path to the workflow definition file (.json, .yaml, .yml).

        Returns:
            Validated DAGSpec AST object.

        Raises:
            DAGParseError: If file reading or JSON/YAML syntax parsing fails.
            DAGValidationError: If schema structure validation fails.
        """
        path = Path(filepath).resolve()
        if not path.exists():
            raise DAGParseError(
                message=f"Workflow definition file not found: '{filepath}'",
                filepath=str(filepath),
            )
        if not path.is_file():
            raise DAGParseError(
                message=f"Path is not a regular file: '{filepath}'",
                filepath=str(filepath),
            )

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            raise DAGParseError(
                message=f"Failed to read workflow file '{filepath}': {exc}",
                filepath=str(filepath),
            ) from exc

        # Infer format from extension if possible
        ext = path.suffix.lower()
        format_type = "json" if ext == ".json" else "yaml"

        return cls.parse_string(content=content, format_type=format_type, filepath=str(filepath))

    @classmethod
    async def parse_file_async(cls, filepath: str | Path) -> DAGSpec:
        """Asynchronously load and parse a workflow definition file from disk.

        Args:
            filepath: Path to the workflow definition file (.json, .yaml, .yml).

        Returns:
            Validated DAGSpec AST object.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, cls.parse_file, filepath)

    @classmethod
    def parse_string(
        cls,
        content: str,
        format_type: str = "yaml",
        filepath: str = "<string>",
    ) -> DAGSpec:
        """Parse raw JSON or YAML string content into a DAGSpec object.

        Args:
            content: Raw text content containing workflow definition.
            format_type: Expected format ('yaml', 'yml', or 'json').
            filepath: Optional origin filename for error reporting context.

        Returns:
            Validated DAGSpec AST object.

        Raises:
            DAGParseError: If JSON or YAML syntax parsing fails.
            DAGValidationError: If Pydantic schema validation fails.
        """
        if not content or not content.strip():
            raise DAGParseError(
                message="Workflow definition content is empty.",
                filepath=filepath,
            )

        raw_data: dict[str, Any]

        if format_type.lower() in ("json", ".json"):
            try:
                raw_data = json.loads(content)
            except json.JSONDecodeError as exc:
                raise DAGParseError(
                    message=f"Invalid JSON syntax: {exc.msg}",
                    filepath=filepath,
                    line_number=exc.lineno,
                ) from exc
        else:
            try:
                raw_data = yaml.safe_load(content)
            except yaml.YAMLError as exc:
                line_no = None
                if hasattr(exc, "problem_mark") and exc.problem_mark:
                    line_no = exc.problem_mark.line + 1
                raise DAGParseError(
                    message=f"Invalid YAML syntax: {exc}",
                    filepath=filepath,
                    line_number=line_no,
                ) from exc

        if not isinstance(raw_data, dict):
            raise DAGParseError(
                message=f"Root workflow structure must be a dictionary, got {type(raw_data).__name__}.",
                filepath=filepath,
            )

        return cls.parse_dict(raw_data=raw_data, filepath=filepath)

    @classmethod
    def parse_dict(
        cls,
        raw_data: dict[str, Any],
        filepath: str = "<dict>",
    ) -> DAGSpec:
        """Instantiate and validate a DAGSpec from a raw Python dictionary.

        Args:
            raw_data: Unstructured dictionary representing a workflow definition.
            filepath: Origin file context for error reports.

        Returns:
            Validated DAGSpec AST object.

        Raises:
            DAGValidationError: If validation against Pydantic schema fails.
        """
        try:
            dag = DAGSpec.model_validate(raw_data)
            logger.debug(
                "Successfully parsed DAG definition",
                extra={"dag_id": dag.id, "step_count": len(dag.steps)},
            )
            return dag
        except ValidationError as exc:
            errors_list = []
            for err in exc.errors():
                loc_str = " -> ".join(str(loc) for loc in err["loc"])
                errors_list.append(
                    {
                        "field": loc_str,
                        "message": err["msg"],
                        "type": err["type"],
                    }
                )

            dag_id = raw_data.get("id") if isinstance(raw_data, dict) else None
            first_msg = errors_list[0]["message"] if errors_list else str(exc)
            field_name = errors_list[0]["field"] if errors_list else "root"

            raise DAGValidationError(
                message=f"Workflow schema validation failed at '{field_name}': {first_msg}",
                validation_errors=errors_list,
                dag_id=str(dag_id) if dag_id else None,
            ) from exc

    @classmethod
    def parse_directory(
        cls,
        directory_path: str | Path,
        extensions: list[str] | None = None,
    ) -> dict[str, DAGSpec]:
        """Scan a directory for workflow definition files and parse all valid DAGs.

        Args:
            directory_path: Directory containing workflow definition files.
            extensions: List of file extensions to include (default: [.yaml, .yml, .json]).

        Returns:
            Dictionary mapping DAG IDs to parsed DAGSpec objects.
        """
        target_dir = Path(directory_path).resolve()
        if not target_dir.exists() or not target_dir.is_dir():
            raise DAGParseError(
                message=f"Target directory does not exist or is not a directory: '{directory_path}'",
                filepath=str(directory_path),
            )

        valid_exts = set(ext.lower() for ext in (extensions or [".yaml", ".yml", ".json"]))
        parsed_dags: dict[str, DAGSpec] = {}

        for file_path in target_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in valid_exts:
                try:
                    dag = cls.parse_file(file_path)
                    parsed_dags[dag.id] = dag
                except (DAGParseError, DAGValidationError) as exc:
                    logger.warning(
                        f"Skipping invalid workflow file '{file_path.name}': {exc.message}"
                    )

        return parsed_dags


def dump_dag_to_yaml(dag: DAGSpec) -> str:
    """Serialize a DAGSpec object to a formatted YAML string.

    Args:
        dag: Validated DAGSpec object.

    Returns:
        Formatted YAML string.
    """
    dag_dict = dag.model_dump(exclude_none=True, mode="json")
    return yaml.safe_dump(dag_dict, sort_keys=False, indent=2)


def dump_dag_to_json(dag: DAGSpec, indent: int = 2) -> str:
    """Serialize a DAGSpec object to a formatted JSON string.

    Args:
        dag: Validated DAGSpec object.
        indent: JSON indentation spaces.

    Returns:
        Formatted JSON string.
    """
    dag_dict = dag.model_dump(exclude_none=True, mode="json")
    return json.dumps(dag_dict, indent=indent, default=str)
