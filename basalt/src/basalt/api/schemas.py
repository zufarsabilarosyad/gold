"""Pydantic REST API Schemas Subsystem Module for Basalt Engine.

Provides request and response payload data models for FastAPI REST API endpoints,
including DAG registration, run execution, trigger management, DLQ inspection, and error reporting.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from basalt.core.dag.ast import TriggerType
from basalt.core.engine.state_machine import StepState, WorkflowState

# --- Standard System & Health Response Models ---


class HealthResponse(BaseModel):
    """System health check status response model."""

    status: str = Field(default="healthy", description="Engine health status.")
    version: str = Field(default="1.0.0", description="Basalt engine version string.")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Current server UTC timestamp.",
    )
    storage_backend: str = Field(..., description="Active storage engine backend name.")
    active_runs: int = Field(default=0, description="Count of currently active workflow runs.")


class SystemInfoResponse(BaseModel):
    """Detailed engine telemetry and system info model."""

    engine_name: str = Field(default="Basalt", description="Engine framework name.")
    version: str = Field(default="1.0.0")
    python_version: str = Field(...)
    loaded_dags_count: int = Field(default=0)
    worker_concurrency: int = Field(default=10)
    uptime_seconds: float = Field(default=0.0)


# --- Workflow DAG Request & Response Models ---


class DAGRegisterRequest(BaseModel):
    """Request payload for registering or updating a workflow DAG specification."""

    spec: str = Field(
        ...,
        description="Raw YAML or JSON workflow specification string, or dict AST object.",
    )
    overwrite: bool = Field(
        default=True,
        description="Whether to overwrite existing registered workflow DAG with same ID.",
    )


class DAGResponse(BaseModel):
    """API response representation of a registered workflow DAGSpec."""

    id: str = Field(..., description="Unique DAG identifier.")
    name: str = Field(..., description="Human-readable DAG title.")
    description: str | None = Field(None, description="Workflow description.")
    version: str = Field(default="1.0.0", description="Semantic version string.")
    owner: str | None = Field(None, description="Workflow owner.")
    tags: list[str] = Field(default_factory=list, description="Categorization tags.")
    step_count: int = Field(..., description="Total step count in workflow DAG.")
    trigger_count: int = Field(default=0, description="Associated event trigger count.")
    created_at: datetime | None = Field(None, description="Creation timestamp.")
    updated_at: datetime | None = Field(None, description="Last update timestamp.")


class DAGListResponse(BaseModel):
    """Paginated list response container for workflow DAG definitions."""

    total: int = Field(..., description="Total matching DAG count.")
    dags: list[DAGResponse] = Field(..., description="List of DAG response objects.")
    page: int = Field(default=1, description="Page index (1-based).")
    size: int = Field(default=50, description="Items per page limit.")


# --- Workflow Run Request & Response Models ---


class RunTriggerRequest(BaseModel):
    """Request payload to initiate execution of a workflow DAG."""

    inputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Execution input parameters passed to workflow steps.",
    )
    run_id: str | None = Field(
        None,
        description="Optional custom run identifier (auto-generated if omitted).",
    )


class BatchRunTriggerRequest(BaseModel):
    """Request payload to trigger batch execution of multiple DAG workflows."""

    requests: list[RunTriggerRequest] = Field(..., description="List of run trigger requests.")


class StepRunResponse(BaseModel):
    """Execution status snapshot of an individual workflow step."""

    step_id: str = Field(..., description="Target step identifier.")
    state: StepState = Field(..., description="Step execution state.")
    attempt: int = Field(default=1, description="Execution attempt index.")
    start_time: datetime | None = Field(None, description="Step start timestamp.")
    end_time: datetime | None = Field(None, description="Step completion timestamp.")
    duration_ms: float | None = Field(None, description="Execution duration in milliseconds.")
    output: Any | None = Field(None, description="Returned output payload.")
    error_message: str | None = Field(None, description="Error trace message if step failed.")


class RunStatusResponse(BaseModel):
    """Complete execution run log result model."""

    run_id: str = Field(..., description="Execution run identifier.")
    dag_id: str = Field(..., description="Target workflow DAG identifier.")
    state: WorkflowState = Field(..., description="Workflow execution state.")
    start_time: datetime = Field(..., description="Execution start timestamp.")
    end_time: datetime | None = Field(None, description="Completion timestamp.")
    duration_ms: float = Field(default=0.0, description="Total execution duration in ms.")
    inputs: dict[str, Any] = Field(default_factory=dict, description="Input parameters dict.")
    outputs: dict[str, Any] = Field(default_factory=dict, description="Step outputs dict.")
    step_runs: list[StepRunResponse] = Field(
        default_factory=list,
        description="Detailed step execution records.",
    )
    error_message: str | None = Field(None, description="Failure reason message.")


class BatchRunStatusResponse(BaseModel):
    """Batch execution status response container."""

    total_submitted: int = Field(..., description="Count of submitted runs.")
    runs: list[RunStatusResponse] = Field(..., description="List of run result responses.")


class RunListResponse(BaseModel):
    """Paginated list response container for workflow execution runs."""

    total: int = Field(..., description="Total matching run count.")
    runs: list[RunStatusResponse] = Field(..., description="List of run result status objects.")
    page: int = Field(default=1, description="Page index (1-based).")
    size: int = Field(default=50, description="Items per page limit.")


# --- Event Trigger Request & Response Models ---


class TriggerResponse(BaseModel):
    """API response model for event trigger status."""

    id: str = Field(..., description="Trigger identifier.")
    dag_id: str = Field(..., description="Target workflow DAG identifier.")
    type: TriggerType = Field(..., description="Trigger classification type.")
    status: str = Field(default="active", description="Trigger status (active, paused, stopped).")
    enabled: bool = Field(default=True, description="Whether trigger evaluation is enabled.")
    next_fire_time: datetime | None = Field(None, description="Next anticipated fire timestamp.")
    last_fired_at: datetime | None = Field(None, description="Last fire timestamp.")


class TriggerListResponse(BaseModel):
    """List response container for registered event triggers."""

    total: int = Field(..., description="Total count of registered triggers.")
    triggers: list[TriggerResponse] = Field(..., description="List of trigger status objects.")


# --- Dead-Letter Queue (DLQ) Response Models ---


class DLQItemResponse(BaseModel):
    """Dead-Letter Queue (DLQ) payload response model."""

    payload_id: str = Field(..., description="Unique DLQ entry payload ID.")
    dag_id: str | None = Field(None, description="Associated DAG ID.")
    step_id: str | None = Field(None, description="Associated step ID.")
    error_code: str = Field(..., description="Categorical error code string.")
    error_message: str = Field(..., description="Detailed failure reason message.")
    payload: dict[str, Any] = Field(..., description="Unrecoverable payload content.")
    processed: bool = Field(default=False, description="Whether DLQ payload was processed.")
    created_at: datetime = Field(..., description="DLQ entry creation timestamp.")


class DLQListResponse(BaseModel):
    """List response container for Dead-Letter Queue entries."""

    total: int = Field(..., description="Total DLQ entry count.")
    items: list[DLQItemResponse] = Field(..., description="List of DLQ payload responses.")


# --- Standard Error Response Models ---


class ErrorDetail(BaseModel):
    """Detailed exception info model for standard API error responses."""

    message: str = Field(..., description="Human-readable error explanation.")
    code: str = Field(..., description="Categorical error code identifier.")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Error timestamp in UTC.",
    )
    details: dict[str, Any] | None = Field(
        None,
        description="Additional contextual key-value debugging metadata.",
    )


class ErrorResponse(BaseModel):
    """Standardized top-level API error response envelope."""

    error: ErrorDetail = Field(..., description="Error detail container object.")


def create_error_response(
    message: str,
    code: str = "INTERNAL_SERVER_ERROR",
    details: dict[str, Any] | None = None,
) -> ErrorResponse:
    """Helper shortcut to instantiate standardized ErrorResponse objects."""
    return ErrorResponse(
        error=ErrorDetail(
            message=message,
            code=code,
            details=details,
        )
    )
