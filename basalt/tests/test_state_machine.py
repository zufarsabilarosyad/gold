"""Unit Tests for Workflow and Step Lifecycle State Machine Module.

Validates allowed state transitions, invalid transition error guards, step execution record
tracking, retry boundaries, terminal predicates, matrix coverage, and overall workflow state aggregation.
"""

import pytest

from basalt.core.engine.state_machine import (
    InvalidStateTransitionError,
    StateMachine,
    StepExecutionRecord,
    StepState,
    WorkflowState,
)


def test_workflow_state_valid_transitions() -> None:
    """Verify legal workflow state transitions."""
    # PENDING -> RUNNING -> COMPLETED
    s1 = StateMachine.transition_workflow("run_1", WorkflowState.PENDING, WorkflowState.RUNNING)
    assert s1 == WorkflowState.RUNNING

    s2 = StateMachine.transition_workflow("run_1", WorkflowState.RUNNING, WorkflowState.COMPLETED)
    assert s2 == WorkflowState.COMPLETED

    # PENDING -> CANCELLED
    s3 = StateMachine.transition_workflow("run_2", WorkflowState.PENDING, WorkflowState.CANCELLED)
    assert s3 == WorkflowState.CANCELLED

    # RUNNING -> FAILED
    s4 = StateMachine.transition_workflow("run_3", WorkflowState.RUNNING, WorkflowState.FAILED)
    assert s4 == WorkflowState.FAILED

    # RUNNING -> TIMEOUT
    s5 = StateMachine.transition_workflow("run_4", WorkflowState.RUNNING, WorkflowState.TIMEOUT)
    assert s5 == WorkflowState.TIMEOUT


def test_workflow_state_same_state_idempotent() -> None:
    """Verify transitioning to the same state is idempotent and returns current state."""
    state = StateMachine.transition_workflow("run_1", WorkflowState.RUNNING, WorkflowState.RUNNING)
    assert state == WorkflowState.RUNNING


def test_workflow_state_invalid_transitions() -> None:
    """Verify illegal workflow state transitions raise InvalidStateTransitionError."""
    # Cannot transition COMPLETED -> RUNNING
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        StateMachine.transition_workflow("run_1", WorkflowState.COMPLETED, WorkflowState.RUNNING)
    assert exc_info.value.code == "INVALID_STATE_TRANSITION"
    assert exc_info.value.entity_type == "Workflow"
    assert exc_info.value.current_state == "COMPLETED"
    assert exc_info.value.target_state == "RUNNING"
    assert exc_info.value.details["entity_id"] == "run_1"

    # Cannot transition FAILED -> COMPLETED
    with pytest.raises(InvalidStateTransitionError):
        StateMachine.transition_workflow("run_1", WorkflowState.FAILED, WorkflowState.COMPLETED)

    # Cannot transition CANCELLED -> RUNNING
    with pytest.raises(InvalidStateTransitionError):
        StateMachine.transition_workflow("run_1", WorkflowState.CANCELLED, WorkflowState.RUNNING)


def test_step_state_valid_transitions() -> None:
    """Verify legal step state transitions."""
    # PENDING -> RUNNING -> COMPLETED
    s1 = StateMachine.transition_step("step_a", StepState.PENDING, StepState.RUNNING)
    assert s1 == StepState.RUNNING

    s2 = StateMachine.transition_step("step_a", StepState.RUNNING, StepState.COMPLETED)
    assert s2 == StepState.COMPLETED

    # RUNNING -> RETRYING -> RUNNING -> FAILED
    s3 = StateMachine.transition_step("step_b", StepState.RUNNING, StepState.RETRYING)
    assert s3 == StepState.RETRYING

    s4 = StateMachine.transition_step("step_b", StepState.RETRYING, StepState.RUNNING)
    assert s4 == StepState.RUNNING

    s5 = StateMachine.transition_step("step_b", StepState.RUNNING, StepState.FAILED)
    assert s5 == StepState.FAILED

    # PENDING -> SKIPPED
    s6 = StateMachine.transition_step("step_c", StepState.PENDING, StepState.SKIPPED)
    assert s6 == StepState.SKIPPED

    # RUNNING -> CANCELLED
    s7 = StateMachine.transition_step("step_d", StepState.RUNNING, StepState.CANCELLED)
    assert s7 == StepState.CANCELLED


def test_step_state_invalid_transitions() -> None:
    """Verify illegal step state transitions raise InvalidStateTransitionError."""
    # Cannot transition COMPLETED -> RUNNING
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        StateMachine.transition_step("step_1", StepState.COMPLETED, StepState.RUNNING)
    assert exc_info.value.code == "INVALID_STATE_TRANSITION"
    assert exc_info.value.entity_type == "Step"

    # Cannot transition SKIPPED -> RUNNING
    with pytest.raises(InvalidStateTransitionError):
        StateMachine.transition_step("step_1", StepState.SKIPPED, StepState.RUNNING)

    # Cannot transition FAILED -> RETRYING (must go through RETRYING from RUNNING)
    with pytest.raises(InvalidStateTransitionError):
        StateMachine.transition_step("step_1", StepState.FAILED, StepState.RETRYING)


def test_step_execution_record_tracking() -> None:
    """Verify StepExecutionRecord state updates and duration calculation."""
    record = StepExecutionRecord(step_id="extract_step", max_retries=3)
    assert record.state == StepState.PENDING
    assert record.start_time is None
    assert record.end_time is None

    record.mark_running()
    assert record.state == StepState.RUNNING
    assert record.start_time is not None

    record.mark_completed(output={"rows": 100})
    assert record.state == StepState.COMPLETED
    assert record.end_time is not None
    assert record.output_data == {"rows": 100}
    assert record.duration_ms >= 0.0

    failed_record = StepExecutionRecord(step_id="fail_step")
    failed_record.mark_running()
    failed_record.mark_failed(error="Connection refused")
    assert failed_record.state == StepState.FAILED
    assert failed_record.error_message == "Connection refused"


def test_terminal_state_predicates() -> None:
    """Verify terminal state checkers for workflow and step states."""
    assert StateMachine.is_workflow_terminal(WorkflowState.COMPLETED) is True
    assert StateMachine.is_workflow_terminal(WorkflowState.FAILED) is True
    assert StateMachine.is_workflow_terminal(WorkflowState.CANCELLED) is True
    assert StateMachine.is_workflow_terminal(WorkflowState.TIMEOUT) is True
    assert StateMachine.is_workflow_terminal(WorkflowState.RUNNING) is False
    assert StateMachine.is_workflow_terminal(WorkflowState.PENDING) is False

    assert StateMachine.is_step_terminal(StepState.COMPLETED) is True
    assert StateMachine.is_step_terminal(StepState.FAILED) is True
    assert StateMachine.is_step_terminal(StepState.SKIPPED) is True
    assert StateMachine.is_step_terminal(StepState.CANCELLED) is True
    assert StateMachine.is_step_terminal(StepState.TIMEOUT) is True
    assert StateMachine.is_step_terminal(StepState.RUNNING) is False
    assert StateMachine.is_step_terminal(StepState.RETRYING) is False


def test_can_retry_boundaries() -> None:
    """Verify retry eligibility calculation."""
    assert StateMachine.can_retry(current_attempt=1, max_retries=3) is True
    assert StateMachine.can_retry(current_attempt=3, max_retries=3) is True
    assert StateMachine.can_retry(current_attempt=4, max_retries=3) is False


def test_aggregate_workflow_state() -> None:
    """Verify aggregation of overall workflow state from step states map."""
    # Empty step map -> PENDING
    assert StateMachine.aggregate_workflow_state({}) == WorkflowState.PENDING

    # All completed or skipped -> COMPLETED
    all_success = {
        "step1": StepState.COMPLETED,
        "step2": StepState.SKIPPED,
        "step3": StepState.COMPLETED,
    }
    assert StateMachine.aggregate_workflow_state(all_success) == WorkflowState.COMPLETED

    # Any step running or retrying -> RUNNING
    one_running = {
        "step1": StepState.COMPLETED,
        "step2": StepState.RUNNING,
    }
    assert StateMachine.aggregate_workflow_state(one_running) == WorkflowState.RUNNING

    one_retrying = {
        "step1": StepState.COMPLETED,
        "step2": StepState.RETRYING,
    }
    assert StateMachine.aggregate_workflow_state(one_retrying) == WorkflowState.RUNNING

    # Step failure -> FAILED
    one_failed = {
        "step1": StepState.COMPLETED,
        "step2": StepState.FAILED,
    }
    assert StateMachine.aggregate_workflow_state(one_failed) == WorkflowState.FAILED

    # Step timeout -> TIMEOUT
    one_timeout = {
        "step1": StepState.COMPLETED,
        "step2": StepState.TIMEOUT,
    }
    assert StateMachine.aggregate_workflow_state(one_timeout) == WorkflowState.TIMEOUT

    # Step cancelled -> CANCELLED
    one_cancelled = {
        "step1": StepState.COMPLETED,
        "step2": StepState.CANCELLED,
    }
    assert StateMachine.aggregate_workflow_state(one_cancelled) == WorkflowState.CANCELLED


def test_terminal_states_reject_all_further_transitions() -> None:
    """Verify terminal workflow states reject all further state transitions."""
    terminal_states = [
        WorkflowState.COMPLETED,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
        WorkflowState.TIMEOUT,
    ]
    target_states = list(WorkflowState)

    for term in terminal_states:
        for target in target_states:
            if target != term:
                with pytest.raises(InvalidStateTransitionError):
                    StateMachine.transition_workflow("test_run", term, target)
