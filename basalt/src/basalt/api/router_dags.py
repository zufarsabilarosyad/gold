"""FastAPI REST API Router Subsystem for Workflow DAG Operations.

Provides API endpoints for registering workflow DAG specifications (YAML/JSON),
inspecting registered DAG definitions, listing DAGs with tag filtering and pagination,
validating DAG AST structure and topological dependencies, querying execution graph topology, and deleting DAGs.
"""

from typing import Any

from fastapi import APIRouter, Depends, Query, status

from basalt.api.schemas import (
    DAGListResponse,
    DAGRegisterRequest,
    DAGResponse,
    ErrorResponse,
)
from basalt.core.dag.ast import DAGSpec
from basalt.core.dag.exceptions import BasaltError
from basalt.core.dag.parser import DAGParser
from basalt.core.dag.sorter import DAGSorter
from basalt.core.dag.validator import DAGValidator
from basalt.core.engine.engine import BasaltEngine, get_engine
from basalt.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/dags", tags=["Workflows"])


def get_engine_dep() -> BasaltEngine:
    """Dependency injector for BasaltEngine facade instance."""
    return get_engine()


def _to_dag_response(dag: DAGSpec) -> DAGResponse:
    """Convert internal AST DAGSpec model into API DAGResponse payload."""
    return DAGResponse(
        id=dag.id,
        name=dag.name,
        description=dag.description,
        version=dag.version,
        owner=dag.owner,
        tags=dag.tags,
        step_count=len(dag.steps),
        trigger_count=len(dag.triggers),
        created_at=getattr(dag, "created_at", None),
        updated_at=getattr(dag, "updated_at", None),
    )


@router.post(
    "/",
    response_model=DAGResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new Workflow DAG",
    description="Parses YAML or JSON workflow specification, validates topological DAG structure, and persists definition.",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Syntax or validation error in DAG specification.",
        },
        409: {
            "model": ErrorResponse,
            "description": "Workflow DAG with given ID already registered.",
        },
    },
)
async def register_dag(
    payload: DAGRegisterRequest,
    engine: BasaltEngine = Depends(get_engine_dep),
) -> DAGResponse:
    """Register or update a workflow DAG specification."""
    try:
        dag = await engine.register_dag(
            dag_input=payload.spec,
            overwrite=payload.overwrite,
        )
        logger.info(f"API registered workflow DAG '{dag.id}'")
        return _to_dag_response(dag)
    except BasaltError as exc:
        raise exc
    except Exception as exc:
        logger.error(f"Failed to register workflow DAG via API: {exc}", exc_info=True)
        raise BasaltError(
            message=f"Failed to parse or validate workflow DAG: {exc}",
            code="DAG_VALIDATION_ERROR",
        )


@router.post(
    "/validate",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Validate Workflow DAG Specification",
    description="Validates AST structure, executor parameters, and cycle-free topological sorting without persisting.",
)
async def validate_dag_spec(payload: DAGRegisterRequest) -> dict[str, Any]:
    """Validate YAML/JSON workflow specification without persisting."""
    try:
        dag = DAGParser.parse_string(payload.spec)
        DAGValidator.validate_dag(dag)
        stages = DAGSorter.get_execution_levels(dag)

        return {
            "valid": True,
            "dag_id": dag.id,
            "name": dag.name,
            "step_count": len(dag.steps),
            "execution_stages_count": len(stages),
            "trigger_count": len(dag.triggers),
        }
    except BasaltError as exc:
        raise exc
    except Exception as exc:
        raise BasaltError(
            message=f"Specification validation failed: {exc}",
            code="DAG_VALIDATION_FAILED",
        )


@router.get(
    "/",
    response_model=DAGListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Registered Workflow DAGs",
    description="Retrieve paginated list of registered workflow DAGs with optional tag filtering.",
)
async def list_dags(
    tag: str | None = Query(None, description="Optional tag filter."),
    page: int = Query(1, ge=1, description="Page index (1-based)."),
    size: int = Query(50, ge=1, le=200, description="Items per page limit."),
    engine: BasaltEngine = Depends(get_engine_dep),
) -> DAGListResponse:
    """Retrieve list of registered workflow DAGs."""
    all_dags = await engine.list_dags(tag=tag)
    total = len(all_dags)

    start = (page - 1) * size
    end = start + size
    paginated_dags = all_dags[start:end]

    return DAGListResponse(
        total=total,
        dags=[_to_dag_response(dag) for dag in paginated_dags],
        page=page,
        size=size,
    )


@router.get(
    "/{dag_id}",
    response_model=DAGResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Workflow DAG by ID",
    description="Inspect a specific registered workflow DAG definition.",
    responses={
        404: {"model": ErrorResponse, "description": "Workflow DAG not found."},
    },
)
async def get_dag(
    dag_id: str,
    engine: BasaltEngine = Depends(get_engine_dep),
) -> DAGResponse:
    """Retrieve details for a specific workflow DAG."""
    dag = await engine.get_dag(dag_id)
    if not dag:
        raise BasaltError(
            message=f"Workflow DAG '{dag_id}' not found.",
            code="DAG_NOT_FOUND",
        )
    return _to_dag_response(dag)


@router.get(
    "/{dag_id}/graph",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Get Workflow DAG Graph Topology",
    description="Inspect topological parallel stages, step dependencies, and critical execution path for a DAG.",
    responses={
        404: {"model": ErrorResponse, "description": "Workflow DAG not found."},
    },
)
async def get_dag_graph(
    dag_id: str,
    engine: BasaltEngine = Depends(get_engine_dep),
) -> dict[str, Any]:
    """Retrieve topological graph execution stages and dependency structure."""
    dag = await engine.get_dag(dag_id)
    if not dag:
        raise BasaltError(
            message=f"Workflow DAG '{dag_id}' not found.",
            code="DAG_NOT_FOUND",
        )

    execution_levels = DAGSorter.get_execution_levels(dag)
    critical_path = DAGSorter.get_critical_path(dag)

    stages_repr = []
    for level_idx, level_steps in enumerate(execution_levels):
        stages_repr.append(
            {
                "stage": level_idx + 1,
                "parallel_step_ids": [s.id for s in level_steps],
            }
        )

    return {
        "dag_id": dag.id,
        "name": dag.name,
        "step_count": len(dag.steps),
        "execution_stages": stages_repr,
        "critical_path_step_ids": [s.id for s in critical_path],
    }


@router.delete(
    "/{dag_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete Registered Workflow DAG",
    description="Remove workflow DAG definition and unregister associated event triggers.",
    responses={
        404: {"model": ErrorResponse, "description": "Workflow DAG not found."},
    },
)
async def delete_dag(
    dag_id: str,
    engine: BasaltEngine = Depends(get_engine_dep),
) -> dict[str, Any]:
    """Delete a workflow DAG definition."""
    existing = await engine.get_dag(dag_id)
    if not existing:
        raise BasaltError(
            message=f"Workflow DAG '{dag_id}' not found.",
            code="DAG_NOT_FOUND",
        )

    deleted = await engine.delete_dag(dag_id)
    logger.info(f"API deleted workflow DAG '{dag_id}'")

    return {
        "deleted": deleted,
        "dag_id": dag_id,
        "message": f"Successfully deleted workflow DAG '{dag_id}'.",
    }
