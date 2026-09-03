"""Workflow and Step Lifecycle State Machine Module for Basalt Workflow Engine.

Defines state enums, valid transition rules, transition validators, terminal state checks,
and state aggregation logic for workflow runs and individual task steps.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel

from basalt.core.dag.exceptions import BasaltError
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class WorkflowState(str, Enum):
    """Lifecycle states for a complete DAG Workflow run."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


class StepState(str, Enum):
    """Lifecycle states for an individual task step within a workflow."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


class InvalidStateTransitionError(BasaltError):
    """Raised when an illegal state transition is attempted."""

    def __init__(
        self,
        entity_type: str,
        entity_id: str,
        current_state: str,
        target_state: str,
        allowed_states: set[str],
    ) -> None:
        message = (
            f"Invalid {entity_type} state transition for '{entity_id}': "
            f"cannot transition from '{current_state}' to '{target_state}'. "
            f"Allowed transitions from '{current_state}': {sorted(list(allowed_states))}."
        )
        super().__init__(
            message=message,
            code="INVALID_STATE_TRANSITION",
            details={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "current_state": current_state,
                "target_state": target_state,
                "allowed_states": sorted(list(allowed_states)),
            },
        )
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.current_state = current_state
        self.target_state = target_state
        self.allowed_states = allowed_states


class StepExecutionRecord(BaseModel):
    """Snapshot record tracking step execution state history."""

    step_id: str
    state: StepState = StepState.PENDING
    attempt: int = 1
    max_retries: int = 3
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_ms: float = 0.0
    error_message: str | None = None
    output_data: dict[str, Any] | None = None

    def mark_running(self) -> None:
        """Mark step as RUNNING with current timestamp."""
        self.state = StepState.RUNNING
        self.start_time = datetime.now(UTC)

    def mark_completed(self, output: dict[str, Any] | None = None) -> None:
        """Mark step as COMPLETED."""
        self.state = StepState.COMPLETED
        self.end_time = datetime.now(UTC)
        self.output_data = output or {}
        if self.start_time and self.end_time:
            self.duration_ms = (self.end_time - self.start_time).total_seconds() * 1000.0

    def mark_failed(self, error: str) -> None:
        """Mark step as FAILED."""
        self.state = StepState.FAILED
        self.end_time = datetime.now(UTC)
        self.error_message = error
        if self.start_time and self.end_time:
            self.duration_ms = (self.end_time - self.start_time).total_seconds() * 1000.0

    def mark_retrying(self, error: str, delay_seconds: float = 0.0) -> None:
        """Mark step as RETRYING after a recoverable execution failure."""
        self.state = StepState.RETRYING
        self.error_message = error

    def mark_cancelled(self) -> None:
        """Mark step as CANCELLED when execution or retry wait is aborted."""
        self.state = StepState.CANCELLED
        self.end_time = datetime.now(UTC)
        if self.start_time and self.end_time:
            self.duration_ms = (self.end_time - self.start_time).total_seconds() * 1000.0



class StateMachine:
    """State machine governing transition rules for Workflows and Steps."""

    # Valid transitions map for WorkflowState
    WORKFLOW_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
        WorkflowState.PENDING: {
            WorkflowState.RUNNING,
            WorkflowState.CANCELLED,
        },
        WorkflowState.RUNNING: {
            WorkflowState.COMPLETED,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
            WorkflowState.TIMEOUT,
        },
        WorkflowState.COMPLETED: set(),  # Terminal
        WorkflowState.FAILED: set(),  # Terminal
        WorkflowState.CANCELLED: set(),  # Terminal
        WorkflowState.TIMEOUT: set(),  # Terminal
    }

    # Valid transitions map for StepState
    STEP_TRANSITIONS: dict[StepState, set[StepState]] = {
        StepState.PENDING: {
            StepState.RUNNING,
            StepState.SKIPPED,
            StepState.CANCELLED,
        },
        StepState.RUNNING: {
            StepState.COMPLETED,
            StepState.FAILED,
            StepState.RETRYING,
            StepState.SKIPPED,
            StepState.CANCELLED,
            StepState.TIMEOUT,
        },
        StepState.RETRYING: {
            StepState.RUNNING,
            StepState.FAILED,
            StepState.CANCELLED,
        },
        StepState.COMPLETED: set(),  # Terminal
        StepState.FAILED: set(),  # Terminal
        StepState.SKIPPED: set(),  # Terminal
        StepState.CANCELLED: set(),  # Terminal
        StepState.TIMEOUT: set(),  # Terminal
    }

    # Terminal state sets
    TERMINAL_WORKFLOW_STATES: set[WorkflowState] = {
        WorkflowState.COMPLETED,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
        WorkflowState.TIMEOUT,
    }

    TERMINAL_STEP_STATES: set[StepState] = {
        StepState.COMPLETED,
        StepState.FAILED,
        StepState.SKIPPED,
        StepState.CANCELLED,
        StepState.TIMEOUT,
    }

    @classmethod
    def transition_workflow(
        cls,
        run_id: str,
        current_state: WorkflowState,
        target_state: WorkflowState,
    ) -> WorkflowState:
        """Validate and execute a WorkflowState transition.

        Args:
            run_id: Workflow run identifier.
            current_state: Active workflow state.
            target_state: Target workflow state.

        Returns:
            New WorkflowState if transition is legal.

        Raises:
            InvalidStateTransitionError: If transition is illegal.
        """
        if current_state == target_state:
            return current_state

        allowed_targets = cls.WORKFLOW_TRANSITIONS.get(current_state, set())
        if target_state not in allowed_targets:
            allowed_names = {s.value for s in allowed_targets}
            raise InvalidStateTransitionError(
                entity_type="Workflow",
                entity_id=run_id,
                current_state=current_state.value,
                target_state=target_state.value,
                allowed_states=allowed_names,
            )

        logger.debug(
            f"Workflow run '{run_id}' transitioned: {current_state.value} -> {target_state.value}"
        )
        return target_state

    @classmethod
    def transition_step(
        cls,
        step_id: str,
        current_state: StepState,
        target_state: StepState,
    ) -> StepState:
        """Validate and execute a StepState transition.

        Args:
            step_id: Task step identifier.
            current_state: Active step state.
            target_state: Target step state.

        Returns:
            New StepState if transition is legal.

        Raises:
            InvalidStateTransitionError: If transition is illegal.
        """
        if current_state == target_state:
            return current_state

        allowed_targets = cls.STEP_TRANSITIONS.get(current_state, set())
        if target_state not in allowed_targets:
            allowed_names = {s.value for s in allowed_targets}
            raise InvalidStateTransitionError(
                entity_type="Step",
                entity_id=step_id,
                current_state=current_state.value,
                target_state=target_state.value,
                allowed_states=allowed_names,
            )

        logger.debug(
            f"Step '{step_id}' transitioned: {current_state.value} -> {target_state.value}"
        )
        return target_state

    @classmethod
    def is_workflow_terminal(cls, state: WorkflowState) -> bool:
        """Check if workflow state is a terminal state."""
        return state in cls.TERMINAL_WORKFLOW_STATES

    @classmethod
    def is_step_terminal(cls, state: StepState) -> bool:
        """Check if step state is a terminal state."""
        return state in cls.TERMINAL_STEP_STATES

    @classmethod
    def can_retry(cls, current_attempt: int, max_retries: int) -> bool:
        """Check if a failed step is eligible for another retry attempt.

        Args:
            current_attempt: 1-indexed current attempt number.
            max_retries: Maximum configured retry limit.

        Returns:
            True if current_attempt <= max_retries.
        """
        return current_attempt <= max_retries

    @classmethod
    def aggregate_workflow_state(
        cls,
        step_states: dict[str, StepState],
    ) -> WorkflowState:
        """Determine overall WorkflowState based on current step states dictionary.

        Args:
            step_states: Dictionary mapping step_id to StepState.

        Returns:
            Aggregated overall WorkflowState.
        """
        if not step_states:
            return WorkflowState.PENDING

        states = set(step_states.values())

        if StepState.RUNNING in states or StepState.RETRYING in states:
            return WorkflowState.RUNNING

        if StepState.FAILED in states:
            return WorkflowState.FAILED

        if StepState.TIMEOUT in states:
            return WorkflowState.TIMEOUT

        if StepState.CANCELLED in states:
            return WorkflowState.CANCELLED

        # All steps are in terminal success/skip states
        non_running_pending = states - {StepState.COMPLETED, StepState.SKIPPED}
        if not non_running_pending:
            return WorkflowState.COMPLETED

        return WorkflowState.RUNNING
