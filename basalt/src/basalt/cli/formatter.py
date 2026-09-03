"""CLI Output Formatter Subsystem Module for Basalt Engine.

Provides ASCII table formatting, JSON serialization, and status color highlights
for rendering workflow DAG definitions, execution run ledgers, and trigger telemetry in Click CLI commands.
"""

import json
from enum import Enum
from typing import Any

from basalt.core.dag.ast import DAGSpec
from basalt.core.engine.runner import WorkflowRunResult


class OutputFormat(str, Enum):
    """Supported output rendering formats for CLI commands."""

    TABLE = "table"
    JSON = "json"
    PLAIN = "plain"


class CLIFormatter:
    """Formatter class converting Basalt objects into terminal ASCII tables or JSON."""

    @staticmethod
    def format_table(headers: list[str], rows: list[list[Any]], title: str | None = None) -> str:
        """Render a formatted ASCII table string with column auto-width alignment.

        Args:
            headers: List of header column titles.
            rows: List of data rows matching header column count.
            title: Optional table banner title.

        Returns:
            ASCII table formatted multiline string.
        """
        if not headers:
            return ""

        # Stringify row values
        string_rows = [[str(val) for val in row] for row in rows]

        # Calculate max width for each column
        col_widths = [len(h) for h in headers]
        for row in string_rows:
            for i, val in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(val))

        # Format border divider
        divider = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
        header_row = "| " + " | ".join(f"{h:<{w}}" for h, w in zip(headers, col_widths)) + " |"

        lines = []
        if title:
            lines.append(f"=== {title} ===")

        lines.append(divider)
        lines.append(header_row)
        lines.append(divider)

        for row in string_rows:
            # Fill missing cells if row length mismatch
            padded_row = row + [""] * (len(headers) - len(row))
            row_str = (
                "| " + " | ".join(f"{val:<{w}}" for val, w in zip(padded_row, col_widths)) + " |"
            )
            lines.append(row_str)

        lines.append(divider)
        return "\n".join(lines)

    @staticmethod
    def format_json(data: Any, indent: int = 2) -> str:
        """Serialize dictionary, Pydantic model, or AST object to formatted JSON string."""

        def default_serializer(obj: Any) -> Any:
            if hasattr(obj, "model_dump"):
                return obj.model_dump(mode="json")
            if hasattr(obj, "dict"):
                return obj.dict()
            if hasattr(obj, "value"):  # Enums
                return obj.value
            if hasattr(obj, "isoformat"):  # Datetime
                return obj.isoformat()
            return str(obj)

        return json.dumps(data, default=default_serializer, indent=indent)

    @classmethod
    def format_dag_summary(
        cls, dag: DAGSpec, output_format: OutputFormat = OutputFormat.TABLE
    ) -> str:
        """Format detailed summary of a single DAGSpec."""
        if output_format == OutputFormat.JSON:
            return cls.format_json(dag)

        headers = ["Property", "Value"]
        rows = [
            ["ID", dag.id],
            ["Name", dag.name],
            ["Version", dag.version],
            ["Description", dag.description or "N/A"],
            ["Owner", dag.owner or "N/A"],
            ["Tags", ", ".join(dag.tags) if dag.tags else "None"],
            ["Step Count", len(dag.steps)],
            ["Trigger Count", len(dag.triggers)],
        ]

        summary_table = cls.format_table(headers, rows, title=f"Workflow DAG: {dag.id}")

        # Render steps sub-table
        step_headers = ["Step ID", "Executor Type", "Dependencies", "Timeout (s)"]
        step_rows = [
            [
                s.id,
                s.executor_type.value,
                ", ".join(s.depends_on) if s.depends_on else "None",
                s.timeout_seconds,
            ]
            for s in dag.steps
        ]
        steps_table = cls.format_table(step_headers, step_rows, title="Workflow Steps")

        return f"{summary_table}\n\n{steps_table}"

    @classmethod
    def format_dag_list(
        cls, dags: list[DAGSpec], output_format: OutputFormat = OutputFormat.TABLE
    ) -> str:
        """Format list of registered workflow DAGs."""
        if output_format == OutputFormat.JSON:
            return cls.format_json(dags)

        if not dags:
            return "No workflow DAGs registered."

        headers = ["DAG ID", "Name", "Version", "Tags", "Steps", "Triggers"]
        rows = [
            [
                dag.id,
                dag.name,
                dag.version,
                ", ".join(dag.tags) if dag.tags else "-",
                len(dag.steps),
                len(dag.triggers),
            ]
            for dag in dags
        ]
        return cls.format_table(headers, rows, title="Registered Workflow DAGs")

    @classmethod
    def format_run_result(
        cls, result: WorkflowRunResult, output_format: OutputFormat = OutputFormat.TABLE
    ) -> str:
        """Format complete execution run result summary and step state ledger."""
        if output_format == OutputFormat.JSON:
            return cls.format_json(result)

        headers = ["Property", "Value"]
        rows = [
            ["Run ID", result.run_id],
            ["DAG ID", result.dag_id],
            ["State", result.state.value.upper()],
            ["Duration (ms)", f"{result.duration_ms:.2f}"],
            ["Start Time", result.start_time.strftime("%Y-%m-%d %H:%M:%S UTC")],
            [
                "End Time",
                result.end_time.strftime("%Y-%m-%d %H:%M:%S UTC") if result.end_time else "N/A",
            ],
            ["Error Message", result.error_message or "None"],
        ]

        summary_table = cls.format_table(headers, rows, title=f"Run Result: {result.run_id}")

        # Render step states table
        step_headers = ["Step ID", "Execution State", "Attempts", "Output Summary"]
        step_rows = []
        for step_id, state in result.step_states.items():
            output_val = result.outputs.get(step_id)
            output_str = json.dumps(output_val) if output_val else "-"
            if len(output_str) > 40:
                output_str = output_str[:37] + "..."
            attempts = result.step_attempts.get(step_id, 1)
            step_rows.append([step_id, state.value.upper(), str(attempts), output_str])


        steps_table = cls.format_table(step_headers, step_rows, title="Step Execution States")
        return f"{summary_table}\n\n{steps_table}"

    @classmethod
    def format_run_list(
        cls, runs: list[WorkflowRunResult], output_format: OutputFormat = OutputFormat.TABLE
    ) -> str:
        """Format list of workflow execution run records."""
        if output_format == OutputFormat.JSON:
            return cls.format_json(runs)

        if not runs:
            return "No workflow execution runs found."

        headers = ["Run ID", "DAG ID", "State", "Duration (ms)", "Start Time"]
        rows = [
            [
                r.run_id,
                r.dag_id,
                r.state.value.upper(),
                f"{r.duration_ms:.2f}",
                r.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            ]
            for r in runs
        ]
        return cls.format_table(headers, rows, title="Workflow Run Logs")
