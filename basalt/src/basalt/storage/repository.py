"""High-Level Async Database Repository Subsystem Module for Basalt Engine.

Provides BasaltRepository class encapsulating async CRUD operations for DAG workflows,
execution run logs, step state transitions, triggers, and Dead-Letter Queue (DLQ) payloads.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from basalt.core.dag.ast import DAGSpec
from basalt.core.engine.runner import WorkflowRunResult
from basalt.core.engine.state_machine import StepState, WorkflowState
from basalt.core.storage.base import AlreadyExistsError
from basalt.storage.database import DatabaseManager, get_db_manager
from basalt.storage.models import DAGModel, DAGRunModel, DLQModel, StepRunModel, TriggerModel
from basalt.storage.serializers import ModelSerializer, json_dumps
from basalt.utils.crypto import generate_run_id
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class BasaltRepository:
    """Async database repository exposing workflow persistence and execution ledger APIs."""

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self.db_manager = db_manager or get_db_manager()

    async def initialize(self) -> None:
        """Initialize database connection pool and create tables."""
        await self.db_manager.create_tables()

    # --- Workflow DAG Operations ---

    async def save_dag(self, dag: DAGSpec, overwrite: bool = True) -> DAGSpec:
        """Persist or update a DAGSpec workflow definition.

        Args:
            dag: DAGSpec AST object.
            overwrite: Whether to overwrite existing DAG definition.

        Returns:
            Saved DAGSpec object.

        Raises:
            AlreadyExistsError: If overwrite is False and DAG exists.
        """
        await self.initialize()

        async with self.db_manager.session() as session:
            existing = await session.get(DAGModel, dag.id)
            if existing is not None:
                if not overwrite:
                    raise AlreadyExistsError(entity_type="Workflow DAG", entity_id=dag.id)

                # Delete existing triggers first
                await session.execute(delete(TriggerModel).where(TriggerModel.dag_id == dag.id))

                # Update existing model
                existing.name = dag.name
                existing.description = dag.description
                existing.version = dag.version
                existing.owner = dag.owner
                existing.tags_json = json_dumps(dag.tags)
                existing.timeout_seconds = dag.timeout_seconds
                existing.max_concurrency = dag.max_concurrency
                existing.spec_json = json_dumps(dag.model_dump(mode="json"))
                existing.updated_at = datetime.now(UTC)

                # Save new triggers
                for trig in dag.triggers:
                    trig_orm = ModelSerializer.trigger_to_orm(trig, dag_id=dag.id)
                    session.add(trig_orm)

                logger.info(f"Updated existing DAGSpec '{dag.id}' in database")
            else:
                dag_orm = ModelSerializer.dag_to_orm(dag)
                session.add(dag_orm)
                for trig in dag.triggers:
                    trig_orm = ModelSerializer.trigger_to_orm(trig, dag_id=dag.id)
                    session.add(trig_orm)
                logger.info(f"Saved new DAGSpec '{dag.id}' in database")

        return dag

    async def get_dag(self, dag_id: str) -> DAGSpec | None:
        """Fetch DAGSpec workflow definition by ID."""
        await self.initialize()

        async with self.db_manager.session() as session:
            stmt = select(DAGModel).where(DAGModel.id == dag_id)
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return ModelSerializer.orm_to_dag(model)

    async def delete_dag(self, dag_id: str) -> bool:
        """Delete workflow definition and cascade associated runs/triggers."""
        await self.initialize()

        async with self.db_manager.session() as session:
            model = await session.get(DAGModel, dag_id)
            if model is None:
                return False

            await session.delete(model)
            logger.info(f"Deleted DAGSpec '{dag_id}' from database")
            return True

    async def list_dags(
        self,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DAGSpec]:
        """Query and list stored DAGSpec definitions with optional tag filter."""
        await self.initialize()

        async with self.db_manager.session() as session:
            stmt = select(DAGModel).order_by(DAGModel.created_at.desc())
            if tag:
                stmt = stmt.where(DAGModel.tags_json.like(f'%"{tag}"%'))

            stmt = stmt.offset(offset).limit(limit)
            result = await session.execute(stmt)
            models = result.scalars().all()
            return ModelSerializer.orm_list_to_dags(list(models))

    async def count_dags(self, tag: str | None = None) -> int:
        """Count total stored workflow DAG definitions."""
        await self.initialize()

        async with self.db_manager.session() as session:
            stmt = select(func.count(DAGModel.id))
            if tag:
                stmt = stmt.where(DAGModel.tags_json.like(f'%"{tag}"%'))
            result = await session.execute(stmt)
            return result.scalar_one() or 0

    # --- Workflow Run Ledger Operations ---

    async def create_run(
        self,
        dag_id: str,
        run_id: str | None = None,
        inputs: dict[str, Any] | None = None,
    ) -> DAGRunModel:
        """Create a new pending workflow execution run record."""
        await self.initialize()

        active_run_id = run_id or generate_run_id()
        now = datetime.now(UTC)

        async with self.db_manager.session() as session:
            run_model = DAGRunModel(
                id=active_run_id,
                dag_id=dag_id,
                state=WorkflowState.PENDING.value,
                start_time=now,
                inputs_json=json_dumps(inputs or {}),
                outputs_json="{}",
            )
            session.add(run_model)
            logger.info(f"Created workflow run record '{active_run_id}' for DAG '{dag_id}'")
            return run_model

    async def save_run_result(self, result: WorkflowRunResult) -> None:
        """Save complete WorkflowRunResult snapshot into database."""
        await self.initialize()

        async with self.db_manager.session() as session:
            existing = await session.get(DAGRunModel, result.run_id)
            state_val = (
                result.state.value if isinstance(result.state, WorkflowState) else str(result.state)
            )

            if existing is not None:
                existing.state = state_val
                existing.end_time = result.end_time
                existing.duration_ms = result.duration_ms
                existing.inputs_json = json_dumps(result.inputs)
                existing.outputs_json = json_dumps(result.outputs)
                existing.error_message = result.error_message

                # Update step runs
                await session.execute(
                    delete(StepRunModel).where(StepRunModel.run_id == result.run_id)
                )
                for step_id, st in result.step_states.items():
                    step_output = result.outputs.get(step_id)
                    st_val = st.value if isinstance(st, StepState) else str(st)
                    step_model = StepRunModel(
                        run_id=result.run_id,
                        step_id=step_id,
                        state=st_val,
                        attempt=result.step_attempts.get(step_id, 1),
                        start_time=result.start_time,
                        end_time=result.end_time,
                        output_json=json_dumps(step_output) if step_output is not None else None,
                    )

                    session.add(step_model)
            else:
                run_orm = ModelSerializer.run_result_to_orm(result)
                session.add(run_orm)

            logger.debug(f"Saved run result '{result.run_id}' in database")

    async def get_run(self, run_id: str) -> WorkflowRunResult | None:
        """Fetch execution run log result by run ID."""
        await self.initialize()

        async with self.db_manager.session() as session:
            stmt = (
                select(DAGRunModel)
                .options(selectinload(DAGRunModel.step_runs))
                .where(DAGRunModel.id == run_id)
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return ModelSerializer.orm_to_run_result(model)

    async def update_run_state(
        self,
        run_id: str,
        state: WorkflowState,
        duration_ms: float | None = None,
        outputs: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> DAGRunModel | None:
        """Update active workflow run state and completion status."""
        await self.initialize()

        async with self.db_manager.session() as session:
            model = await session.get(DAGRunModel, run_id)
            if model is None:
                return None

            state_val = state.value if isinstance(state, WorkflowState) else str(state)
            model.state = state_val

            is_terminal_wf = state in (
                WorkflowState.COMPLETED,
                WorkflowState.FAILED,
                WorkflowState.CANCELLED,
                WorkflowState.TIMEOUT,
            )
            if is_terminal_wf:
                model.end_time = datetime.now(UTC)
            if duration_ms is not None:
                model.duration_ms = duration_ms
            if outputs is not None:
                model.outputs_json = json_dumps(outputs)
            if error_message is not None:
                model.error_message = error_message

            logger.info(f"Updated run '{run_id}' state to '{model.state}'")
            return model

    async def list_runs(
        self,
        dag_id: str | None = None,
        state: WorkflowState | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WorkflowRunResult]:
        """Query execution run logs with optional filters and pagination."""
        await self.initialize()

        async with self.db_manager.session() as session:
            stmt = (
                select(DAGRunModel)
                .options(selectinload(DAGRunModel.step_runs))
                .order_by(DAGRunModel.start_time.desc())
            )
            if dag_id:
                stmt = stmt.where(DAGRunModel.dag_id == dag_id)
            if state:
                state_val = state.value if isinstance(state, WorkflowState) else str(state)
                stmt = stmt.where(DAGRunModel.state == state_val)

            stmt = stmt.offset(offset).limit(limit)
            result = await session.execute(stmt)
            models = result.scalars().all()
            return ModelSerializer.orm_list_to_run_results(list(models))

    async def count_runs(
        self,
        dag_id: str | None = None,
        state: WorkflowState | None = None,
    ) -> int:
        """Count total workflow execution runs matching filters."""
        await self.initialize()

        async with self.db_manager.session() as session:
            stmt = select(func.count(DAGRunModel.id))
            if dag_id:
                stmt = stmt.where(DAGRunModel.dag_id == dag_id)
            if state:
                state_val = state.value if isinstance(state, WorkflowState) else str(state)
                stmt = stmt.where(DAGRunModel.state == state_val)

            result = await session.execute(stmt)
            return result.scalar_one() or 0

    async def delete_run(self, run_id: str) -> bool:
        """Delete an execution run record and child step runs."""
        await self.initialize()

        async with self.db_manager.session() as session:
            model = await session.get(DAGRunModel, run_id)
            if model is None:
                return False

            await session.delete(model)
            logger.info(f"Deleted workflow run '{run_id}' from database")
            return True

    # --- Step Execution Records ---

    async def record_step_run(
        self,
        run_id: str,
        step_id: str,
        state: StepState,
        attempt: int = 1,
        output: Any | None = None,
        error_message: str | None = None,
    ) -> StepRunModel:
        """Record step execution status snapshot within a workflow run."""
        await self.initialize()

        now = datetime.now(UTC)
        state_val = state.value if isinstance(state, StepState) else str(state)
        is_terminal_step = state in (
            StepState.COMPLETED,
            StepState.FAILED,
            StepState.SKIPPED,
            StepState.CANCELLED,
        )

        async with self.db_manager.session() as session:
            step_orm = StepRunModel(
                run_id=run_id,
                step_id=step_id,
                state=state_val,
                attempt=attempt,
                start_time=now,
                end_time=now if is_terminal_step else None,
                output_json=json_dumps(output) if output is not None else None,
                error_message=error_message,
            )
            session.add(step_orm)
            return step_orm

    # --- Dead-Letter Queue (DLQ) Operations ---

    async def save_dlq_payload(
        self,
        payload_id: str,
        error_code: str,
        error_message: str,
        payload: dict[str, Any],
        dag_id: str | None = None,
        step_id: str | None = None,
    ) -> DLQModel:
        """Persist unrecoverable payload into Dead-Letter Queue table."""
        await self.initialize()

        async with self.db_manager.session() as session:
            dlq_orm = DLQModel(
                payload_id=payload_id,
                dag_id=dag_id,
                step_id=step_id,
                error_code=error_code,
                error_message=error_message,
                payload_json=json_dumps(payload),
                created_at=datetime.now(UTC),
            )
            session.add(dlq_orm)
            logger.warning(f"Persisted DLQ payload '{payload_id}' for error '{error_code}'")
            return dlq_orm

    async def list_dlq_payloads(
        self,
        dag_id: str | None = None,
        processed: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DLQModel]:
        """List stored Dead-Letter Queue entries."""
        await self.initialize()

        async with self.db_manager.session() as session:
            stmt = select(DLQModel).order_by(DLQModel.created_at.desc())
            if dag_id is not None:
                stmt = stmt.where(DLQModel.dag_id == dag_id)
            if processed is not None:
                stmt = stmt.where(DLQModel.processed == processed)

            stmt = stmt.offset(offset).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    list_dlq_items = list_dlq_payloads

    async def count_dlq_items(
        self,
        dag_id: str | None = None,
        processed: bool | None = None,
    ) -> int:
        """Count stored Dead-Letter Queue entries."""
        await self.initialize()

        async with self.db_manager.session() as session:
            stmt = select(func.count(DLQModel.id))
            if dag_id is not None:
                stmt = stmt.where(DLQModel.dag_id == dag_id)
            if processed is not None:
                stmt = stmt.where(DLQModel.processed == processed)

            result = await session.execute(stmt)
            return result.scalar_one() or 0

    async def mark_dlq_processed(self, payload_id: str) -> bool:
        """Mark Dead-Letter Queue entry as processed/resolved."""
        await self.initialize()

        async with self.db_manager.session() as session:
            stmt = select(DLQModel).where(DLQModel.payload_id == payload_id)
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return False

            model.processed = True
            logger.info(f"Marked DLQ payload '{payload_id}' as processed")
            return True


def get_repository(db_url: str = "sqlite+aiosqlite:///basalt.db") -> BasaltRepository:
    """Retrieve BasaltRepository instance using specified database URL."""
    db_mgr = get_db_manager(db_url=db_url)
    return BasaltRepository(db_manager=db_mgr)
