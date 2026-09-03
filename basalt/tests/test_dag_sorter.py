"""Unit Tests for DAG Sorter and Validator Modules in Basalt Workflow Engine.

Validates Kahn's level-parallel sorting, linear ordering, cycle path detection,
transitive dependency tracking, critical path calculation, and structural validation rules.
"""

import pytest

from basalt.core.dag.ast import DAGSpec, StepSpec, TriggerSpec, TriggerType
from basalt.core.dag.exceptions import (
    CycleDetectedError,
    DAGValidationError,
    DuplicateStepIdError,
    InvalidExecutorConfigError,
    OrphanDependencyError,
)
from basalt.core.dag.sorter import DAGSorter, sort_dag_steps
from basalt.core.dag.validator import DAGValidator, validate_dag_spec


@pytest.fixture
def linear_dag() -> DAGSpec:
    """Fixture returning a linear DAG (A -> B -> C)."""
    return DAGSpec(
        id="linear_dag",
        name="Linear Pipeline",
        steps=[
            StepSpec(id="stepA", command="echo A"),
            StepSpec(id="stepB", command="echo B", depends_on=["stepA"]),
            StepSpec(id="stepC", command="echo C", depends_on=["stepB"]),
        ],
    )


@pytest.fixture
def diamond_dag() -> DAGSpec:
    r"""Fixture returning a diamond-shaped parallel DAG.

          stepA
         /     \
      stepB   stepC
         \     /
          stepD
    """
    return DAGSpec(
        id="diamond_dag",
        name="Diamond Pipeline",
        steps=[
            StepSpec(id="stepA", command="echo A"),
            StepSpec(id="stepB", command="echo B", depends_on=["stepA"]),
            StepSpec(id="stepC", command="echo C", depends_on=["stepA"]),
            StepSpec(id="stepD", command="echo D", depends_on=["stepB", "stepC"]),
        ],
    )


@pytest.fixture
def cyclic_dag() -> DAGSpec:
    """Fixture returning a cyclic DAG (A -> B -> C -> A)."""
    return DAGSpec(
        id="cyclic_dag",
        name="Cyclic Pipeline",
        steps=[
            StepSpec(id="stepA", command="echo A", depends_on=["stepC"]),
            StepSpec(id="stepB", command="echo B", depends_on=["stepA"]),
            StepSpec(id="stepC", command="echo C", depends_on=["stepB"]),
        ],
    )


def test_topological_sort_linear_dag(linear_dag: DAGSpec) -> None:
    """Verify execution levels for linear DAG."""
    levels = DAGSorter.get_execution_levels(linear_dag)

    assert len(levels) == 3
    assert [s.id for s in levels[0]] == ["stepA"]
    assert [s.id for s in levels[1]] == ["stepB"]
    assert [s.id for s in levels[2]] == ["stepC"]


def test_topological_sort_diamond_dag(diamond_dag: DAGSpec) -> None:
    """Verify execution levels for diamond DAG."""
    levels = sort_dag_steps(diamond_dag)

    assert len(levels) == 3
    assert [s.id for s in levels[0]] == ["stepA"]

    level_1_ids = set(s.id for s in levels[1])
    assert level_1_ids == {"stepB", "stepC"}

    assert [s.id for s in levels[2]] == ["stepD"]


def test_linear_order_resolution(diamond_dag: DAGSpec) -> None:
    """Verify linear ordering resolution."""
    linear_steps = DAGSorter.get_linear_order(diamond_dag)
    linear_ids = [s.id for s in linear_steps]

    assert linear_ids[0] == "stepA"
    assert linear_ids[-1] == "stepD"
    assert len(linear_ids) == 4


def test_cycle_detection_raises_exception(cyclic_dag: DAGSpec) -> None:
    """Verify cyclic graph raises CycleDetectedError with explicit path."""
    with pytest.raises(CycleDetectedError) as exc_info:
        DAGSorter.get_execution_levels(cyclic_dag)

    assert exc_info.value.code == "CYCLE_DETECTED"
    assert exc_info.value.cycle_path is not None
    assert len(exc_info.value.cycle_path) >= 2


def test_detect_cycle_path_directly(cyclic_dag: DAGSpec) -> None:
    """Verify detect_cycle_path extracts explicit path sequence."""
    cycle_path = DAGSorter.detect_cycle_path(cyclic_dag)

    assert len(cycle_path) >= 2
    # Ensure cycle forms a loop
    assert cycle_path[0] == cycle_path[-1] or cycle_path[1] in cycle_path


def test_upstream_ancestors(diamond_dag: DAGSpec) -> None:
    """Verify tracking transitive upstream ancestor steps."""
    ancestors_d = DAGSorter.get_upstream_ancestors(diamond_dag, "stepD")
    assert ancestors_d == {"stepA", "stepB", "stepC"}

    ancestors_b = DAGSorter.get_upstream_ancestors(diamond_dag, "stepB")
    assert ancestors_b == {"stepA"}

    ancestors_a = DAGSorter.get_upstream_ancestors(diamond_dag, "stepA")
    assert ancestors_a == set()

    non_existent = DAGSorter.get_upstream_ancestors(diamond_dag, "ghost")
    assert non_existent == set()


def test_downstream_descendants(diamond_dag: DAGSpec) -> None:
    """Verify tracking transitive downstream descendant steps."""
    descendants_a = DAGSorter.get_downstream_descendants(diamond_dag, "stepA")
    assert descendants_a == {"stepB", "stepC", "stepD"}

    descendants_d = DAGSorter.get_downstream_descendants(diamond_dag, "stepD")
    assert descendants_d == set()


def test_critical_path_calculation() -> None:
    """Verify critical path calculation based on step timeouts."""
    dag = DAGSpec(
        id="critical_dag",
        name="Critical Path Test",
        steps=[
            StepSpec(id="start", command="echo start", timeout_seconds=10.0),
            StepSpec(id="path1", command="echo fast", depends_on=["start"], timeout_seconds=5.0),
            StepSpec(id="path2", command="echo slow", depends_on=["start"], timeout_seconds=50.0),
            StepSpec(
                id="end", command="echo end", depends_on=["path1", "path2"], timeout_seconds=10.0
            ),
        ],
    )

    critical_steps = DAGSorter.get_critical_path(dag)
    critical_ids = [s.id for s in critical_steps]

    assert critical_ids == ["start", "path2", "end"]


def test_validator_duplicate_step_ids() -> None:
    """Verify validator detects duplicate step IDs."""
    invalid_dag = DAGSpec(
        id="dup_dag",
        name="Duplicate Step ID DAG",
        steps=[
            StepSpec(id="step1", command="echo 1"),
            StepSpec(id="step1", command="echo 2"),  # Duplicate
        ],
    )
    with pytest.raises(DuplicateStepIdError) as exc_info:
        DAGValidator.validate_dag(invalid_dag)
    assert exc_info.value.step_id == "step1"


def test_validator_orphan_dependency() -> None:
    """Verify validator detects orphan step dependencies."""
    invalid_dag = DAGSpec(
        id="orphan_dag",
        name="Orphan Dependency DAG",
        steps=[
            StepSpec(id="step1", command="echo 1", depends_on=["ghost_step"]),
        ],
    )
    with pytest.raises(OrphanDependencyError) as exc_info:
        DAGValidator.validate_dag(invalid_dag)
    assert exc_info.value.missing_dependency_id == "ghost_step"


def test_validator_self_dependency() -> None:
    """Verify validator detects self-referential dependencies."""
    invalid_dag = DAGSpec(
        id="self_dep_dag",
        name="Self Dependency DAG",
        steps=[
            StepSpec(id="step1", command="echo 1", depends_on=["step1"]),
        ],
    )
    with pytest.raises(DAGValidationError) as exc_info:
        DAGValidator.validate_dag(invalid_dag)
    assert "cannot depend on itself" in str(exc_info.value.message)


def test_validator_invalid_executor_config() -> None:
    """Verify validator detects invalid executor configurations."""
    invalid_dag = DAGSpec(
        id="bad_exec_dag",
        name="Bad Executor Config",
        steps=[
            StepSpec(id="step1", executor_type="subprocess", command="   "),  # Empty command
        ],
    )
    with pytest.raises(InvalidExecutorConfigError) as exc_info:
        DAGValidator.validate_dag(invalid_dag)
    assert exc_info.value.executor_type == "subprocess"


def test_validator_duplicate_trigger_ids() -> None:
    """Verify validator detects duplicate trigger IDs."""
    invalid_dag = DAGSpec(
        id="dup_trigger_dag",
        name="Duplicate Trigger DAG",
        steps=[StepSpec(id="step1", command="echo 1")],
        triggers=[
            TriggerSpec(id="trg1", type=TriggerType.INTERVAL, interval_seconds=10.0),
            TriggerSpec(id="trg1", type=TriggerType.CRON, cron="* * * * *"),
        ],
    )
    with pytest.raises(DAGValidationError) as exc_info:
        DAGValidator.validate_dag(invalid_dag)
    assert "Duplicate trigger ID" in str(exc_info.value.message)


def test_validate_dag_spec_functional_wrapper(diamond_dag: DAGSpec) -> None:
    """Verify validate_dag_spec returns True for valid DAGs."""
    assert validate_dag_spec(diamond_dag) is True
