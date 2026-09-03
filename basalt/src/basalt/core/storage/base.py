"""Abstract Base Storage Engine Subsystem Module for Basalt Engine.

Defines the BaseStorageEngine abstract interface, storage exceptions hierarchy,
and query filtering parameters for workflow definitions and execution run logs persistence.
"""

import abc
from typing import Any

from basalt.core.dag.ast import DAGSpec
from basalt.core.dag.exceptions import BasaltError
from basalt.core.engine.runner import WorkflowRunResult
from basalt.core.engine.state_machine import WorkflowState
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class StorageError(BasaltError):
    """Base exception class for storage operations failures."""

    def __init__(
        self,
        message: str,
        operation: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = {"operation": operation}
        if details:
            merged_details.update(details)
        super().__init__(
            message=f"Storage error during '{operation}': {message}",
            code="STORAGE_ERROR",
            details=merged_details,
        )
        self.operation = operation


class NotFoundError(StorageError):
    """Raised when requested entity is not found in storage."""

    def __init__(self, entity_type: str, entity_id: str) -> None:
        super().__init__(
            message=f"{entity_type} with ID '{entity_id}' not found.",
            operation="read",
            details={"entity_type": entity_type, "entity_id": entity_id},
        )
        self.entity_type = entity_type
        self.entity_id = entity_id


class AlreadyExistsError(StorageError):
    """Raised when creating an entity that already exists in storage."""

    def __init__(self, entity_type: str, entity_id: str) -> None:
        super().__init__(
            message=f"{entity_type} with ID '{entity_id}' already exists.",
            operation="create",
            details={"entity_type": entity_type, "entity_id": entity_id},
        )
        self.entity_type = entity_type
        self.entity_id = entity_id


class BaseStorageEngine(abc.ABC):
    """Abstract Base Class defining persistent storage operations interface."""

    def __init__(self, engine_name: str) -> None:
        self.engine_name = engine_name

    # --- DAG Workflow Persistence ---

    @abc.abstractmethod
    def save_workflow(self, dag: DAGSpec, overwrite: bool = True) -> None:
        """Persist or update a DAGSpec workflow definition.

        Args:
            dag: DAGSpec AST object.
            overwrite: Whether to overwrite existing DAG definition.

        Raises:
            AlreadyExistsError: If overwrite is False and DAG exists.
            StorageError: On storage I/O failure.
        """
        pass

    @abc.abstractmethod
    def load_workflow(self, dag_id: str) -> DAGSpec:
        """Load a DAGSpec workflow definition by ID.

        Args:
            dag_id: Workflow identifier.

        Returns:
            Loaded DAGSpec object.

        Raises:
            NotFoundError: If workflow ID is not found.
            StorageError: On storage read failure.
        """
        pass

    @abc.abstractmethod
    def delete_workflow(self, dag_id: str) -> bool:
        """Delete a DAGSpec workflow definition by ID.

        Args:
            dag_id: Workflow identifier.

        Returns:
            True if deleted, False if entity did not exist.
        """
        pass

    @abc.abstractmethod
    def list_workflows(
        self,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DAGSpec]:
        """List stored DAGSpec workflow definitions with optional tag filtering.

        Args:
            tag: Optional tag filter.
            limit: Maximum count to return.
            offset: Offset pagination index.

        Returns:
            List of matching DAGSpec objects.
        """
        pass

    # --- Execution Run Logs Persistence ---

    @abc.abstractmethod
    def save_run_result(self, result: WorkflowRunResult) -> None:
        """Persist a WorkflowRunResult log snapshot.

        Args:
            result: WorkflowRunResult container object.

        Raises:
            StorageError: On storage I/O failure.
        """
        pass

    @abc.abstractmethod
    def load_run_result(self, run_id: str) -> WorkflowRunResult:
        """Load a WorkflowRunResult execution log by run ID.

        Args:
            run_id: Unique workflow run identifier.

        Returns:
            Loaded WorkflowRunResult object.

        Raises:
            NotFoundError: If run ID is not found.
        """
        pass

    @abc.abstractmethod
    def delete_run_result(self, run_id: str) -> bool:
        """Delete a WorkflowRunResult log by run ID.

        Args:
            run_id: Unique workflow run identifier.

        Returns:
            True if deleted, False if entity did not exist.
        """
        pass

    @abc.abstractmethod
    def list_run_results(
        self,
        dag_id: str | None = None,
        state: WorkflowState | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WorkflowRunResult]:
        """Query and list stored execution run logs with optional filters.

        Args:
            dag_id: Optional DAG ID filter.
            state: Optional WorkflowState filter.
            limit: Maximum count to return.
            offset: Offset pagination index.

        Returns:
            List of matching WorkflowRunResult objects.
        """
        pass

    def clear(self) -> None:
        """Clear all stored workflows and run results from storage engine."""
        pass
