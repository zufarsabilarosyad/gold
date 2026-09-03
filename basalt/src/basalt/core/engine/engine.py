"""Top-Level BasaltEngine Facade Subsystem Module.

Provides BasaltEngine class unifying YAML/JSON DAG parsing, topological sorting validation,
storage persistence, resilient worker pool execution, and event trigger dispatching.
"""

from typing import Any

from pydantic import BaseModel, Field

from basalt.core.dag.ast import DAGSpec
from basalt.core.dag.exceptions import BasaltError
from basalt.core.dag.parser import DAGParser
from basalt.core.dag.sorter import DAGSorter
from basalt.core.dag.validator import DAGValidator
from basalt.core.engine.runner import WorkflowRunner, WorkflowRunResult
from basalt.core.engine.state_machine import WorkflowState
from basalt.core.executors.pool import WorkerPool
from basalt.core.storage.memory import MemoryStorageEngine
from basalt.core.triggers.base import TriggerEvent
from basalt.core.triggers.dispatcher import TriggerDispatcher
from basalt.core.triggers.webhook import WebhookTrigger
from basalt.storage.database import get_db_manager
from basalt.storage.repository import BasaltRepository
from basalt.utils.crypto import generate_run_id
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class EngineConfig(BaseModel):
    """Configuration options for BasaltEngine initialization."""

    db_url: str = Field(
        default="sqlite+aiosqlite:///basalt.db",
        description="Database connection URL for repository persistence.",
    )
    max_concurrency: int = Field(
        default=10,
        ge=1,
        description="Maximum concurrent step executions in worker pool.",
    )
    use_memory_storage: bool = Field(
        default=False,
        description="Use in-memory storage engine instead of SQLite database.",
    )
    poll_interval_seconds: float = Field(
        default=1.0,
        ge=0.1,
        description="Trigger dispatcher polling loop tick interval.",
    )
    enable_triggers: bool = Field(
        default=True,
        description="Automatically launch background trigger dispatcher.",
    )


class BasaltEngine:
    """Master facade API unifying Basalt workflow engine subsystems."""

    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()
        self.parser = DAGParser()
        self.worker_pool = WorkerPool(max_concurrency=self.config.max_concurrency)
        self.runner = WorkflowRunner(worker_pool=self.worker_pool)
        self.dispatcher = TriggerDispatcher(poll_interval_seconds=self.config.poll_interval_seconds)

        if self.config.use_memory_storage:
            self.memory_storage = MemoryStorageEngine()
            self.repository = None
        else:
            self.memory_storage = None
            db_mgr = get_db_manager(db_url=self.config.db_url)
            self.repository = BasaltRepository(db_manager=db_mgr)

        self._running: bool = False
        self._registered_dags: dict[str, DAGSpec] = {}

    @property
    def is_running(self) -> bool:
        """Check if engine background dispatcher and worker pool are active."""
        return self._running

    async def initialize(self) -> None:
        """Initialize database schema, storage engines, and register trigger event listeners."""
        if self.repository:
            await self.repository.initialize()

        # Wire trigger dispatcher callback to engine workflow execution
        self.dispatcher.add_listener(self._handle_trigger_event)
        logger.info("BasaltEngine subsystems initialized successfully")

    async def start(self) -> None:
        """Start database initialization and trigger dispatcher."""
        if self._running:
            return

        await self.initialize()

        if self.config.enable_triggers:
            await self.dispatcher.start()

        self._running = True
        logger.info("BasaltEngine facade started")

    async def stop(self) -> None:
        """Gracefully stop trigger dispatcher and shutdown worker pool."""
        if not self._running:
            return

        if self.config.enable_triggers:
            await self.dispatcher.stop()

        self.worker_pool.shutdown()
        self._running = False
        logger.info("BasaltEngine facade stopped")

    async def __aenter__(self) -> "BasaltEngine":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()

    # --- DAG Management ---

    async def register_dag(
        self,
        dag_input: str | dict[str, Any] | DAGSpec,
        overwrite: bool = True,
    ) -> DAGSpec:
        """Parse, validate, persist, and register a workflow DAG definition.

        Args:
            dag_input: File path, YAML/JSON string, dict, or DAGSpec AST object.
            overwrite: Whether to overwrite existing stored definition.

        Returns:
            Validated DAGSpec AST object.
        """
        # 1. Parse AST
        if isinstance(dag_input, DAGSpec):
            dag = dag_input
        elif isinstance(dag_input, str) and (
            dag_input.strip().startswith("{") or "steps:" in dag_input
        ):
            dag = self.parser.parse_string(dag_input)
        elif isinstance(dag_input, str):
            dag = await self.parser.parse_file(dag_input)
        elif isinstance(dag_input, dict):
            dag = DAGSpec.model_validate(dag_input)
        else:
            raise ValueError(f"Unsupported DAG input type '{type(dag_input)}'")

        # 2. Validate AST and dependencies
        DAGValidator.validate_dag(dag)
        DAGSorter.get_execution_levels(dag)

        # 3. Store in local registry and database repository
        self._registered_dags[dag.id] = dag

        if self.repository:
            await self.repository.save_dag(dag, overwrite=overwrite)
        elif self.memory_storage:
            self.memory_storage.save_workflow(dag, overwrite=overwrite)

        # 4. Register event triggers with dispatcher
        if self.config.enable_triggers:
            self.dispatcher.register_dag_triggers(dag)

        logger.info(f"Successfully registered DAG workflow '{dag.id}' ({dag.name})")
        return dag

    async def get_dag(self, dag_id: str) -> DAGSpec | None:
        """Fetch registered DAGSpec by ID from local cache or repository."""
        if dag_id in self._registered_dags:
            return self._registered_dags[dag_id]

        if self.repository:
            dag = await self.repository.get_dag(dag_id)
            if dag:
                self._registered_dags[dag.id] = dag
            return dag
        elif self.memory_storage:
            try:
                dag = self.memory_storage.load_workflow(dag_id)
                self._registered_dags[dag.id] = dag
                return dag
            except Exception:
                return None

        return None

    async def list_dags(self, tag: str | None = None) -> list[DAGSpec]:
        """List registered workflow DAG definitions."""
        if self.repository:
            return await self.repository.list_dags(tag=tag)
        elif self.memory_storage:
            return self.memory_storage.list_workflows(tag=tag)

        dags = list(self._registered_dags.values())
        if tag:
            dags = [d for d in dags if tag in d.tags]
        return dags

    async def delete_dag(self, dag_id: str) -> bool:
        """Delete workflow DAG and clean up registered triggers."""
        if dag_id in self._registered_dags:
            del self._registered_dags[dag_id]

        # Unregister triggers
        triggers = self.dispatcher.list_triggers(dag_id=dag_id)
        for trig in triggers:
            self.dispatcher.unregister_trigger(trig.spec.id)

        if self.repository:
            return await self.repository.delete_dag(dag_id)
        elif self.memory_storage:
            return self.memory_storage.delete_workflow(dag_id)

        return True

    # --- Workflow Execution ---

    async def run_dag(
        self,
        dag_id_or_spec: str | DAGSpec,
        inputs: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> WorkflowRunResult:
        """Execute a workflow DAG and record run result ledger in repository.

        Args:
            dag_id_or_spec: Registered DAG ID or DAGSpec object.
            inputs: Runtime execution input parameter values.
            run_id: Optional custom run identifier.

        Returns:
            WorkflowRunResult status object.
        """
        if isinstance(dag_id_or_spec, str):
            dag = await self.get_dag(dag_id_or_spec)
            if dag is None:
                raise BasaltError(
                    message=f"DAG '{dag_id_or_spec}' is not registered.",
                    code="DAG_NOT_FOUND",
                )
        else:
            dag = dag_id_or_spec

        active_run_id = run_id or generate_run_id()
        logger.info(f"Submitting execution for DAG '{dag.id}' (run_id='{active_run_id}')")

        # Create pending run record in database
        if self.repository:
            await self.repository.create_run(dag_id=dag.id, run_id=active_run_id, inputs=inputs)

        # Run DAG through WorkflowRunner
        result = await self.runner.run_async(dag=dag, inputs=inputs, run_id=active_run_id)

        # Save run result snapshot
        if self.repository:
            await self.repository.save_run_result(result)
        elif self.memory_storage:
            self.memory_storage.save_run_result(result)

        logger.info(
            f"Completed DAG '{dag.id}' run '{active_run_id}' with state '{result.state.value}'"
        )
        return result

    async def get_run_result(self, run_id: str) -> WorkflowRunResult | None:
        """Fetch execution run result log by run ID."""
        if self.repository:
            return await self.repository.get_run(run_id)
        elif self.memory_storage:
            try:
                return self.memory_storage.load_run_result(run_id)
            except Exception:
                return None
        return None

    async def list_run_results(
        self,
        dag_id: str | None = None,
        state: WorkflowState | None = None,
    ) -> list[WorkflowRunResult]:
        """List execution run log results."""
        if self.repository:
            return await self.repository.list_runs(dag_id=dag_id, state=state)
        elif self.memory_storage:
            return self.memory_storage.list_run_results(dag_id=dag_id, state=state)
        return []

    # --- Trigger Event Handlers ---

    async def _handle_trigger_event(self, event: TriggerEvent) -> None:
        """Internal callback listener invoked when a TriggerEvent is dispatched."""
        logger.info(
            f"BasaltEngine processing TriggerEvent '{event.event_id}' for DAG '{event.dag_id}'"
        )
        try:
            await self.run_dag(dag_id_or_spec=event.dag_id, inputs=event.payload)
        except Exception as e:
            logger.error(
                f"Failed to execute DAG '{event.dag_id}' for TriggerEvent '{event.event_id}': {e}",
                exc_info=True,
            )

    async def process_webhook_event(
        self,
        trigger_id: str,
        raw_body: bytes,
        headers: dict[str, str],
        payload_dict: dict[str, Any] | None = None,
    ) -> WorkflowRunResult:
        """Process incoming HTTP webhook POST call and run target DAG workflow immediately.

        Args:
            trigger_id: Identifier of registered WebhookTrigger.
            raw_body: Raw request body byte string.
            headers: HTTP request header dictionary.
            payload_dict: Parsed request JSON body dictionary.

        Returns:
            WorkflowRunResult of initiated workflow run.
        """
        trig = self.dispatcher.get_trigger(trigger_id)
        if not isinstance(trig, WebhookTrigger):
            raise BasaltError(
                message=f"WebhookTrigger '{trigger_id}' is not registered.",
                code="WEBHOOK_NOT_FOUND",
            )

        event = trig.process_webhook(raw_body=raw_body, headers=headers, payload_dict=payload_dict)
        return await self.run_dag(dag_id_or_spec=event.dag_id, inputs=event.payload)


_engine_singleton: BasaltEngine | None = None


def get_engine(config: EngineConfig | None = None) -> BasaltEngine:
    """Retrieve process-wide BasaltEngine singleton instance."""
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = BasaltEngine(config=config)
    return _engine_singleton


def set_engine(engine: BasaltEngine | None) -> None:
    """Set or reset process-wide BasaltEngine singleton instance."""
    global _engine_singleton
    _engine_singleton = engine
