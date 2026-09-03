"""FastAPI REST API Router Subsystem for Event Triggers, Webhooks, and Dead-Letter Queue (DLQ).

Provides API endpoints for handling incoming HTTP webhook events, inspecting registered triggers,
pausing/resuming triggers, and inspecting/retrying items in the Dead-Letter Queue (DLQ).
"""

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status

from basalt.api.schemas import (
    DLQItemResponse,
    DLQListResponse,
    ErrorResponse,
    RunStatusResponse,
    StepRunResponse,
    TriggerListResponse,
    TriggerResponse,
)
from basalt.core.dag.exceptions import BasaltError
from basalt.core.engine.engine import BasaltEngine, get_engine
from basalt.core.engine.runner import WorkflowRunResult
from basalt.core.triggers.base import BaseTrigger
from basalt.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Event Triggers & Webhooks"])


def get_engine_dep() -> BasaltEngine:
    """Dependency injector for BasaltEngine facade instance."""
    return get_engine()


def _to_trigger_response(trigger: BaseTrigger) -> TriggerResponse:
    """Convert BaseTrigger instance into API TriggerResponse model."""
    return TriggerResponse(
        id=trigger.spec.id,
        dag_id=trigger.dag_id,
        type=trigger.spec.type,
        status=trigger.status.value,
        enabled=trigger.spec.enabled,
        next_fire_time=trigger.get_next_fire_time(),
        last_fired_at=trigger.last_fired_at,
    )


def _to_run_status_response(result: WorkflowRunResult) -> RunStatusResponse:
    """Convert WorkflowRunResult engine snapshot into API RunStatusResponse model."""
    step_runs = [
        StepRunResponse(
            step_id=step_id,
            state=state,
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


# --- Webhook Endpoint ---


@router.post(
    "/webhooks/{trigger_id}",
    response_model=RunStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest HTTP Webhook Event",
    description="Authenticates incoming HMAC signature header, evaluates payload, and triggers target workflow DAG.",
    responses={
        401: {"model": ErrorResponse, "description": "HMAC signature verification failed."},
        404: {"model": ErrorResponse, "description": "Webhook trigger ID not registered."},
    },
)
async def handle_webhook_event(
    trigger_id: str,
    request: Request,
    engine: BasaltEngine = Depends(get_engine_dep),
) -> RunStatusResponse:
    """Receive HTTP webhook payload and initiate target workflow DAG execution."""
    raw_body = await request.body()
    headers_dict = dict(request.headers)

    payload_dict: dict[str, Any] | None = None
    try:
        if raw_body:
            payload_dict = await request.json()
    except Exception:
        payload_dict = None

    logger.info(f"API received HTTP webhook POST for trigger '{trigger_id}'")
    try:
        run_res = await engine.process_webhook_event(
            trigger_id=trigger_id,
            raw_body=raw_body,
            headers=headers_dict,
            payload_dict=payload_dict,
        )
        return _to_run_status_response(run_res)
    except BasaltError as exc:
        raise exc
    except Exception as exc:
        logger.error(
            f"Failed processing webhook event for trigger '{trigger_id}': {exc}", exc_info=True
        )
        raise BasaltError(
            message=f"Webhook processing error: {exc}",
            code="WEBHOOK_PROCESSING_FAILED",
        )


# --- Event Triggers Management Endpoints ---


@router.get(
    "/triggers",
    response_model=TriggerListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Registered Event Triggers",
    description="Retrieve list of registered event triggers with optional DAG ID filter.",
)
async def list_triggers(
    dag_id: str | None = Query(None, description="Optional target DAG ID filter."),
    engine: BasaltEngine = Depends(get_engine_dep),
) -> TriggerListResponse:
    """List registered event triggers."""
    triggers = engine.dispatcher.list_triggers(dag_id=dag_id)
    return TriggerListResponse(
        total=len(triggers),
        triggers=[_to_trigger_response(trig) for trig in triggers],
    )


@router.post(
    "/triggers/{trigger_id}/pause",
    response_model=TriggerResponse,
    status_code=status.HTTP_200_OK,
    summary="Pause Event Trigger",
    description="Pause periodic schedule evaluation for a registered event trigger.",
    responses={
        404: {"model": ErrorResponse, "description": "Trigger ID not found."},
    },
)
async def pause_trigger(
    trigger_id: str,
    engine: BasaltEngine = Depends(get_engine_dep),
) -> TriggerResponse:
    """Pause an active event trigger."""
    trig = engine.dispatcher.get_trigger(trigger_id)
    if not trig:
        raise BasaltError(
            message=f"Event trigger ID '{trigger_id}' not found.",
            code="TRIGGER_NOT_FOUND",
        )

    engine.dispatcher.pause_trigger(trigger_id)
    logger.info(f"API paused event trigger '{trigger_id}'")
    return _to_trigger_response(trig)


@router.post(
    "/triggers/{trigger_id}/resume",
    response_model=TriggerResponse,
    status_code=status.HTTP_200_OK,
    summary="Resume Event Trigger",
    description="Resume periodic evaluation for a previously paused event trigger.",
    responses={
        404: {"model": ErrorResponse, "description": "Trigger ID not found."},
    },
)
async def resume_trigger(
    trigger_id: str,
    engine: BasaltEngine = Depends(get_engine_dep),
) -> TriggerResponse:
    """Resume a paused event trigger."""
    trig = engine.dispatcher.get_trigger(trigger_id)
    if not trig:
        raise BasaltError(
            message=f"Event trigger ID '{trigger_id}' not found.",
            code="TRIGGER_NOT_FOUND",
        )

    engine.dispatcher.resume_trigger(trigger_id)
    logger.info(f"API resumed event trigger '{trigger_id}'")
    return _to_trigger_response(trig)


# --- Dead-Letter Queue (DLQ) Endpoints ---


@router.get(
    "/dlq",
    response_model=DLQListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Dead-Letter Queue Items",
    description="Retrieve items stored in Dead-Letter Queue resulting from unrecoverable failures.",
)
async def list_dlq_items(
    dag_id: str | None = Query(None, description="Optional DAG ID filter."),
    processed: bool | None = Query(None, description="Optional processed status filter."),
    page: int = Query(1, ge=1, description="Page index (1-based)."),
    size: int = Query(50, ge=1, le=200, description="Items per page limit."),
    engine: BasaltEngine = Depends(get_engine_dep),
) -> DLQListResponse:
    """Query items in Dead-Letter Queue (DLQ)."""
    items_raw: list[dict[str, Any]] = []

    if engine.repository:
        offset = (page - 1) * size
        dlq_models = await engine.repository.list_dlq_items(
            dag_id=dag_id,
            processed=processed,
            limit=size,
            offset=offset,
        )
        total = await engine.repository.count_dlq_items(dag_id=dag_id, processed=processed)

        for m in dlq_models:
            items_raw.append(
                DLQItemResponse(
                    payload_id=m.payload_id,
                    dag_id=m.dag_id,
                    step_id=m.step_id,
                    error_code=m.error_code,
                    error_message=m.error_message,
                    payload=m.payload_dict or {},
                    processed=m.processed,
                    created_at=m.created_at,
                )
            )
        return DLQListResponse(total=total, items=items_raw)

    return DLQListResponse(total=0, items=[])


@router.post(
    "/dlq/{payload_id}/retry",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Retry Dead-Letter Queue Item",
    description="Re-submit unrecoverable payload from DLQ for execution and mark DLQ entry as processed.",
    responses={
        404: {"model": ErrorResponse, "description": "DLQ payload ID not found."},
    },
)
async def retry_dlq_item(
    payload_id: str,
    engine: BasaltEngine = Depends(get_engine_dep),
) -> dict[str, Any]:
    """Retry a Dead-Letter Queue entry."""
    if not engine.repository:
        raise BasaltError(
            message="DLQ operations require SQLite database storage repository backend.",
            code="STORAGE_ENGINE_NOT_SUPPORTED",
        )

    item = await engine.repository.get_dlq_item(payload_id)
    if not item:
        raise BasaltError(
            message=f"DLQ payload ID '{payload_id}' not found.",
            code="DLQ_ITEM_NOT_FOUND",
        )

    # Mark as processed
    await engine.repository.mark_dlq_processed(payload_id)

    # Re-run DAG if dag_id is present
    run_id: str | None = None
    if item.dag_id:
        res = await engine.run_dag(dag_id_or_spec=item.dag_id, inputs=item.payload_dict)
        run_id = res.run_id

    return {
        "retried": True,
        "payload_id": payload_id,
        "new_run_id": run_id,
        "message": f"Successfully processed DLQ payload '{payload_id}'.",
    }
