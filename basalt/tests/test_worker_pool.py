"""Unit & Integration Tests for WorkerPool, ExecutorFactory, and WorkflowRunner.

Validates concurrency limit enforcement, parallel step execution, executor factory lookup,
metrics snapshots, DAG topological execution, conditional skipping, cancellation, batch execution,
and state machine updates.
"""

import asyncio

import pytest

from basalt.core.dag.ast import DAGSpec, ExecutorType, StepSpec
from basalt.core.engine.context import ExecutionContext
from basalt.core.engine.runner import WorkflowRunner, run_dag_workflow
from basalt.core.engine.state_machine import StepState, WorkflowState
from basalt.core.executors.base import BaseExecutor, ExecutorError
from basalt.core.executors.inline import clear_python_callable_registry, register_python_callable
from basalt.core.executors.pool import (
    ExecutorFactory,
    WorkerPool,
    get_global_executor_factory,
)


class MockDelayExecutor(BaseExecutor):
    """Mock Executor plugin that sleeps for specified duration to test concurrency."""

    def __init__(self) -> None:
        super().__init__(executor_type="mock_delay")
        self.active_count = 0
        self.max_observed = 0

    async def execute(self, step: StepSpec, context: ExecutionContext) -> dict[str, int]:
        self.active_count += 1
        if self.active_count > self.max_observed:
            self.max_observed = self.active_count

        delay = step.parameters.get("delay", 0.05) if step.parameters else 0.05
        await asyncio.sleep(delay)

        self.active_count -= 1
        return {"delayed": True}


# --- ExecutorFactory Tests ---


def test_executor_factory_registration() -> None:
    """Verify registration, lookup, and unregistration of custom executors."""
    factory = ExecutorFactory()
    mock_exec = MockDelayExecutor()

    assert factory.has_executor("subprocess")
    assert factory.has_executor("http")
    assert factory.has_executor("python_inline")

    factory.register("mock_delay", mock_exec)
    assert factory.has_executor("mock_delay")
    assert factory.get_executor("mock_delay") == mock_exec

    factory.unregister("mock_delay")
    assert not factory.has_executor("mock_delay")

    with pytest.raises(ExecutorError):
        factory.get_executor("non_existent")

    global_factory = get_global_executor_factory()
    assert global_factory is not None


# --- WorkerPool Concurrency Tests ---


@pytest.mark.asyncio
async def test_worker_pool_concurrency_limiting() -> None:
    """Verify WorkerPool bounds maximum concurrent steps to max_concurrency."""
    factory = ExecutorFactory()
    mock_exec = MockDelayExecutor()
    factory.register("subprocess", mock_exec)  # Override subprocess with mock delay

    max_concurrent = 2
    pool = WorkerPool(max_concurrency=max_concurrent, factory=factory)
    context = ExecutionContext(run_id="run_pool", dag_id="dag_pool")

    # Create 5 parallel steps
    steps = [
        StepSpec(id=f"step_{i}", executor_type=ExecutorType.SUBPROCESS, command="dummy")
        for i in range(5)
    ]

    results = await pool.execute_steps_parallel(steps, context)

    assert len(results) == 5
    assert mock_exec.max_observed <= max_concurrent

    metrics = pool.get_metrics()
    assert metrics.total_steps_executed == 5
    assert metrics.total_steps_succeeded == 5
    assert metrics.total_steps_failed == 0

    pool.shutdown()


# --- WorkflowRunner Lifecycle & DAG Integration Tests ---


@pytest.mark.asyncio
async def test_workflow_runner_end_to_end_dag() -> None:
    """Verify WorkflowRunner executes multi-level DAG with output dependency propagation."""
    clear_python_callable_registry()

    def step_a() -> dict:
        return {"val": 100}

    def step_b(a_val: int) -> dict:
        return {"result": a_val * 2}

    register_python_callable("func_a", step_a)
    register_python_callable("func_b", step_b)

    dag = DAGSpec(
        id="calc_pipeline",
        version="1.0",
        steps=[
            StepSpec(
                id="fetch_val",
                executor_type=ExecutorType.PYTHON_INLINE,
                callable_name="func_a",
            ),
            StepSpec(
                id="compute_val",
                executor_type=ExecutorType.PYTHON_INLINE,
                callable_name="func_b",
                parameters={"a_val": "${steps.fetch_val.output.val}"},
                depends_on=["fetch_val"],
            ),
        ],
    )

    runner = WorkflowRunner()
    result = await runner.run_async(dag)

    assert result.is_success()
    assert result.state == WorkflowState.COMPLETED
    assert result.step_states["fetch_val"] == StepState.COMPLETED
    assert result.step_states["compute_val"] == StepState.COMPLETED
    assert result.outputs["compute_val"]["result"] == 200


@pytest.mark.asyncio
async def test_workflow_runner_conditional_skipping() -> None:
    """Verify WorkflowRunner skips step when conditional 'when' expression evaluates to False."""
    clear_python_callable_registry()

    def run_primary() -> dict:
        return {"flag": False}

    def run_conditional() -> dict:
        return {"ran": True}

    register_python_callable("primary", run_primary)
    register_python_callable("conditional", run_conditional)

    dag = DAGSpec(
        id="conditional_pipeline",
        version="1.0",
        steps=[
            StepSpec(
                id="step1",
                executor_type=ExecutorType.PYTHON_INLINE,
                callable_name="primary",
            ),
            StepSpec(
                id="step2",
                executor_type=ExecutorType.PYTHON_INLINE,
                callable_name="conditional",
                when="${steps.step1.output.flag} == true",
                depends_on=["step1"],
            ),
        ],
    )

    runner = WorkflowRunner()
    result = await runner.run_async(dag)

    assert result.is_success()
    assert result.step_states["step1"] == StepState.COMPLETED
    assert result.step_states["step2"] == StepState.SKIPPED


@pytest.mark.asyncio
async def test_workflow_runner_fast_fail_on_error() -> None:
    """Verify WorkflowRunner aborts downstream step execution when an upstream step fails."""
    clear_python_callable_registry()

    def fail_fn() -> None:
        raise ValueError("Simulated step failure")

    register_python_callable("fail_task", fail_fn)

    dag = DAGSpec(
        id="failure_pipeline",
        version="1.0",
        steps=[
            StepSpec(
                id="boom",
                executor_type=ExecutorType.PYTHON_INLINE,
                callable_name="fail_task",
            ),
            StepSpec(
                id="downstream",
                executor_type=ExecutorType.SUBPROCESS,
                command="echo 'should not run'",
                depends_on=["boom"],
            ),
        ],
    )

    runner = WorkflowRunner()
    result = await runner.run_async(dag)

    assert result.is_failed()
    assert result.state == WorkflowState.FAILED
    assert result.step_states["boom"] == StepState.FAILED
    assert result.step_states["downstream"] == StepState.SKIPPED


@pytest.mark.asyncio
async def test_workflow_runner_batch_execution() -> None:
    """Verify WorkflowRunner.run_batch_async executes multiple DAGs concurrently."""
    clear_python_callable_registry()

    def task_x() -> dict:
        return {"x": 1}

    register_python_callable("fn_x", task_x)

    dag1 = DAGSpec(
        id="batch_dag_1",
        steps=[StepSpec(id="s1", executor_type=ExecutorType.PYTHON_INLINE, callable_name="fn_x")],
    )
    dag2 = DAGSpec(
        id="batch_dag_2",
        steps=[StepSpec(id="s2", executor_type=ExecutorType.PYTHON_INLINE, callable_name="fn_x")],
    )

    runner = WorkflowRunner()
    batch_results = await runner.run_batch_async([dag1, dag2])

    assert len(batch_results) == 2
    assert batch_results[0].dag_id == "batch_dag_1"
    assert batch_results[1].dag_id == "batch_dag_2"
    assert batch_results[0].is_success()
    assert batch_results[1].is_success()


@pytest.mark.asyncio
async def test_run_dag_workflow_shortcut() -> None:
    """Verify run_dag_workflow helper function."""
    dag = DAGSpec(
        id="shortcut_dag",
        steps=[
            StepSpec(
                id="echo_step", executor_type=ExecutorType.SUBPROCESS, command="echo 'shortcut'"
            )
        ],
    )

    res = await run_dag_workflow(dag)
    assert res.is_success()
    assert "shortcut" in res.outputs["echo_step"]["stdout"]
