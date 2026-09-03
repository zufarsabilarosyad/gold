"""Behavioral coverage for failure actions across workflow branches."""

import asyncio

import pytest

from basalt.core.dag.ast import DAGSpec, ExecutorType, OnFailureAction, StepSpec
from basalt.core.engine.context import ExecutionContext
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


def register_success(name: str, marker: list[str]) -> None:
    def callable() -> dict[str, str]:
        marker.append(name)
        return {"name": name}

    register_python_callable(name, callable)


def register_failure(name: str) -> None:
    def callable() -> dict:
        raise RuntimeError(name)

    register_python_callable(name, callable)


def inline(
    step_id: str,
    callable_name: str,
    depends_on: list[str] | None = None,
    on_failure: OnFailureAction = OnFailureAction.FAIL_FAST,
) -> StepSpec:
    return StepSpec(
        id=step_id,
        executor_type=ExecutorType.PYTHON_INLINE,
        callable_name=callable_name,
        depends_on=depends_on or [],
        on_failure=on_failure,
    )


@pytest.mark.asyncio
async def test_continue_runs_independent_branch_after_failure():
    marker: list[str] = []
    register_failure("bad")
    register_success("root_ok", marker)
    register_success("good", marker)
    bad = inline("bad", "bad", on_failure=OnFailureAction.CONTINUE)
    dag = DAGSpec(
        id="continue",
        version="1",
        steps=[
            inline("root_ok", "root_ok"),
            bad,
            inline("good", "good", depends_on=["root_ok"]),
        ],
    )
    result = await WorkflowRunner().run_async(dag)
    assert result.state == WorkflowState.FAILED
    assert result.step_states["bad"] == StepState.FAILED
    assert result.step_states["good"] == StepState.COMPLETED
    assert result.step_attempts["good"] == 1
    assert "good" in marker


@pytest.mark.asyncio
async def test_continue_skips_direct_dependant_of_failed_step():
    marker: list[str] = []
    register_failure("bad")
    register_success("root_ok", marker)
    register_success("child", marker)
    register_success("worker", marker)
    bad = inline("bad", "bad", on_failure=OnFailureAction.CONTINUE)
    dag = DAGSpec(
        id="child",
        version="1",
        steps=[
            inline("root_ok", "root_ok"),
            bad,
            inline("child", "child", depends_on=["bad"]),
            inline("worker", "worker", depends_on=["root_ok"]),
        ],
    )
    result = await WorkflowRunner().run_async(dag)
    assert result.state == WorkflowState.FAILED
    assert result.step_states["child"] == StepState.SKIPPED
    assert result.step_states["worker"] == StepState.COMPLETED
    assert result.step_attempts["worker"] == 1
    assert "child" not in marker
    assert "worker" in marker


@pytest.mark.asyncio
async def test_continue_skips_transitive_dependants_but_not_other_roots():
    marker: list[str] = []
    register_failure("bad")
    register_success("other_root", marker)
    register_success("middle", marker)
    register_success("leaf", marker)
    register_success("other_worker", marker)
    register_success("other_leaf", marker)

    bad = inline("bad", "bad", on_failure=OnFailureAction.CONTINUE)
    dag = DAGSpec(
        id="tree",
        version="1",
        steps=[
            bad,
            inline("other_root", "other_root"),
            inline("middle", "middle", ["bad"]),
            inline("leaf", "leaf", ["middle"]),
            inline("other_worker", "other_worker", ["other_root"]),
            inline("other_leaf", "other_leaf", ["other_worker"]),
        ],
    )
    result = await WorkflowRunner().run_async(dag)
    assert result.step_states["middle"] == StepState.SKIPPED
    assert result.step_states["leaf"] == StepState.SKIPPED
    assert result.step_states["other_worker"] == StepState.COMPLETED
    assert result.step_states["other_leaf"] == StepState.COMPLETED
    assert result.step_attempts["other_leaf"] == 1
    assert "middle" not in marker
    assert "leaf" not in marker
    assert "other_leaf" in marker


@pytest.mark.asyncio
async def test_default_failure_action_preserves_fast_fail():
    marker: list[str] = []
    register_failure("bad")
    register_success("start", marker)
    register_success("other", marker)
    register_success("later", marker)
    dag = DAGSpec(
        id="fast",
        version="1",
        steps=[
            inline("start", "start"),
            inline("bad", "bad", ["start"]),
            inline("other", "other", ["start"]),
            inline("later", "later", ["other"]),
        ],
    )
    result = await WorkflowRunner().run_async(dag)
    assert result.state == WorkflowState.FAILED
    assert result.step_states["later"] == StepState.SKIPPED
    assert result.step_attempts["start"] == 1
    assert result.step_attempts["bad"] == 1
    assert marker == ["start", "other"]


@pytest.mark.asyncio
async def test_continue_diamond_dag_skips_join_node():
    marker: list[str] = []
    register_success("root", marker)
    register_failure("branch_fail")
    register_success("branch_ok", marker)
    register_success("b2", marker)
    register_success("join_step", marker)

    dag = DAGSpec(
        id="diamond_continue",
        steps=[
            inline("root", "root"),
            inline("branch_fail", "branch_fail", ["root"], on_failure=OnFailureAction.CONTINUE),
            inline("branch_ok", "branch_ok", ["root"]),
            inline("b2", "b2", ["branch_ok"]),
            inline("join_step", "join_step", ["branch_fail", "b2"]),
        ],
    )
    result = await WorkflowRunner().run_async(dag)

    assert result.state == WorkflowState.FAILED
    assert result.step_states["root"] == StepState.COMPLETED
    assert result.step_states["branch_fail"] == StepState.FAILED
    assert result.step_states["branch_ok"] == StepState.COMPLETED
    assert result.step_states["b2"] == StepState.COMPLETED
    assert result.step_states["join_step"] == StepState.SKIPPED
    assert result.step_attempts["b2"] == 1
    assert marker == ["root", "branch_ok", "b2"]


@pytest.mark.asyncio
async def test_continue_workflow_state_is_failed_overall():
    marker: list[str] = []
    register_success("root_node", marker)
    register_failure("failing_branch")
    register_success("worker_1", marker)
    register_success("worker_2", marker)

    dag = DAGSpec(
        id="overall_failed_check",
        steps=[
            inline("root_node", "root_node"),
            inline("failing_branch", "failing_branch", ["root_node"], on_failure=OnFailureAction.CONTINUE),
            inline("worker_1", "worker_1", ["root_node"]),
            inline("worker_2", "worker_2", ["worker_1"]),
        ],
    )
    result = await WorkflowRunner().run_async(dag)

    assert result.state == WorkflowState.FAILED
    assert result.step_states["failing_branch"] == StepState.FAILED
    assert result.step_states["worker_1"] == StepState.COMPLETED
    assert result.step_states["worker_2"] == StepState.COMPLETED
    assert result.step_attempts["worker_2"] == 1
    assert not result.is_success()
    assert result.is_failed()


@pytest.mark.asyncio
async def test_mixed_failure_actions_fail_fast_wins():
    marker: list[str] = []
    register_success("root_seed", marker)
    register_failure("fail_continue")
    register_failure("fail_fast_step")
    register_success("downstream_independent", marker)

    dag = DAGSpec(
        id="mixed_fail_actions",
        steps=[
            inline("root_seed", "root_seed"),
            inline("fail_continue", "fail_continue", ["root_seed"], on_failure=OnFailureAction.CONTINUE),
            inline("fail_fast_step", "fail_fast_step", ["root_seed"], on_failure=OnFailureAction.FAIL_FAST),
            inline("downstream_independent", "downstream_independent", ["root_seed"]),
            inline("downstream_later", "downstream_independent", ["downstream_independent"]),
        ],
    )
    result = await WorkflowRunner().run_async(dag)

    assert result.state == WorkflowState.FAILED
    assert result.step_states["fail_continue"] == StepState.FAILED
    assert result.step_states["fail_fast_step"] == StepState.FAILED
    assert result.step_states["downstream_later"] == StepState.SKIPPED
    assert result.step_attempts["fail_fast_step"] == 1


@pytest.mark.asyncio
async def test_continue_lifecycle_hooks_contain_skipped_events():
    marker: list[str] = []
    skipped_steps: list[str] = []
    register_success("root_hook", marker)
    register_failure("bad_hook_step")
    register_success("child_hook_step", marker)
    register_success("grandchild_hook_step", marker)
    register_success("independent_step", marker)
    register_success("independent_later", marker)

    hooks = HookRegistry()

    async def on_skip(_, __, payload):
        skipped_steps.append(payload.get("step_id"))

    hooks.register(LifecycleEvent.STEP_SKIPPED, on_skip)

    dag = DAGSpec(
        id="hook_skip_dag",
        steps=[
            inline("root_hook", "root_hook"),
            inline("bad_hook_step", "bad_hook_step", ["root_hook"], on_failure=OnFailureAction.CONTINUE),
            inline("child_hook_step", "child_hook_step", ["bad_hook_step"]),
            inline("grandchild_hook_step", "grandchild_hook_step", ["child_hook_step"]),
            inline("independent_step", "independent_step", ["root_hook"]),
            inline("independent_later", "independent_later", ["independent_step"]),
        ],
    )
    result = await WorkflowRunner(hook_registry=hooks).run_async(dag)

    assert result.state == WorkflowState.FAILED
    assert result.step_states["independent_later"] == StepState.COMPLETED
    assert result.step_attempts["independent_later"] == 1
    assert "child_hook_step" in skipped_steps
    assert "grandchild_hook_step" in skipped_steps
    assert "child_hook_step" not in marker


@pytest.mark.asyncio
async def test_continue_with_three_independent_branches():
    marker: list[str] = []
    register_failure("branch_1_a")
    register_success("branch_1_b", marker)
    register_success("branch_2_a", marker)
    register_success("branch_2_b", marker)
    register_success("branch_3_a", marker)
    register_success("branch_3_b", marker)

    dag = DAGSpec(
        id="three_branches_dag",
        steps=[
            inline("b1_a", "branch_1_a", on_failure=OnFailureAction.CONTINUE),
            inline("b1_b", "branch_1_b", ["b1_a"]),
            inline("b2_a", "branch_2_a"),
            inline("b2_b", "branch_2_b", ["b2_a"]),
            inline("b3_a", "branch_3_a"),
            inline("b3_b", "branch_3_b", ["b3_a"]),
        ],
    )
    result = await WorkflowRunner().run_async(dag)

    assert result.state == WorkflowState.FAILED
    assert result.step_states["b1_a"] == StepState.FAILED
    assert result.step_states["b1_b"] == StepState.SKIPPED
    assert result.step_states["b2_a"] == StepState.COMPLETED
    assert result.step_states["b2_b"] == StepState.COMPLETED
    assert result.step_states["b3_a"] == StepState.COMPLETED
    assert result.step_states["b3_b"] == StepState.COMPLETED
    assert result.step_attempts["b2_b"] == 1
    assert "branch_1_b" not in marker
    assert set(marker) == {"branch_2_a", "branch_2_b", "branch_3_a", "branch_3_b"}


@pytest.mark.asyncio
async def test_continue_persistence_in_sqlite(tmp_path):
    db_file = tmp_path / "test_continue_persist.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    db_mgr = DatabaseManager(database_url=db_url)
    repo = BasaltRepository(db_manager=db_mgr)
    await repo.initialize()

    marker: list[str] = []
    register_success("sql_root", marker)
    register_failure("sql_bad")
    register_success("sql_good", marker)
    register_success("sql_child", marker)
    register_success("sql_good_2", marker)

    dag = DAGSpec(
        id="dag_sql_continue",
        steps=[
            inline("sql_root", "sql_root"),
            inline("sql_bad", "sql_bad", ["sql_root"], on_failure=OnFailureAction.CONTINUE),
            inline("sql_child", "sql_child", ["sql_bad"]),
            inline("sql_good", "sql_good", ["sql_root"]),
            inline("sql_good_2", "sql_good_2", ["sql_good"]),
        ],
    )
    await repo.save_dag(dag)

    result = await WorkflowRunner().run_async(dag)
    assert result.state == WorkflowState.FAILED
    assert result.step_states["sql_bad"] == StepState.FAILED
    assert result.step_states["sql_child"] == StepState.SKIPPED
    assert result.step_states["sql_good"] == StepState.COMPLETED
    assert result.step_states["sql_good_2"] == StepState.COMPLETED
    assert result.step_attempts["sql_good_2"] == 1

    await repo.save_run_result(result)
    loaded = await repo.get_run(result.run_id)

    assert loaded is not None
    assert loaded.state == WorkflowState.FAILED
    assert loaded.step_states["sql_bad"] == StepState.FAILED
    assert loaded.step_states["sql_child"] == StepState.SKIPPED
    assert loaded.step_states["sql_good_2"] == StepState.COMPLETED
    assert loaded.step_attempts["sql_good_2"] == 1
    await db_mgr.close()


@pytest.mark.asyncio
async def test_continue_step_outputs_ledger_intact():
    marker: list[str] = []
    register_success("root_prod", marker)
    register_failure("ledger_bad")

    def producer_fn() -> dict[str, int]:
        return {"amount": 500}

    def consumer_fn() -> dict[str, int]:
        return {"final_val": 1000}

    register_python_callable("producer", producer_fn)
    register_python_callable("consumer", consumer_fn)

    dag = DAGSpec(
        id="ledger_dag",
        steps=[
            inline("root_prod", "producer"),
            inline("ledger_bad", "ledger_bad", ["root_prod"], on_failure=OnFailureAction.CONTINUE),
            inline("ledger_good", "consumer", ["root_prod"]),
            inline("final_step", "consumer", ["ledger_good"]),
        ],
    )
    result = await WorkflowRunner().run_async(dag)

    assert result.state == WorkflowState.FAILED
    assert result.outputs["ledger_good"] == {"final_val": 1000}
    assert result.outputs["final_step"] == {"final_val": 1000}
    assert result.step_attempts["final_step"] == 1
    assert "ledger_bad" not in result.outputs


@pytest.mark.asyncio
async def test_explicit_fail_fast_action_aborts_independent_branch():
    marker: list[str] = []
    register_success("root_start", marker)
    register_failure("fail_fast_explicit")
    register_success("independent_later", marker)
    register_success("later_child", marker)

    dag = DAGSpec(
        id="explicit_fast_fail_dag",
        steps=[
            inline("root_start", "root_start"),
            inline("fail_fast_explicit", "fail_fast_explicit", ["root_start"], on_failure=OnFailureAction.FAIL_FAST),
            inline("independent_later", "independent_later", ["root_start"]),
            inline("later_child", "later_child", ["independent_later"]),
        ],
    )
    result = await WorkflowRunner().run_async(dag)

    assert result.state == WorkflowState.FAILED
    assert result.step_states["fail_fast_explicit"] == StepState.FAILED
    assert result.step_states["later_child"] == StepState.SKIPPED
    assert result.step_attempts["fail_fast_explicit"] == 1
