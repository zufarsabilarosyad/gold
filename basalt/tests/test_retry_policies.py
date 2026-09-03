"""Behavioral coverage for workflow step retry policies."""

import asyncio
from datetime import UTC, datetime

import pytest

import httpx
from httpx import ASGITransport

from basalt.api.app import create_app
from basalt.core.dag.ast import (
    DAGSpec,
    ExecutorType,
    OnFailureAction,
    RetryPolicySpec,
    StepSpec,
)
from basalt.core.engine.context import ExecutionContext
from basalt.core.engine.engine import BasaltEngine, EngineConfig, set_engine
from basalt.core.engine.hooks import HookRegistry, LifecycleEvent
from basalt.core.engine.runner import WorkflowRunner
from basalt.core.engine.state_machine import StepState, WorkflowState
from basalt.core.executors.inline import (
    clear_python_callable_registry,
    register_python_callable,
)
from basalt.storage.database import DatabaseManager
from basalt.storage.repository import BasaltRepository


@pytest.fixture(autouse=True)
def clean_registry():
    clear_python_callable_registry()
    yield
    clear_python_callable_registry()


def retry_step(name: str, failures: int, calls: list[int]) -> None:
    def callable() -> dict[str, int]:
        calls.append(1)
        if len(calls) <= failures:
            raise RuntimeError("temporary")
        return {"calls": len(calls)}

    register_python_callable(name, callable)


def retry_spec(name: str, max_retries: int = 2, jitter: bool = False) -> StepSpec:
    return StepSpec(
        id="work",
        executor_type=ExecutorType.PYTHON_INLINE,
        callable_name=name,
        on_failure=OnFailureAction.RETRY,
        retry_policy=RetryPolicySpec(
            max_retries=max_retries,
            initial_delay_seconds=0.001,
            max_delay_seconds=0.001,
            backoff_factor=2.0,
            jitter=jitter,
        ),
    )


@pytest.mark.asyncio
async def test_retry_recovers_and_exposes_attempt_count():
    calls: list[int] = []
    retry_step("recover", 1, calls)
    result = await WorkflowRunner().run_async(
        DAGSpec(id="recover", version="1", steps=[retry_spec("recover")])
    )
    assert result.state == WorkflowState.COMPLETED
    assert result.step_states["work"] == StepState.COMPLETED
    assert result.step_attempts["work"] == 2
    assert result.outputs["work"] == {"calls": 2}


@pytest.mark.asyncio
async def test_retry_exhaustion_is_terminal_failure():
    calls: list[int] = []
    retry_step("exhaust", 4, calls)
    result = await WorkflowRunner().run_async(
        DAGSpec(id="exhaust", version="1", steps=[retry_spec("exhaust", 2)])
    )
    assert result.state == WorkflowState.FAILED
    assert result.step_states["work"] == StepState.FAILED
    assert result.step_attempts["work"] == 3
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_retry_hook_receives_each_recoverable_failure():
    calls: list[int] = []
    events: list[dict] = []
    retry_step("hooks", 2, calls)
    hooks = HookRegistry()

    async def record(_, __, payload):
        events.append(payload)

    hooks.register(LifecycleEvent.STEP_RETRY, record)
    result = await WorkflowRunner(hook_registry=hooks).run_async(
        DAGSpec(id="hooks", version="1", steps=[retry_spec("hooks")])
    )
    assert result.is_success()
    assert [event["attempt"] for event in events] == [1, 2]
    assert all(event["delay_seconds"] == 0.001 for event in events)
    assert all("error" in event and "temporary" in str(event["error"]) for event in events)


@pytest.mark.asyncio
async def test_step_failure_hook_payload_on_terminal_exhaustion():
    calls: list[int] = []
    failure_payloads: list[dict] = []
    retry_step("exhaust_hook_step", 5, calls)
    hooks = HookRegistry()

    async def record_failure(_, __, payload):
        failure_payloads.append(payload)

    hooks.register(LifecycleEvent.STEP_FAILURE, record_failure)
    result = await WorkflowRunner(hook_registry=hooks).run_async(
        DAGSpec(id="exhaust_dag", steps=[retry_spec("exhaust_hook_step", max_retries=2)])
    )
    assert result.state == WorkflowState.FAILED
    assert len(failure_payloads) == 1
    fail_ev = failure_payloads[0]
    assert fail_ev["step_id"] == "work"
    assert fail_ev["attempt"] == 3
    assert "error" in fail_ev and "temporary" in str(fail_ev["error"])



@pytest.mark.asyncio
async def test_fail_fast_does_not_retry_even_with_a_policy():
    calls: list[int] = []
    retry_step("fast", 1, calls)
    step = retry_spec("fast", 3)
    step.on_failure = OnFailureAction.FAIL_FAST
    result = await WorkflowRunner().run_async(
        DAGSpec(id="fast", version="1", steps=[step])
    )
    assert result.state == WorkflowState.FAILED
    assert result.step_attempts["work"] == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_cancellation_during_retry_wait_prevents_next_attempt():
    calls: list[int] = []
    retry_step("cancel", 10, calls)
    spec = retry_spec("cancel", 4)
    spec.retry_policy.initial_delay_seconds = 1.0
    spec.retry_policy.max_delay_seconds = 1.0
    runner = WorkflowRunner()
    task = asyncio.create_task(
        runner.run_async(DAGSpec(id="cancel", version="1", steps=[spec]), run_id="cancel-run")
    )
    for _ in range(100):
        if runner.is_run_active("cancel-run") and calls:
            break
        await asyncio.sleep(0.001)
    assert runner.cancel_run("cancel-run")
    result = await task
    assert result.state == WorkflowState.CANCELLED
    assert result.step_attempts["work"] == 1


@pytest.mark.asyncio
async def test_deterministic_backoff_without_jitter():
    calls: list[int] = []
    events: list[dict] = []
    retry_step("deterministic", 3, calls)
    spec = StepSpec(
        id="det_step",
        executor_type=ExecutorType.PYTHON_INLINE,
        callable_name="deterministic",
        on_failure=OnFailureAction.RETRY,
        retry_policy=RetryPolicySpec(
            max_retries=3,
            initial_delay_seconds=0.005,
            backoff_factor=2.0,
            jitter=False,
        ),
    )
    hooks = HookRegistry()

    async def on_retry(_, __, payload):
        events.append(payload)

    hooks.register(LifecycleEvent.STEP_RETRY, on_retry)
    result = await WorkflowRunner(hook_registry=hooks).run_async(
        DAGSpec(id="det_dag", steps=[spec])
    )
    assert result.is_success()
    delays = [round(e["delay_seconds"], 5) for e in events]
    assert delays == [0.005, 0.01, 0.02]


@pytest.mark.asyncio
async def test_retry_lifecycle_hooks_complete_sequence():
    calls: list[int] = []
    lifecycle_history: list[tuple[str, int]] = []
    retry_step("lifecycle", 1, calls)
    hooks = HookRegistry()

    async def on_start(_, __, payload):
        lifecycle_history.append(("START", payload.get("attempt", 1)))

    async def on_retry(_, __, payload):
        lifecycle_history.append(("RETRY", payload.get("attempt", 1)))

    async def on_success(_, __, payload):
        lifecycle_history.append(("SUCCESS", payload.get("attempt", 1)))

    hooks.register(LifecycleEvent.STEP_START, on_start)
    hooks.register(LifecycleEvent.STEP_RETRY, on_retry)
    hooks.register(LifecycleEvent.STEP_SUCCESS, on_success)

    result = await WorkflowRunner(hook_registry=hooks).run_async(
        DAGSpec(id="life_dag", steps=[retry_spec("lifecycle", max_retries=2)])
    )
    assert result.is_success()
    assert lifecycle_history == [
        ("START", 1),
        ("RETRY", 1),
        ("START", 2),
        ("SUCCESS", 2),
    ]


@pytest.mark.asyncio
async def test_retry_with_multiple_failing_steps_in_same_level():
    calls_a: list[int] = []
    calls_b: list[int] = []
    retry_step("step_a_fn", 1, calls_a)
    retry_step("step_b_fn", 2, calls_b)

    step_a = StepSpec(
        id="step_a",
        executor_type=ExecutorType.PYTHON_INLINE,
        callable_name="step_a_fn",
        on_failure=OnFailureAction.RETRY,
        retry_policy=RetryPolicySpec(max_retries=2, initial_delay_seconds=0.001, jitter=False),
    )
    step_b = StepSpec(
        id="step_b",
        executor_type=ExecutorType.PYTHON_INLINE,
        callable_name="step_b_fn",
        on_failure=OnFailureAction.RETRY,
        retry_policy=RetryPolicySpec(max_retries=3, initial_delay_seconds=0.001, jitter=False),
    )

    dag = DAGSpec(id="multi_retry_dag", steps=[step_a, step_b])
    result = await WorkflowRunner().run_async(dag)

    assert result.state == WorkflowState.COMPLETED
    assert result.step_states["step_a"] == StepState.COMPLETED
    assert result.step_states["step_b"] == StepState.COMPLETED
    assert result.step_attempts["step_a"] == 2
    assert result.step_attempts["step_b"] == 3


@pytest.mark.asyncio
async def test_cancellation_during_executor_execution_prevents_retry():
    calls: list[int] = []

    def slow_callable():
        calls.append(1)
        import time
        time.sleep(0.3)
        raise RuntimeError("failed after delay")

    register_python_callable("slow_step_fn", slow_callable)

    step = StepSpec(
        id="slow_step",
        executor_type=ExecutorType.PYTHON_INLINE,
        callable_name="slow_step_fn",
        on_failure=OnFailureAction.RETRY,
        retry_policy=RetryPolicySpec(max_retries=3, initial_delay_seconds=0.01),
    )

    runner = WorkflowRunner()
    run_task = asyncio.create_task(
        runner.run_async(DAGSpec(id="cancel_exec_dag", steps=[step]), run_id="cancel_exec_run")
    )
    for _ in range(100):
        if runner.is_run_active("cancel_exec_run") and calls:
            break
        await asyncio.sleep(0.001)

    assert runner.cancel_run("cancel_exec_run")
    res = await run_task

    assert res.state == WorkflowState.CANCELLED
    assert res.step_attempts["slow_step"] == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_retry_step_persistence_in_sqlite(tmp_path):
    db_file = tmp_path / "test_retry_persist.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    db_mgr = DatabaseManager(database_url=db_url)
    repo = BasaltRepository(db_manager=db_mgr)
    await repo.initialize()

    calls: list[int] = []
    retry_step("persist_fn", 2, calls)

    dag = DAGSpec(
        id="dag_persist",
        steps=[
            StepSpec(
                id="persist_step",
                executor_type=ExecutorType.PYTHON_INLINE,
                callable_name="persist_fn",
                on_failure=OnFailureAction.RETRY,
                retry_policy=RetryPolicySpec(max_retries=3, initial_delay_seconds=0.001),
            )
        ],
    )
    await repo.save_dag(dag)

    result = await WorkflowRunner().run_async(dag)
    assert result.state == WorkflowState.COMPLETED
    assert result.step_attempts["persist_step"] == 3

    await repo.save_run_result(result)
    persisted = await repo.get_run(result.run_id)

    assert persisted is not None
    assert persisted.state == WorkflowState.COMPLETED
    assert persisted.step_attempts["persist_step"] == 3
    await db_mgr.close()


@pytest.mark.asyncio
async def test_retry_attempt_surfaced_in_api_responses(tmp_path):
    calls: list[int] = []
    retry_step("api_step_fn", 1, calls)

    db_file = tmp_path / "api_retry_test.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    engine = BasaltEngine(config=EngineConfig(db_url=db_url, use_memory_storage=False, enable_triggers=False))
    set_engine(engine)
    await engine.start()

    app = create_app()

    dag = DAGSpec(
        id="api_dag",
        steps=[
            StepSpec(
                id="step_api",
                executor_type=ExecutorType.PYTHON_INLINE,
                callable_name="api_step_fn",
                on_failure=OnFailureAction.RETRY,
                retry_policy=RetryPolicySpec(max_retries=2, initial_delay_seconds=0.001),
            )
        ],
    )

    await engine.register_dag(dag)
    result = await engine.run_dag("api_dag")

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.get(f"/api/v1/runs/{result.run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "COMPLETED"
        step_runs = {sr["step_id"]: sr for sr in data["step_runs"]}
        assert "step_api" in step_runs
        assert step_runs["step_api"]["attempt"] == 2
        assert step_runs["step_api"]["state"] == "COMPLETED"

        resp_step = await client.get(f"/api/v1/runs/{result.run_id}/steps/step_api")
        assert resp_step.status_code == 200
        step_data = resp_step.json()
        assert step_data["attempt"] == 2

    await engine.stop()
    set_engine(None)




@pytest.mark.asyncio
async def test_retry_recovery_enables_dependent_downstream_step():
    calls: list[int] = []
    retry_step("parent_fn", 1, calls)

    def child_fn(parent_val: int) -> dict[str, int]:
        return {"multiplied": parent_val * 10}

    register_python_callable("child_fn", child_fn)

    parent_step = StepSpec(
        id="parent",
        executor_type=ExecutorType.PYTHON_INLINE,
        callable_name="parent_fn",
        on_failure=OnFailureAction.RETRY,
        retry_policy=RetryPolicySpec(max_retries=2, initial_delay_seconds=0.001),
    )
    child_step = StepSpec(
        id="child",
        executor_type=ExecutorType.PYTHON_INLINE,
        callable_name="child_fn",
        parameters={"parent_val": "${steps.parent.output.calls}"},
        depends_on=["parent"],
    )

    dag = DAGSpec(id="dep_dag", steps=[parent_step, child_step])
    result = await WorkflowRunner().run_async(dag)

    assert result.state == WorkflowState.COMPLETED
    assert result.step_states["parent"] == StepState.COMPLETED
    assert result.step_states["child"] == StepState.COMPLETED
    assert result.step_attempts["parent"] == 2
    assert result.step_attempts["child"] == 1
    assert result.outputs["child"]["multiplied"] == 20


def test_cli_attempt_count_rendering(tmp_path):
    import json
    from click.testing import CliRunner
    from basalt.cli.main import cli

    db_file = tmp_path / "cli_retry_test.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    calls: list[int] = []
    retry_step("cli_step_fn", 2, calls)

    dag_file = tmp_path / "cli_retry_dag.yaml"
    dag_file.write_text("""
id: cli_retry_dag
steps:
  - id: retry_cli_step
    executor_type: python_inline
    callable_name: cli_step_fn
    on_failure: retry
    retry_policy:
      max_retries: 3
      initial_delay_seconds: 0.001
""")

    runner = CliRunner()
    res_start = runner.invoke(
        cli, ["run", "start", str(dag_file), "--run-id", "cli_test_run", "--db-url", db_url]
    )
    assert res_start.exit_code == 0

    # 1. Verify status table renders 'Attempts' column and attempt count '3'
    res_status = runner.invoke(cli, ["run", "status", "cli_test_run", "--db-url", db_url])
    assert res_status.exit_code == 0
    assert "Attempts" in res_status.output
    assert "3" in res_status.output

    # 2. Verify step detail returns attempt '3'
    res_step = runner.invoke(
        cli, ["run", "step", "cli_test_run", "retry_cli_step", "--db-url", db_url]
    )
    assert res_step.exit_code == 0
    step_details = json.loads(res_step.output)
    assert step_details["attempt"] == 3

