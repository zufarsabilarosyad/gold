"""Thread-Safe In-Memory Storage Engine Subsystem Module for Basalt Engine.

Provides an in-memory dictionary-backed storage engine with re-entrant locking (threading.RLock),
deep-copy object isolation, tag filtering, pagination, and run status querying.
"""

import copy
import threading
from functools import lru_cache
from typing import Any

from basalt.core.dag.ast import DAGSpec
from basalt.core.engine.runner import WorkflowRunResult
from basalt.core.engine.state_machine import WorkflowState
from basalt.core.storage.base import AlreadyExistsError, BaseStorageEngine, NotFoundError
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class MemoryStorageEngine(BaseStorageEngine):
    """Thread-safe in-memory dictionary storage engine for workflows and run logs."""

    def __init__(self) -> None:
        super().__init__(engine_name="memory")
        self._lock = threading.RLock()
        self._workflows: dict[str, DAGSpec] = {}
        self._runs: dict[str, WorkflowRunResult] = {}

    # --- DAG Workflow Operations ---

    def has_workflow(self, dag_id: str) -> bool:
        """Check if workflow DAG ID exists in memory storage."""
        with self._lock:
            return dag_id in self._workflows

    def get_workflow_ids(self) -> list[str]:
        """Retrieve list of all stored workflow DAG IDs."""
        with self._lock:
            return list(self._workflows.keys())

    def count_workflows(self, tag: str | None = None) -> int:
        """Count total stored workflow definitions matching optional tag filter."""
        with self._lock:
            if tag is None:
                return len(self._workflows)
            return sum(1 for dag in self._workflows.values() if tag in dag.tags)

    def save_workflow(self, dag: DAGSpec, overwrite: bool = True) -> None:
        """Persist a DAGSpec in memory with deep-copy isolation."""
        with self._lock:
            if not overwrite and dag.id in self._workflows:
                raise AlreadyExistsError(entity_type="Workflow", entity_id=dag.id)

            self._workflows[dag.id] = copy.deepcopy(dag)
            logger.debug(f"MemoryStorage saved workflow '{dag.id}'")

    def load_workflow(self, dag_id: str) -> DAGSpec:
        """Load a DAGSpec from memory by ID."""
        with self._lock:
            if dag_id not in self._workflows:
                raise NotFoundError(entity_type="Workflow", entity_id=dag_id)
            return copy.deepcopy(self._workflows[dag_id])

    def delete_workflow(self, dag_id: str) -> bool:
        """Delete a DAGSpec from memory by ID."""
        with self._lock:
            if dag_id in self._workflows:
                del self._workflows[dag_id]
                logger.debug(f"MemoryStorage deleted workflow '{dag_id}'")
                return True
            return False

    def list_workflows(
        self,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DAGSpec]:
        """List stored DAGSpec definitions with optional tag filter and pagination."""
        with self._lock:
            matching: list[DAGSpec] = []
            for dag in self._workflows.values():
                if tag is None or tag in dag.tags:
                    matching.append(copy.deepcopy(dag))

            # Apply pagination offset and limit
            start = max(0, offset)
            end = start + max(1, limit)
            return matching[start:end]

    # --- Execution Run Logs Operations ---

    def has_run_result(self, run_id: str) -> bool:
        """Check if execution run ID exists in memory storage."""
        with self._lock:
            return run_id in self._runs

    def get_run_ids(self) -> list[str]:
        """Retrieve list of all stored execution run IDs."""
        with self._lock:
            return list(self._runs.keys())

    def count_run_results(
        self,
        dag_id: str | None = None,
        state: WorkflowState | None = None,
    ) -> int:
        """Count total stored run results matching optional filters."""
        with self._lock:
            count = 0
            for res in self._runs.values():
                if dag_id is not None and res.dag_id != dag_id:
                    continue
                if state is not None and res.state != state:
                    continue
                count += 1
            return count

    def save_run_result(self, result: WorkflowRunResult) -> None:
        """Persist a WorkflowRunResult log snapshot in memory."""
        with self._lock:
            self._runs[result.run_id] = copy.deepcopy(result)
            logger.debug(
                f"MemoryStorage saved run result '{result.run_id}' for DAG '{result.dag_id}'"
            )

    def load_run_result(self, run_id: str) -> WorkflowRunResult:
        """Load a WorkflowRunResult from memory by run ID."""
        with self._lock:
            if run_id not in self._runs:
                raise NotFoundError(entity_type="RunResult", entity_id=run_id)
            return copy.deepcopy(self._runs[run_id])

    def delete_run_result(self, run_id: str) -> bool:
        """Delete a WorkflowRunResult log from memory by run ID."""
        with self._lock:
            if run_id in self._runs:
                del self._runs[run_id]
                logger.debug(f"MemoryStorage deleted run result '{run_id}'")
                return True
            return False

    def list_run_results(
        self,
        dag_id: str | None = None,
        state: WorkflowState | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WorkflowRunResult]:
        """Query and list stored run results with optional filters and pagination."""
        with self._lock:
            matching: list[WorkflowRunResult] = []
            for res in self._runs.values():
                if dag_id is not None and res.dag_id != dag_id:
                    continue
                if state is not None and res.state != state:
                    continue
                matching.append(copy.deepcopy(res))

            # Sort by start_time descending (newest first)
            matching.sort(key=lambda r: r.start_time, reverse=True)

            start = max(0, offset)
            end = start + max(1, limit)
            return matching[start:end]

    def get_storage_stats(self) -> dict[str, Any]:
        """Retrieve summary statistics of stored workflows and execution run logs."""
        with self._lock:
            return {
                "engine_name": self.engine_name,
                "total_workflows": len(self._workflows),
                "total_runs": len(self._runs),
            }

    def clear(self) -> None:
        """Clear all stored workflows and run results from memory."""
        with self._lock:
            self._workflows.clear()
            self._runs.clear()
            logger.debug("MemoryStorage cleared all stored data")


@lru_cache(maxsize=1)
def get_memory_storage_engine() -> MemoryStorageEngine:
    """Retrieve global singleton LRU-cached MemoryStorageEngine instance."""
    return MemoryStorageEngine()
