"""DAG Structural Validation Module for Basalt Workflow Engine.

Provides deep structural validation of DAG definitions, verifying step ID uniqueness,
detecting orphan dependencies, checking self-referential steps, and verifying executor configs.
"""

from basalt.core.dag.ast import DAGSpec, ExecutorType
from basalt.core.dag.exceptions import (
    DAGValidationError,
    DuplicateStepIdError,
    InvalidExecutorConfigError,
    OrphanDependencyError,
)
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class DAGValidator:
    """Structural validator performing sanity checks on DAGSpec objects."""

    @classmethod
    def validate_dag(cls, dag: DAGSpec) -> None:
        """Perform comprehensive structural validation on a DAG specification.

        Args:
            dag: DAGSpec object to validate.

        Raises:
            DuplicateStepIdError: If duplicate step IDs exist.
            OrphanDependencyError: If a step depends on an unresolvable step ID.
            DAGValidationError: If self-dependencies or duplicate trigger IDs exist.
            InvalidExecutorConfigError: If step executor parameters are invalid.
        """
        logger.debug(f"Starting structural validation for DAG '{dag.id}'")

        cls.check_duplicate_step_ids(dag)
        cls.check_self_dependencies(dag)
        cls.check_orphan_dependencies(dag)
        cls.check_duplicate_trigger_ids(dag)
        cls.check_executor_configurations(dag)
        cls.check_graph_reachability(dag)

        logger.debug(f"DAG '{dag.id}' passed all structural validation checks")

    @classmethod
    def check_duplicate_step_ids(cls, dag: DAGSpec) -> None:
        """Verify all step IDs within the DAG are unique.

        Args:
            dag: DAGSpec object.

        Raises:
            DuplicateStepIdError: If duplicate step ID is found.
        """
        seen_ids: set[str] = set()
        for step in dag.steps:
            if step.id in seen_ids:
                raise DuplicateStepIdError(step_id=step.id, dag_id=dag.id)
            seen_ids.add(step.id)

    @classmethod
    def check_self_dependencies(cls, dag: DAGSpec) -> None:
        """Verify no step lists itself as an upstream dependency.

        Args:
            dag: DAGSpec object.

        Raises:
            DAGValidationError: If self-referential step dependency is found.
        """
        for step in dag.steps:
            if step.id in step.depends_on:
                raise DAGValidationError(
                    message=f"Step '{step.id}' cannot depend on itself.",
                    dag_id=dag.id,
                )

    @classmethod
    def check_orphan_dependencies(cls, dag: DAGSpec) -> None:
        """Verify all step upstream dependencies exist within the DAG.

        Args:
            dag: DAGSpec object.

        Raises:
            OrphanDependencyError: If a referenced dependency step ID does not exist.
        """
        valid_step_ids: set[str] = set(dag.get_step_ids())
        for step in dag.steps:
            for dep_id in step.depends_on:
                if dep_id not in valid_step_ids:
                    raise OrphanDependencyError(
                        step_id=step.id,
                        missing_dependency_id=dep_id,
                        dag_id=dag.id,
                    )

    @classmethod
    def check_duplicate_trigger_ids(cls, dag: DAGSpec) -> None:
        """Verify all trigger IDs attached to the DAG are unique.

        Args:
            dag: DAGSpec object.

        Raises:
            DAGValidationError: If duplicate trigger ID is found.
        """
        seen_trigger_ids: set[str] = set()
        for trigger in dag.triggers:
            if trigger.id in seen_trigger_ids:
                raise DAGValidationError(
                    message=f"Duplicate trigger ID '{trigger.id}' in DAG '{dag.id}'.",
                    dag_id=dag.id,
                )
            seen_trigger_ids.add(trigger.id)

    @classmethod
    def check_executor_configurations(cls, dag: DAGSpec) -> None:
        """Validate step executor parameter completeness.

        Args:
            dag: DAGSpec object.

        Raises:
            InvalidExecutorConfigError: If required parameters for executor type are missing.
        """
        for step in dag.steps:
            if step.executor_type == ExecutorType.SUBPROCESS:
                if not step.command or not step.command.strip():
                    raise InvalidExecutorConfigError(
                        step_id=step.id,
                        executor_type="subprocess",
                        reason="Command string cannot be empty.",
                        dag_id=dag.id,
                    )
            elif step.executor_type == ExecutorType.INLINE:
                if not step.function or ":" not in step.function:
                    raise InvalidExecutorConfigError(
                        step_id=step.id,
                        executor_type="inline",
                        reason="Function must specify module:callable path (e.g., 'myapp.tasks:compute').",
                        dag_id=dag.id,
                    )
            elif step.executor_type == ExecutorType.HTTP:
                if not step.url or not (
                    step.url.startswith("http://") or step.url.startswith("https://")
                ):
                    raise InvalidExecutorConfigError(
                        step_id=step.id,
                        executor_type="http",
                        reason="URL must start with 'http://' or 'https://'.",
                        dag_id=dag.id,
                    )

    @classmethod
    def check_graph_reachability(cls, dag: DAGSpec) -> None:
        """Check for unrooted isolated steps that have dependencies but no root path.

        Args:
            dag: DAGSpec object.
        """
        root_steps = dag.get_root_steps()
        if not root_steps:
            raise DAGValidationError(
                message=f"DAG '{dag.id}' has no root steps (steps with 0 upstream dependencies).",
                dag_id=dag.id,
            )

        # Build adjacency graph
        adj_list: dict[str, list[str]] = {step.id: [] for step in dag.steps}
        for step in dag.steps:
            for parent_id in step.depends_on:
                adj_list[parent_id].append(step.id)

        # BFS from all root steps
        visited: set[str] = set()
        queue = [s.id for s in root_steps]
        while queue:
            curr = queue.pop(0)
            if curr in visited:
                continue
            visited.add(curr)
            for child in adj_list.get(curr, []):
                if child not in visited:
                    queue.append(child)

        all_step_ids = set(dag.get_step_ids())
        unreachable = all_step_ids - visited
        if unreachable:
            logger.warning(
                f"DAG '{dag.id}' contains unreachable isolated steps: {sorted(list(unreachable))}"
            )


def validate_dag_spec(dag: DAGSpec) -> bool:
    """Functional wrapper for validating a DAGSpec. Returns True if valid.

    Args:
        dag: DAGSpec object.

    Returns:
        True if valid. Raises DAGValidationError or subtype if invalid.
    """
    DAGValidator.validate_dag(dag)
    return True
