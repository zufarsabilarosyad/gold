"""FastAPI REST API Router Subsystem for Workflow Execution Runs.

Provides API endpoints for triggering individual or batch workflow runs,
querying execution status and output ledgers, inspecting specific step execution logs,
cancelling active workflow runs, retrying failed workflow runs, and querying active & historical run records.
"""

from typing import Any

from fastapi import APIRouter, Depends, Query, status

from basalt.api.schemas import (
    BatchRunStatusResponse,
    BatchRunTriggerRequest,
    ErrorResponse,
    RunListResponse,
    RunStatusResponse,
    RunTriggerRequest,
    StepRunResponse,
)
from basalt.core.dag.exceptions import BasaltError
from basalt.core.engine.engine import BasaltEngine, get_engine
from basalt.core.engine.runner import WorkflowRunResult
from basalt.core.engine.state_machine import WorkflowState
from basalt.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Execution Runs"])


def get_engine_dep() -> BasaltEngine:
    """Dependency injector for BasaltEngine facade instance."""
    return get_engine()


def _to_run_status_response(result: WorkflowRunResult) -> RunStatusResponse:
    """Convert WorkflowRunResult engine snapshot into API RunStatusResponse model."""
    step_runs = [
        StepRunResponse(
            step_id=step_id,
            state=state,
            attempt=result.step_attempts.get(step_id, 1),
            output=result.outputs.get(step_id),
        )
        for step_id, state in result.step_states.items()
    ]


    return RunStatusResponse(
        run_id=result.run_id,
        dag_id=result.dag_id,
        state=result.state,
        start_time=result.start_time,
        end_time=result.end_time,
        duration_ms=result.duration_ms,
        inputs=result.inputs or {},
        outputs=result.outputs or {},
        step_runs=step_runs,
        error_message=result.error_message,
    )


@router.post(
    "/dags/{dag_id}/runs",
    response_model=RunStatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger Workflow DAG Execution",
    description="Initiates execution of a registered workflow DAG with runtime input parameters.",
    responses={
        404: {"model": ErrorResponse, "description": "Target workflow DAG not found."},
        500: {"model": ErrorResponse, "description": "Workflow execution pipeline failure."},
    },
)
async def trigger_dag_run(
    dag_id: str,
    payload: RunTriggerRequest | None = None,
    engine: BasaltEngine = Depends(get_engine_dep),
) -> RunStatusResponse:
    """Trigger execution of a registered workflow DAG."""
    inputs = payload.inputs if payload else None
    custom_run_id = payload.run_id if payload else None

    logger.info(f"API triggering run for DAG '{dag_id}'")
    try:
        result = await engine.run_dag(
            dag_id_or_spec=dag_id,
            inputs=inputs,
            run_id=custom_run_id,
        )
        return _to_run_status_response(result)
    except BasaltError as exc:
        raise exc
    except Exception as exc:
        logger.error(f"Execution failed for DAG '{dag_id}' via API: {exc}", exc_info=True)
        raise BasaltError(
            message=f"Failed to execute workflow DAG '{dag_id}': {exc}",
            code="EXECUTION_FAILED",
        )


@router.post(
    "/dags/{dag_id}/runs/batch",
    response_model=BatchRunStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger Batch Execution Runs",
    description="Submit multiple workflow DAG runs concurrently in a single batch API request.",
)
async def trigger_batch_runs(
    dag_id: str,
    payload: BatchRunTriggerRequest,
    engine: BasaltEngine = Depends(get_engine_dep),
) -> BatchRunStatusResponse:
    """Trigger a batch list of workflow executions concurrently."""
    results: list[RunStatusResponse] = []
    for req in payload.requests:
        try:
            res = await engine.run_dag(
                dag_id_or_spec=dag_id,
                inputs=req.inputs,
                run_id=req.run_id,
            )
            results.append(_to_run_status_response(res))
        except Exception as exc:
            logger.error(f"Batch run failed for item in DAG '{dag_id}': {exc}")

    return BatchRunStatusResponse(
        total_submitted=len(payload.requests),
        runs=results,
    )


@router.get(
    "/runs/active",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="List Currently Active Workflow Runs",
    description="Query list of active workflow run IDs currently executing in the engine worker pool.",
)
async def list_active_runs(
    engine: BasaltEngine = Depends(get_engine_dep),
) -> dict[str, Any]:
    """Retrieve active workflow run IDs currently executing."""
    active_ids = engine.runner.get_active_run_ids()
    return {
        "total_active": len(active_ids),
        "active_run_ids": active_ids,
    }


@router.get(
    "/runs/{run_id}",
    response_model=RunStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Workflow Run Status",
    description="Retrieve status snapshot, outputs, and step execution details for a specific run ID.",
    responses={
        404: {"model": ErrorResponse, "description": "Execution run ID not found."},
    },
)
async def get_run_status(
    run_id: str,
    engine: BasaltEngine = Depends(get_engine_dep),
) -> RunStatusResponse:
    """Retrieve details and state for a specific workflow execution run ID."""
    result = await engine.get_run_result(run_id)
    if not result:
        raise BasaltError(
            message=f"Execution run ID '{run_id}' not found.",
            code="RUN_NOT_FOUND",
        )
    return _to_run_status_response(result)


@router.get(
    "/runs/{run_id}/steps/{step_id}",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Get Step Execution Details",
    description="Inspect execution state, returned outputs, and error details for a specific step within a workflow run.",
    responses={
        404: {"model": ErrorResponse, "description": "Run ID or Step ID not found."},
    },
)
async def get_step_run_output(
    run_id: str,
    step_id: str,
    engine: BasaltEngine = Depends(get_engine_dep),
) -> dict[str, Any]:
    """Retrieve execution output and state for a specific step in a workflow run."""
    result = await engine.get_run_result(run_id)
    if not result:
        raise BasaltError(
            message=f"Execution run ID '{run_id}' not found.",
            code="RUN_NOT_FOUND",
        )

    if step_id not in result.step_states:
        raise BasaltError(
            message=f"Step ID '{step_id}' was not executed in run '{run_id}'.",
            code="STEP_NOT_FOUND",
        )

    return {
        "run_id": run_id,
        "dag_id": result.dag_id,
        "step_id": step_id,
        "state": result.step_states[step_id].value,
        "attempt": result.step_attempts.get(step_id, 1),
        "output": result.outputs.get(step_id),
    }



@router.post(
    "/runs/{run_id}/cancel",
    status_code=status.HTTP_200_OK,
    summary="Cancel Active Workflow Run",
    description="Send cancellation signal to abort an actively running workflow.",
    responses={
        404: {"model": ErrorResponse, "description": "Run ID not found or not currently active."},
    },
)
async def cancel_run(
    run_id: str,
    engine: BasaltEngine = Depends(get_engine_dep),
) -> dict[str, Any]:
    """Request cancellation for an active workflow execution run."""
    cancelled = engine.runner.cancel_run(run_id)
    if not cancelled:
        raise BasaltError(
            message=f"Run ID '{run_id}' is not currently active or cannot be cancelled.",
            code="RUN_NOT_ACTIVE",
        )
    logger.info(f"API cancelled workflow run '{run_id}'")
    return {
        "cancelled": True,
        "run_id": run_id,
        "message": f"Successfully sent cancellation signal to run '{run_id}'.",
    }


@router.post(
    "/runs/{run_id}/retry",
    response_model=RunStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Retry Failed Workflow Run",
    description="Re-trigger execution of a previously failed or timed-out workflow run with original inputs.",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Run is not in a failed or terminal retryable state.",
        },
        404: {"model": ErrorResponse, "description": "Target run ID not found."},
    },
)
async def retry_failed_run(
    run_id: str,
    engine: BasaltEngine = Depends(get_engine_dep),
) -> RunStatusResponse:
    """Re-trigger execution of a failed workflow run."""
    original_run = await engine.get_run_result(run_id)
    if not original_run:
        raise BasaltError(
            message=f"Execution run ID '{run_id}' not found.",
            code="RUN_NOT_FOUND",
        )

    if original_run.state not in (
        WorkflowState.FAILED,
        WorkflowState.TIMEOUT,
        WorkflowState.CANCELLED,
    ):
        raise BasaltError(
            message=f"Run '{run_id}' is in state '{original_run.state.value}' and cannot be retried.",
            code="INVALID_RUN_STATE_FOR_RETRY",
        )

    logger.info(f"API retrying failed workflow run '{run_id}' for DAG '{original_run.dag_id}'")
    new_result = await engine.run_dag(
        dag_id_or_spec=original_run.dag_id,
        inputs=original_run.inputs,
    )
    return _to_run_status_response(new_result)


@router.get(
    "/runs",
    response_model=RunListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Workflow Run Logs",
    description="Retrieve paginated list of workflow execution run records filtered by DAG ID or state.",
)
async def list_runs(
    dag_id: str | None = Query(None, description="Optional DAG ID filter."),
    state: WorkflowState | None = Query(None, description="Optional workflow state filter."),
    page: int = Query(1, ge=1, description="Page index (1-based)."),
    size: int = Query(50, ge=1, le=200, description="Items per page limit."),
    engine: BasaltEngine = Depends(get_engine_dep),
) -> RunListResponse:
    """Query and list execution run records."""
    all_runs = await engine.list_run_results(dag_id=dag_id, state=state)
    total = len(all_runs)

    start = (page - 1) * size
    end = start + size
    paginated_runs = all_runs[start:end]

    return RunListResponse(
        total=total,
        runs=[_to_run_status_response(r) for r in paginated_runs],
        page=page,
        size=size,
    )
