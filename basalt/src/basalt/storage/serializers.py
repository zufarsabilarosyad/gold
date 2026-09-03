"""Bidirectional AST, ORM Model & JSON Serializer Subsystem Module for Basalt Engine.

Converts between Pydantic AST schemas (DAGSpec, TriggerSpec, WorkflowRunResult),
SQLAlchemy 2.0 ORM models (DAGModel, DAGRunModel, TriggerModel), and raw JSON dictionaries.
"""

import json
from datetime import UTC, datetime
from typing import Any

from basalt.core.dag.ast import DAGSpec, TriggerSpec
from basalt.core.engine.runner import WorkflowRunResult
from basalt.core.engine.state_machine import StepState, WorkflowState
from basalt.storage.models import DAGModel, DAGRunModel, StepRunModel, TriggerModel
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder supporting datetime, Enum, and custom objects serialization."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, "value"):  # Handles Enum types
            return obj.value
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        return super().default(obj)


def json_dumps(obj: Any) -> str:
    """Helper serializer using CustomJSONEncoder."""
    return json.dumps(obj, cls=CustomJSONEncoder)


def json_loads(json_str: str) -> Any:
    """Helper deserializer for JSON strings."""
    if not json_str:
        return {}
    return json.loads(json_str)


class ModelSerializer:
    """Converter utility for AST Pydantic objects and SQLAlchemy ORM models."""

    # --- DAG AST <-> DAGModel ---

    @staticmethod
    def dag_to_orm(dag: DAGSpec) -> DAGModel:
        """Convert DAGSpec AST object to DAGModel ORM entity."""
        spec_dict = dag.model_dump(mode="json")
        return DAGModel(
            id=dag.id,
            name=dag.name,
            description=dag.description,
            version=dag.version,
            owner=dag.owner,
            tags_json=json_dumps(dag.tags),
            timeout_seconds=dag.timeout_seconds,
            max_concurrency=dag.max_concurrency,
            spec_json=json_dumps(spec_dict),
        )

    @staticmethod
    def orm_to_dag(model: DAGModel) -> DAGSpec:
        """Convert DAGModel ORM entity to DAGSpec AST object."""
        spec_data = json_loads(model.spec_json)
        return DAGSpec.model_validate(spec_data)

    @staticmethod
    def orm_list_to_dags(models: list[DAGModel]) -> list[DAGSpec]:
        """Convert list of DAGModel ORM entities to list of DAGSpec AST objects."""
        return [ModelSerializer.orm_to_dag(m) for m in models]

    # --- WorkflowRunResult <-> DAGRunModel ---

    @staticmethod
    def run_result_to_orm(result: WorkflowRunResult) -> DAGRunModel:
        """Convert WorkflowRunResult container to DAGRunModel ORM entity with child StepRunModels."""
        run_model = DAGRunModel(
            id=result.run_id,
            dag_id=result.dag_id,
            state=result.state.value
            if isinstance(result.state, WorkflowState)
            else str(result.state),
            start_time=result.start_time,
            end_time=result.end_time,
            duration_ms=result.duration_ms,
            inputs_json=json_dumps(result.inputs),
            outputs_json=json_dumps(result.outputs),
            error_message=result.error_message,
        )

        # Convert step states into child StepRunModel records
        for step_id, state in result.step_states.items():
            step_output = result.outputs.get(step_id)
            state_val = state.value if isinstance(state, StepState) else str(state)
            step_model = StepRunModel(
                run_id=result.run_id,
                step_id=step_id,
                state=state_val,
                attempt=result.step_attempts.get(step_id, 1),
                start_time=result.start_time,
                end_time=result.end_time,
                output_json=json_dumps(step_output) if step_output is not None else None,
            )
            run_model.step_runs.append(step_model)

        return run_model

    @staticmethod
    def orm_to_run_result(model: DAGRunModel) -> WorkflowRunResult:
        """Convert DAGRunModel ORM entity to WorkflowRunResult container."""
        inputs_dict = json_loads(model.inputs_json)
        outputs_dict = json_loads(model.outputs_json)

        step_states_dict: dict[str, StepState] = {}
        step_attempts_dict: dict[str, int] = {}
        for step_run in model.step_runs:
            try:
                step_states_dict[step_run.step_id] = StepState(step_run.state)
                step_attempts_dict[step_run.step_id] = step_run.attempt
            except ValueError:
                step_states_dict[step_run.step_id] = StepState.FAILED

        wf_state = (
            WorkflowState(model.state)
            if model.state in [s.value for s in WorkflowState]
            else WorkflowState.FAILED
        )

        start_t = model.start_time if model.start_time else datetime.now(UTC)
        end_t = model.end_time if model.end_time else datetime.now(UTC)

        return WorkflowRunResult(
            run_id=model.id,
            dag_id=model.dag_id,
            state=wf_state,
            start_time=start_t,
            end_time=end_t,
            duration_ms=model.duration_ms or 0.0,
            inputs=inputs_dict,
            outputs=outputs_dict,
            step_states=step_states_dict,
            step_attempts=step_attempts_dict,
            error_message=model.error_message,
        )


    @staticmethod
    def orm_list_to_run_results(models: list[DAGRunModel]) -> list[WorkflowRunResult]:
        """Convert list of DAGRunModel ORM entities to list of WorkflowRunResult objects."""
        return [ModelSerializer.orm_to_run_result(m) for m in models]

    # --- TriggerSpec <-> TriggerModel ---

    @staticmethod
    def trigger_to_orm(trigger: TriggerSpec, dag_id: str) -> TriggerModel:
        """Convert TriggerSpec object to TriggerModel ORM entity."""
        return TriggerModel(
            id=trigger.id,
            dag_id=dag_id,
            type=trigger.type.value if hasattr(trigger.type, "value") else str(trigger.type),
            cron=trigger.cron,
            interval_seconds=trigger.interval_seconds,
            webhook_secret=trigger.webhook_secret,
            enabled=trigger.enabled,
        )

    @staticmethod
    def orm_to_trigger(model: TriggerModel) -> TriggerSpec:
        """Convert TriggerModel ORM entity to TriggerSpec object."""
        return TriggerSpec(
            id=model.id,
            type=model.type,
            cron=model.cron,
            interval_seconds=model.interval_seconds,
            webhook_secret=model.webhook_secret,
            enabled=model.enabled,
        )

    @staticmethod
    def trigger_list_to_orm(triggers: list[TriggerSpec], dag_id: str) -> list[TriggerModel]:
        """Convert list of TriggerSpec objects to list of TriggerModel ORM entities."""
        return [ModelSerializer.trigger_to_orm(t, dag_id=dag_id) for t in triggers]

    @staticmethod
    def orm_list_to_triggers(models: list[TriggerModel]) -> list[TriggerSpec]:
        """Convert list of TriggerModel ORM entities to list of TriggerSpec objects."""
        return [ModelSerializer.orm_to_trigger(m) for m in models]
