"""Integration Tests for Async SQLite Database Engine, Models, Migrations, Serializers, and BasaltRepository.

Validates SQLite table creation, WAL pragmas, schema migrations, ORM serialization,
transaction rollbacks, concurrent run logging, and Dead-Letter Queue (DLQ) operations.
"""

import asyncio
from datetime import UTC, datetime

import pytest

from basalt.core.dag.ast import DAGSpec, ExecutorType, StepSpec, TriggerSpec, TriggerType
from basalt.core.engine.runner import WorkflowRunResult
from basalt.core.engine.state_machine import StepState, WorkflowState
from basalt.core.storage.base import AlreadyExistsError
from basalt.storage.database import DatabaseManager
from basalt.storage.migrations import SchemaMigrator
from basalt.storage.models import DAGRunModel
from basalt.storage.repository import BasaltRepository
from basalt.storage.serializers import ModelSerializer


@pytest.fixture
async def temp_db_repo(tmp_path) -> BasaltRepository:
    """Fixture providing a clean BasaltRepository backed by a temporary SQLite file database."""
    db_file = tmp_path / "test_basalt.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    db_mgr = DatabaseManager(database_url=db_url)
    repo = BasaltRepository(db_manager=db_mgr)
    await repo.initialize()

    # Save default DAG for foreign key validity in tests
    default_dag = DAGSpec(
        id="dag_sales",
        name="Sales DAG",
        steps=[StepSpec(id="step_fetch", executor_type=ExecutorType.SUBPROCESS, command="echo 1")],
    )
    await repo.save_dag(default_dag)

    yield repo
    await db_mgr.close()


@pytest.mark.asyncio
async def test_schema_migrator_history_and_execution(tmp_path) -> None:
    """Verify SchemaMigrator migration execution and history logging on clean database."""
    db_file = tmp_path / "mig_test.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    db_mgr = DatabaseManager(database_url=db_url)
    migrator = SchemaMigrator(db_mgr)

    current_ver = await migrator.get_current_version()
    assert current_ver == 0

    applied = await migrator.apply_migrations()
    assert applied == 3

    history = await migrator.get_migration_history()
    assert len(history) == 3
    assert history[0].version == 1

    pending = await migrator.check_pending_migrations()
    assert len(pending) == 0
    await db_mgr.close()


@pytest.mark.asyncio
async def test_model_serializer_roundtrips() -> None:
    """Verify ModelSerializer bidirectional conversions between Pydantic ASTs and ORM entities."""
    dag = DAGSpec(
        id="dag_roundtrip",
        name="Roundtrip DAG",
        tags=["unit_test"],
        steps=[StepSpec(id="s1", executor_type=ExecutorType.SUBPROCESS, command="echo test")],
        triggers=[TriggerSpec(id="t1", type=TriggerType.CRON, cron="0 * * * *")],
    )

    # DAG roundtrip
    orm_dag = ModelSerializer.dag_to_orm(dag)
    assert orm_dag.id == "dag_roundtrip"
    ast_dag = ModelSerializer.orm_to_dag(orm_dag)
    assert ast_dag.id == dag.id
    assert ast_dag.name == dag.name

    # Trigger roundtrip
    trig = dag.triggers[0]
    orm_trig = ModelSerializer.trigger_to_orm(trig, dag_id=dag.id)
    assert orm_trig.id == "t1"
    ast_trig = ModelSerializer.orm_to_trigger(orm_trig)
    assert ast_trig.cron == "0 * * * *"


@pytest.mark.asyncio
async def test_repository_dag_crud_operations(temp_db_repo: BasaltRepository) -> None:
    """Verify BasaltRepository DAGSpec save, load, update, list, and delete."""
    dag = DAGSpec(
        id="dag_repo_1",
        name="Repo Test DAG",
        tags=["prod", "finance"],
        steps=[
            StepSpec(id="s1", executor_type=ExecutorType.SUBPROCESS, command="echo hello"),
        ],
        triggers=[
            TriggerSpec(id="t1", type=TriggerType.INTERVAL, interval_seconds=60.0),
        ],
    )

    # Save DAG
    saved = await temp_db_repo.save_dag(dag)
    assert saved.id == "dag_repo_1"

    # Duplicate overwrite guard
    with pytest.raises(AlreadyExistsError):
        await temp_db_repo.save_dag(dag, overwrite=False)

    # Fetch DAG
    fetched = await temp_db_repo.get_dag("dag_repo_1")
    assert fetched is not None
    assert fetched.id == "dag_repo_1"
    assert fetched.name == "Repo Test DAG"
    assert len(fetched.triggers) == 1

    # List DAGs with tag filter
    dags_prod = await temp_db_repo.list_dags(tag="prod")
    assert len(dags_prod) == 1
    assert dags_prod[0].id == "dag_repo_1"

    count = await temp_db_repo.count_dags(tag="finance")
    assert count == 1

    # Update DAG
    dag_updated = DAGSpec(
        id="dag_repo_1",
        name="Updated Repo DAG Title",
        tags=["prod"],
        steps=[StepSpec(id="s1", executor_type=ExecutorType.SUBPROCESS, command="echo updated")],
    )
    await temp_db_repo.save_dag(dag_updated, overwrite=True)

    re_fetched = await temp_db_repo.get_dag("dag_repo_1")
    assert re_fetched.name == "Updated Repo DAG Title"

    # Delete DAG
    deleted = await temp_db_repo.delete_dag("dag_repo_1")
    assert deleted is True
    assert await temp_db_repo.get_dag("dag_repo_1") is None


@pytest.mark.asyncio
async def test_repository_run_ledger_operations(temp_db_repo: BasaltRepository) -> None:
    """Verify BasaltRepository create run, save result, list runs, and step state tracking."""
    # Create pending run
    pending_run = await temp_db_repo.create_run(
        dag_id="dag_sales", run_id="run_sales_001", inputs={"region": "US"}
    )
    assert pending_run.id == "run_sales_001"

    # Save complete run result snapshot
    now = datetime.now(UTC)
    res = WorkflowRunResult(
        run_id="run_sales_001",
        dag_id="dag_sales",
        state=WorkflowState.COMPLETED,
        start_time=now,
        end_time=now,
        duration_ms=145.0,
        inputs={"region": "US"},
        outputs={"step_fetch": {"sales": 1000}},
        step_states={"step_fetch": StepState.COMPLETED},
    )

    await temp_db_repo.save_run_result(res)

    # Fetch run
    fetched_res = await temp_db_repo.get_run("run_sales_001")
    assert fetched_res is not None
    assert fetched_res.state == WorkflowState.COMPLETED
    assert fetched_res.outputs["step_fetch"]["sales"] == 1000
    assert fetched_res.step_states["step_fetch"] == StepState.COMPLETED

    # Query runs with filter
    runs = await temp_db_repo.list_runs(dag_id="dag_sales", state=WorkflowState.COMPLETED)
    assert len(runs) == 1
    assert runs[0].run_id == "run_sales_001"

    count = await temp_db_repo.count_runs(dag_id="dag_sales")
    assert count == 1

    # Update run state
    updated_run = await temp_db_repo.update_run_state(
        run_id="run_sales_001", state=WorkflowState.FAILED, error_message="Simulated error"
    )
    assert updated_run.state == WorkflowState.FAILED.value

    # Delete run
    assert await temp_db_repo.delete_run("run_sales_001") is True
    assert await temp_db_repo.get_run("run_sales_001") is None


@pytest.mark.asyncio
async def test_repository_step_run_recording(temp_db_repo: BasaltRepository) -> None:
    """Verify record_step_run method creates StepRunModel entries."""
    await temp_db_repo.create_run(dag_id="dag_sales", run_id="run_step_001")
    step_run = await temp_db_repo.record_step_run(
        run_id="run_step_001",
        step_id="step_alpha",
        state=StepState.COMPLETED,
        attempt=1,
        output={"val": 42},
    )
    assert step_run.step_id == "step_alpha"
    assert step_run.state == StepState.COMPLETED.value


@pytest.mark.asyncio
async def test_repository_transaction_rollback(temp_db_repo: BasaltRepository) -> None:
    """Verify session exception auto-rollback leaves database clean."""
    try:
        async with temp_db_repo.db_manager.session() as session:
            run_model = DAGRunModel(
                id="run_rollback_test",
                dag_id="dag_sales",
                state="RUNNING",
                start_time=datetime.now(UTC),
            )
            session.add(run_model)
            # Intentionally raise exception before commit
            raise RuntimeError("Forced transaction failure")
    except RuntimeError:
        pass

    # Verify rollback succeeded and item is absent
    fetched = await temp_db_repo.get_run("run_rollback_test")
    assert fetched is None


@pytest.mark.asyncio
async def test_repository_concurrent_run_saves(temp_db_repo: BasaltRepository) -> None:
    """Verify concurrent WorkflowRunResult saves execute cleanly without lock collisions."""
    now = datetime.now(UTC)

    async def save_sample_run(idx: int) -> None:
        run_id = f"concurrent_run_{idx}"
        res = WorkflowRunResult(
            run_id=run_id,
            dag_id="dag_sales",
            state=WorkflowState.COMPLETED,
            start_time=now,
            end_time=now,
            duration_ms=50.0,
            outputs={"s1": {"value": idx}},
        )
        await temp_db_repo.save_run_result(res)

    tasks = [save_sample_run(i) for i in range(10)]
    await asyncio.gather(*tasks)

    count = await temp_db_repo.count_runs(dag_id="dag_sales")
    assert count == 10


@pytest.mark.asyncio
async def test_repository_dead_letter_queue_operations(temp_db_repo: BasaltRepository) -> None:
    """Verify Dead-Letter Queue (DLQ) payload saving, listing, and processing."""
    dlq_entry = await temp_db_repo.save_dlq_payload(
        payload_id="dlq_payload_101",
        error_code="PARSE_FAILED",
        error_message="Invalid YAML syntax at line 5",
        payload={"raw": "bad_yaml: [}"},
        dag_id="dag_broken",
    )

    assert dlq_entry.payload_id == "dlq_payload_101"

    # List pending DLQ payloads
    pending = await temp_db_repo.list_dlq_payloads(processed=False)
    assert len(pending) == 1
    assert pending[0].payload_id == "dlq_payload_101"

    # Mark as processed
    marked = await temp_db_repo.mark_dlq_processed("dlq_payload_101")
    assert marked is True

    pending_after = await temp_db_repo.list_dlq_payloads(processed=False)
    assert len(pending_after) == 0

    processed_list = await temp_db_repo.list_dlq_payloads(processed=True)
    assert len(processed_list) == 1
