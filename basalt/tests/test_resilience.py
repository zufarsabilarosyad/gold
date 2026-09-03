"""Unit Tests for Storage Engines, Backoff Calculator, and Retry Resilience Subsystems.

Validates memory storage persistence, lock safety, object isolation, backoff delay algorithms,
full/equal jitter bounds, retry loop handling, and retry exhaustion exceptions.
"""

from datetime import UTC, datetime

import pytest

from basalt.core.dag.ast import DAGSpec, ExecutorType, RetryPolicySpec, StepSpec
from basalt.core.engine.runner import WorkflowRunResult
from basalt.core.engine.state_machine import WorkflowState
from basalt.core.resilience.backoff import (
    BackoffCalculator,
    BackoffPolicy,
    BackoffStrategy,
    JitterStrategy,
    compute_backoff_delay,
)
from basalt.core.resilience.retry import (
    RetryExhaustedError,
    RetryHandler,
    retryable,
)
from basalt.core.storage.base import AlreadyExistsError, NotFoundError
from basalt.core.storage.memory import MemoryStorageEngine, get_memory_storage_engine

# --- Storage Engine Tests ---


def test_memory_storage_workflow_crud() -> None:
    """Verify MemoryStorageEngine CRUD operations for DAGSpec workflows."""
    storage = MemoryStorageEngine()

    dag = DAGSpec(
        id="dag_storage_1",
        name="Storage Workflow",
        tags=["prod", "etl"],
        steps=[StepSpec(id="s1", executor_type=ExecutorType.SUBPROCESS, command="echo 1")],
    )

    # Save
    storage.save_workflow(dag)
    assert storage.has_workflow("dag_storage_1")
    assert storage.count_workflows() == 1
    assert storage.count_workflows(tag="prod") == 1
    assert storage.count_workflows(tag="non_existent") == 0

    # Overwrite guard test
    with pytest.raises(AlreadyExistsError):
        storage.save_workflow(dag, overwrite=False)

    # Load with deep-copy verification
    loaded = storage.load_workflow("dag_storage_1")
    assert loaded.id == "dag_storage_1"
    assert loaded is not dag

    # List
    workflows = storage.list_workflows(tag="etl")
    assert len(workflows) == 1
    assert workflows[0].id == "dag_storage_1"

    # Delete
    assert storage.delete_workflow("dag_storage_1") is True
    assert storage.has_workflow("dag_storage_1") is False
    assert storage.delete_workflow("dag_storage_1") is False

    with pytest.raises(NotFoundError):
        storage.load_workflow("dag_storage_1")


def test_memory_storage_run_result_crud() -> None:
    """Verify MemoryStorageEngine CRUD operations for WorkflowRunResult execution logs."""
    storage = MemoryStorageEngine()

    res = WorkflowRunResult(
        run_id="run_storage_100",
        dag_id="dag_alpha",
        state=WorkflowState.COMPLETED,
        start_time=datetime.now(UTC),
        end_time=datetime.now(UTC),
        duration_ms=125.0,
        outputs={"s1": {"result": 42}},
    )

    # Save
    storage.save_run_result(res)
    assert storage.has_run_result("run_storage_100")
    assert storage.count_run_results(dag_id="dag_alpha") == 1
    assert storage.count_run_results(state=WorkflowState.FAILED) == 0

    # Load
    loaded = storage.load_run_result("run_storage_100")
    assert loaded.run_id == "run_storage_100"
    assert loaded.outputs["s1"]["result"] == 42

    # Query list
    results = storage.list_run_results(dag_id="dag_alpha", state=WorkflowState.COMPLETED)
    assert len(results) == 1
    assert results[0].run_id == "run_storage_100"

    # Stats & Clear
    stats = storage.get_storage_stats()
    assert stats["total_runs"] == 1

    storage.clear()
    assert storage.count_run_results() == 0

    # LRU singleton test
    singleton = get_memory_storage_engine()
    assert singleton is not None


# --- Backoff Calculator Tests ---


def test_backoff_constant_and_linear() -> None:
    """Verify Constant and Linear backoff calculation mathematics."""
    # Constant strategy
    d1 = BackoffCalculator.calculate_delay(
        attempt=1,
        initial_delay_seconds=2.0,
        strategy=BackoffStrategy.CONSTANT,
        jitter=JitterStrategy.NONE,
    )
    d3 = BackoffCalculator.calculate_delay(
        attempt=3,
        initial_delay_seconds=2.0,
        strategy=BackoffStrategy.CONSTANT,
        jitter=JitterStrategy.NONE,
    )
    assert d1 == 2.0
    assert d3 == 2.0

    # Linear strategy (factor=2.0 -> base = initial * (1 + (attempt-1)*(factor-1)))
    l1 = BackoffCalculator.calculate_delay(
        attempt=1,
        initial_delay_seconds=1.0,
        backoff_factor=2.0,
        strategy=BackoffStrategy.LINEAR,
        jitter=JitterStrategy.NONE,
    )
    l2 = BackoffCalculator.calculate_delay(
        attempt=2,
        initial_delay_seconds=1.0,
        backoff_factor=2.0,
        strategy=BackoffStrategy.LINEAR,
        jitter=JitterStrategy.NONE,
    )
    assert l1 == 1.0
    assert l2 == 2.0


def test_backoff_exponential_and_max_cap() -> None:
    """Verify Exponential backoff growth and max_delay ceiling cap."""
    e1 = BackoffCalculator.calculate_delay(
        attempt=1,
        initial_delay_seconds=1.0,
        backoff_factor=2.0,
        strategy=BackoffStrategy.EXPONENTIAL,
        jitter=JitterStrategy.NONE,
    )
    e2 = BackoffCalculator.calculate_delay(
        attempt=2,
        initial_delay_seconds=1.0,
        backoff_factor=2.0,
        strategy=BackoffStrategy.EXPONENTIAL,
        jitter=JitterStrategy.NONE,
    )
    e3 = BackoffCalculator.calculate_delay(
        attempt=3,
        initial_delay_seconds=1.0,
        backoff_factor=2.0,
        strategy=BackoffStrategy.EXPONENTIAL,
        jitter=JitterStrategy.NONE,
    )
    assert e1 == 1.0
    assert e2 == 2.0
    assert e3 == 4.0

    # Ceiling max cap test
    e_capped = BackoffCalculator.calculate_delay(
        attempt=10,
        initial_delay_seconds=1.0,
        max_delay_seconds=10.0,
        backoff_factor=2.0,
        strategy=BackoffStrategy.EXPONENTIAL,
        jitter=JitterStrategy.NONE,
    )
    assert e_capped == 10.0


def test_backoff_jitter_strategies() -> None:
    """Verify Full Jitter and Equal Jitter bounds."""
    # Full jitter: 0.0 <= delay <= base_delay (10.0)
    for _ in range(20):
        fj = BackoffCalculator.calculate_delay(
            attempt=1, initial_delay_seconds=10.0, jitter=JitterStrategy.FULL
        )
        assert 0.0 <= fj <= 10.0

    # Equal jitter: 5.0 <= delay <= 10.0
    for _ in range(20):
        ej = BackoffCalculator.calculate_delay(
            attempt=1, initial_delay_seconds=10.0, jitter=JitterStrategy.EQUAL
        )
        assert 5.0 <= ej <= 10.0


def test_backoff_policy_and_sequence() -> None:
    """Verify BackoffPolicy and generate_delay_sequence helper."""
    policy = BackoffPolicy(
        initial_delay_seconds=1.0, backoff_factor=3.0, jitter=JitterStrategy.NONE
    )
    assert policy.calculate_delay(1) == 1.0
    assert policy.calculate_delay(2) == 3.0

    seq = BackoffCalculator.generate_delay_sequence(
        max_retries=3, initial_delay_seconds=1.0, backoff_factor=2.0
    )
    assert seq == [1.0, 2.0, 4.0]

    assert compute_backoff_delay(1, jitter=False) == 1.0


# --- Retry Handler Tests ---


@pytest.mark.asyncio
async def test_retry_handler_success_on_attempt_n() -> None:
    """Verify RetryHandler succeeds after transient initial failure."""
    calls = 0

    async def flaky_task() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ValueError("Transient network error")
        return "success"

    policy = RetryPolicySpec(max_retries=3, initial_delay_seconds=0.01, jitter=False)
    result = await RetryHandler.execute_with_retry(
        flaky_task, retry_policy=policy, step_id="flaky_step"
    )

    assert result == "success"
    assert calls == 3


@pytest.mark.asyncio
async def test_retry_handler_exhaustion_raises_exception() -> None:
    """Verify RetryHandler raises RetryExhaustedError when max_retries is exceeded."""
    calls = 0

    async def doomed_task() -> None:
        nonlocal calls
        calls += 1
        raise KeyError("Persistent key error")

    policy = RetryPolicySpec(max_retries=2, initial_delay_seconds=0.01, jitter=False)

    with pytest.raises(RetryExhaustedError) as exc_info:
        await RetryHandler.execute_with_retry(
            doomed_task, retry_policy=policy, step_id="doomed_step"
        )

    assert exc_info.value.attempts == 3
    assert exc_info.value.step_id == "doomed_step"
    assert isinstance(exc_info.value.last_exception, KeyError)
    assert len(exc_info.value.attempt_history) == 2


@pytest.mark.asyncio
async def test_retry_handler_non_retryable_exception() -> None:
    """Verify non-retryable exception bypasses retry loop immediately."""
    calls = 0

    async def fatal_task() -> None:
        nonlocal calls
        calls += 1
        raise TypeError("Fatal type error")

    policy = RetryPolicySpec(max_retries=5, initial_delay_seconds=0.01)

    # Filter to only retry ValueError
    with pytest.raises(TypeError):
        await RetryHandler.execute_with_retry(
            fatal_task,
            retry_policy=policy,
            step_id="fatal_step",
            retryable_exceptions=(ValueError,),
        )

    assert calls == 1  # No retries executed


@pytest.mark.asyncio
async def test_retryable_decorator() -> None:
    """Verify @retryable decorator on async function."""
    attempts = 0

    @retryable(max_retries=2, initial_delay=0.01)
    async def decorated_fn(val: int) -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("First attempt fail")
        return val * 10

    res = await decorated_fn(5)
    assert res == 50
    assert attempts == 2


def test_sync_retry_handler() -> None:
    """Verify execute_sync_with_retry for synchronous callables."""
    count = 0

    def sync_fn() -> int:
        nonlocal count
        count += 1
        if count == 1:
            raise RuntimeError("Sync fail")
        return 99

    policy = RetryPolicySpec(max_retries=2, initial_delay_seconds=0.01, jitter=False)
    val = RetryHandler.execute_sync_with_retry(sync_fn, retry_policy=policy)
    assert val == 99
    assert count == 2
