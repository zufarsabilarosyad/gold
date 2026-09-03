"""End-to-End Integration Tests for BasaltEngine Facade Subsystem.

Validates DAG parsing, AST validation, database & memory storage backends,
resilient worker pool execution, trigger dispatching, and webhook processing.
"""

import asyncio

import pytest

from basalt.core.dag.ast import DAGSpec, ExecutorType, StepSpec, TriggerSpec, TriggerType
from basalt.core.dag.exceptions import BasaltError
from basalt.core.engine.engine import BasaltEngine, EngineConfig, get_engine
from basalt.core.engine.state_machine import WorkflowState
from basalt.core.triggers.webhook import WebhookSignatureVerifier


@pytest.mark.asyncio
async def test_engine_initialization_memory_mode() -> None:
    """Verify BasaltEngine initialization and lifecycle in in-memory storage mode."""
    config = EngineConfig(use_memory_storage=True, enable_triggers=False)
    async with BasaltEngine(config=config) as engine:
        assert engine.is_running is True
        assert engine.memory_storage is not None
        assert engine.repository is None


@pytest.mark.asyncio
async def test_engine_initialization_sqlite_mode(tmp_path) -> None:
    """Verify BasaltEngine initialization backed by temporary SQLite file database."""
    db_file = tmp_path / "engine_test.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    config = EngineConfig(db_url=db_url, use_memory_storage=False, enable_triggers=False)

    async with BasaltEngine(config=config) as engine:
        assert engine.is_running is True
        assert engine.repository is not None


@pytest.mark.asyncio
async def test_engine_dag_registration_and_query(tmp_path) -> None:
    """Verify DAG registration from YAML string, dictionary, and AST objects."""
    db_file = tmp_path / "engine_dags.db"
    config = EngineConfig(db_url=f"sqlite+aiosqlite:///{db_file}", enable_triggers=False)

    async with BasaltEngine(config=config) as engine:
        # 1. Register from YAML string
        yaml_content = """
id: dag_yaml_test
name: YAML Engine Test
version: "1.0.0"
tags: ["yaml", "test"]
steps:
  - id: step_echo
    executor_type: subprocess
    command: "echo 'hello from yaml'"
"""
        dag_yaml = await engine.register_dag(yaml_content)
        assert dag_yaml.id == "dag_yaml_test"
        assert len(dag_yaml.steps) == 1

        # 2. Register from Dict
        dict_content = {
            "id": "dag_dict_test",
            "name": "Dict Engine Test",
            "tags": ["dict"],
            "steps": [{"id": "s1", "executor_type": "subprocess", "command": "echo dict"}],
        }
        dag_dict = await engine.register_dag(dict_content)
        assert dag_dict.id == "dag_dict_test"

        # 3. Query DAGs
        fetched = await engine.get_dag("dag_yaml_test")
        assert fetched is not None
        assert fetched.name == "YAML Engine Test"

        dags_yaml_tag = await engine.list_dags(tag="yaml")
        assert len(dags_yaml_tag) == 1
        assert dags_yaml_tag[0].id == "dag_yaml_test"

        # 4. Delete DAG
        deleted = await engine.delete_dag("dag_dict_test")
        assert deleted is True
        assert await engine.get_dag("dag_dict_test") is None


@pytest.mark.asyncio
async def test_engine_end_to_end_dag_execution(tmp_path) -> None:
    """Verify end-to-end DAG registration, submission, execution, and ledger persistence."""
    db_file = tmp_path / "engine_exec.db"
    config = EngineConfig(db_url=f"sqlite+aiosqlite:///{db_file}", enable_triggers=False)

    async with BasaltEngine(config=config) as engine:
        dag = DAGSpec(
            id="dag_e2e_exec",
            name="E2E Execution DAG",
            steps=[
                StepSpec(
                    id="step_calc",
                    executor_type=ExecutorType.SUBPROCESS,
                    command="echo '{\"result\": 42}'",
                )
            ],
        )
        await engine.register_dag(dag)

        # Run DAG
        result = await engine.run_dag("dag_e2e_exec", inputs={"x": 21})
        assert result.state == WorkflowState.COMPLETED
        assert result.outputs["step_calc"]["result"] == 42
        assert result.duration_ms > 0

        # Verify run result was persisted in repository
        persisted_run = await engine.get_run_result(result.run_id)
        assert persisted_run is not None
        assert persisted_run.run_id == result.run_id
        assert persisted_run.state == WorkflowState.COMPLETED
        assert persisted_run.outputs["step_calc"]["result"] == 42

        # Query run results list
        runs = await engine.list_run_results(dag_id="dag_e2e_exec", state=WorkflowState.COMPLETED)
        assert len(runs) == 1
        assert runs[0].run_id == result.run_id


@pytest.mark.asyncio
async def test_engine_webhook_event_trigger(tmp_path) -> None:
    """Verify HTTP Webhook ingestion initiating workflow execution."""
    db_file = tmp_path / "engine_wh.db"
    config = EngineConfig(
        db_url=f"sqlite+aiosqlite:///{db_file}",
        enable_triggers=True,
        poll_interval_seconds=0.1,
    )

    secret = "wh_engine_secret_key_456"

    async with BasaltEngine(config=config) as engine:
        dag = DAGSpec(
            id="dag_wh_target",
            name="Webhook Target DAG",
            steps=[
                StepSpec(
                    id="step_wh",
                    executor_type=ExecutorType.SUBPROCESS,
                    command='echo \'{"result": "Hello Alice"}\'',
                )
            ],
            triggers=[
                TriggerSpec(
                    id="trig_wh_1",
                    type=TriggerType.WEBHOOK,
                    webhook_secret=secret,
                )
            ],
        )
        await engine.register_dag(dag)

        # Simulate incoming HTTP webhook POST
        raw_body = b'{"user": "Alice"}'
        sig = WebhookSignatureVerifier.compute_signature(raw_body, secret)
        headers = {"X-Basalt-Signature": f"sha256={sig}", "Content-Type": "application/json"}

        run_res = await engine.process_webhook_event(
            trigger_id="trig_wh_1",
            raw_body=raw_body,
            headers=headers,
            payload_dict={"user": "Alice"},
        )

        assert run_res.state == WorkflowState.COMPLETED
        assert run_res.outputs["step_wh"]["result"] == "Hello Alice"


@pytest.mark.asyncio
async def test_engine_interval_trigger_execution(tmp_path) -> None:
    """Verify background IntervalTrigger firing and triggering workflow execution."""
    db_file = tmp_path / "engine_interval.db"
    config = EngineConfig(
        db_url=f"sqlite+aiosqlite:///{db_file}",
        enable_triggers=True,
        poll_interval_seconds=0.1,
    )

    async with BasaltEngine(config=config) as engine:
        dag = DAGSpec(
            id="dag_interval_test",
            name="Interval Engine DAG",
            steps=[
                StepSpec(
                    id="s1",
                    executor_type=ExecutorType.SUBPROCESS,
                    command="echo 'interval tick'",
                )
            ],
            triggers=[
                TriggerSpec(
                    id="trig_interval_1",
                    type=TriggerType.INTERVAL,
                    interval_seconds=0.1,
                )
            ],
        )
        await engine.register_dag(dag)

        # Sleep to allow background dispatcher to poll interval trigger
        await asyncio.sleep(0.35)

        runs = await engine.list_run_results(dag_id="dag_interval_test")
        assert len(runs) >= 1
        assert runs[0].state == WorkflowState.COMPLETED


@pytest.mark.asyncio
async def test_engine_double_start_and_stop_safety(tmp_path) -> None:
    """Verify calling start() or stop() multiple times is idempotent."""
    db_file = tmp_path / "engine_safety.db"
    config = EngineConfig(db_url=f"sqlite+aiosqlite:///{db_file}", enable_triggers=True)

    engine = BasaltEngine(config=config)
    await engine.start()
    assert engine.is_running is True

    # Idempotent double start
    await engine.start()
    assert engine.is_running is True

    await engine.stop()
    assert engine.is_running is False

    # Idempotent double stop
    await engine.stop()
    assert engine.is_running is False


@pytest.mark.asyncio
async def test_engine_unregistered_dag_error_handling(tmp_path) -> None:
    """Verify BasaltEngine raises BasaltError when attempting to run unregistered DAG."""
    config = EngineConfig(use_memory_storage=True, enable_triggers=False)
    async with BasaltEngine(config=config) as engine:
        with pytest.raises(BasaltError) as exc_info:
            await engine.run_dag("non_existent_dag_id")
        assert exc_info.value.code == "DAG_NOT_FOUND"

        with pytest.raises(ValueError):
            await engine.register_dag(12345)  # Invalid input type


def test_engine_singleton_accessor() -> None:
    """Verify get_engine singleton returns consistent instance."""
    e1 = get_engine()
    e2 = get_engine()
    assert e1 is e2
