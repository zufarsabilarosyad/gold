"""DAG Topological Sorting and Cycle Detection Module for Basalt Workflow Engine.

Provides algorithms for linear and level-parallel topological ordering of workflow steps
using Kahn's in-degree algorithm and Depth-First Search (DFS) with cycle path extraction,
transitive dependency query methods, and critical execution path calculation.
"""

from collections import deque

from basalt.core.dag.ast import DAGSpec, StepSpec
from basalt.core.dag.exceptions import CycleDetectedError
from basalt.utils.logger import get_logger

logger = get_logger(__name__)

# DFS node coloring constants for cycle detection
COLOR_WHITE = 0  # Unvisited
COLOR_GRAY = 1  # Visiting (in current recursion stack)
COLOR_BLACK = 2  # Visited (fully processed)


class DAGSorter:
    """Sorter utility for topological execution order resolution and cycle detection."""

    @classmethod
    def topological_sort(cls, dag: DAGSpec) -> list[list[StepSpec]]:
        """Alias for get_execution_levels."""
        return cls.get_execution_levels(dag)

    @classmethod
    def get_execution_levels(cls, dag: DAGSpec) -> list[list[StepSpec]]:
        """Compute parallel execution stages (levels of independent steps) using Kahn's algorithm.

        Returns:
            List of step lists representing sequential execution stages.
            Steps within the same stage can be executed concurrently.

        Raises:
            CycleDetectedError: If a cyclic step dependency is detected.
        """
        # Step lookup table
        step_map: dict[str, StepSpec] = {step.id: step for step in dag.steps}

        # Build in-degrees (number of upstream dependencies) and adjacency list
        in_degree: dict[str, int] = {step.id: 0 for step in dag.steps}
        downstream_adj: dict[str, list[str]] = {step.id: [] for step in dag.steps}

        for step in dag.steps:
            in_degree[step.id] = len(step.depends_on)
            for parent_id in step.depends_on:
                if parent_id in downstream_adj:
                    downstream_adj[parent_id].append(step.id)

        # Queue root nodes (in-degree == 0)
        current_level_queue: deque[str] = deque(
            [step_id for step_id, degree in in_degree.items() if degree == 0]
        )

        if not current_level_queue:
            # All steps have dependencies => Cycle exists
            cycle_path = cls.detect_cycle_path(dag)
            raise CycleDetectedError(cycle_path=cycle_path or dag.get_step_ids(), dag_id=dag.id)

        levels: list[list[StepSpec]] = []
        processed_count = 0

        while current_level_queue:
            level_step_ids: list[str] = list(current_level_queue)
            current_level_queue.clear()

            level_steps: list[StepSpec] = [step_map[s_id] for s_id in level_step_ids]
            levels.append(level_steps)
            processed_count += len(level_step_ids)

            next_level_candidates: list[str] = []
            for s_id in level_step_ids:
                for child_id in downstream_adj[s_id]:
                    in_degree[child_id] -= 1
                    if in_degree[child_id] == 0:
                        next_level_candidates.append(child_id)

            current_level_queue.extend(next_level_candidates)

        if processed_count < len(dag.steps):
            cycle_path = cls.detect_cycle_path(dag)
            raise CycleDetectedError(cycle_path=cycle_path or dag.get_step_ids(), dag_id=dag.id)

        return levels

    @classmethod
    def get_linear_order(cls, dag: DAGSpec) -> list[StepSpec]:
        """Compute a flat, linear topological ordering of steps using DFS.

        Returns:
            List of StepSpec objects ordered sequentially.

        Raises:
            CycleDetectedError: If a cyclic step dependency is detected.
        """
        levels = cls.get_execution_levels(dag)
        linear_steps: list[StepSpec] = []
        for level in levels:
            linear_steps.extend(level)
        return linear_steps

    @classmethod
    def detect_cycle_path(cls, dag: DAGSpec) -> list[str]:
        """Find and return the explicit cycle path sequence using DFS color marking.

        Returns:
            List of step IDs representing the cycle (e.g. ['stepA', 'stepB', 'stepA']).
            Returns empty list if no cycle exists.
        """
        step_map: dict[str, StepSpec] = {step.id: step for step in dag.steps}

        # Build graph mapping step_id -> list of upstream dependency step_ids
        parent_adj: dict[str, list[str]] = {step.id: list(step.depends_on) for step in dag.steps}

        colors: dict[str, int] = {step.id: COLOR_WHITE for step in dag.steps}
        parent_trace: dict[str, str | None] = {step.id: None for step in dag.steps}

        cycle_result: list[str] = []

        def dfs(node: str) -> bool:
            nonlocal cycle_result
            colors[node] = COLOR_GRAY

            for parent_id in parent_adj.get(node, []):
                if parent_id not in colors:
                    continue
                if colors[parent_id] == COLOR_GRAY:
                    # Cycle detected! Reconstruct path from node to parent_id
                    cycle_path = [parent_id, node]
                    curr = node
                    while curr != parent_id and parent_trace[curr] is not None:
                        curr = parent_trace[curr]  # type: ignore
                        cycle_path.append(curr)
                    cycle_path.reverse()
                    cycle_result = cycle_path
                    return True
                elif colors[parent_id] == COLOR_WHITE:
                    parent_trace[parent_id] = node
                    if dfs(parent_id):
                        return True

            colors[node] = COLOR_BLACK
            return False

        for step in dag.steps:
            if colors[step.id] == COLOR_WHITE:
                if dfs(step.id):
                    break

        return cycle_result

    @classmethod
    def get_upstream_ancestors(cls, dag: DAGSpec, step_id: str) -> set[str]:
        """Find all transitive upstream dependency step IDs for a target step.

        Args:
            dag: DAGSpec object.
            step_id: Target step ID.

        Returns:
            Set of all ancestor step IDs required before target step can run.
        """
        step_map = {step.id: step for step in dag.steps}
        if step_id not in step_map:
            return set()

        ancestors: set[str] = set()
        queue = deque(step_map[step_id].depends_on)

        while queue:
            curr = queue.popleft()
            if curr not in ancestors and curr in step_map:
                ancestors.add(curr)
                queue.extend(step_map[curr].depends_on)

        return ancestors

    @classmethod
    def get_downstream_descendants(cls, dag: DAGSpec, step_id: str) -> set[str]:
        """Find all transitive downstream dependent step IDs for a target step.

        Args:
            dag: DAGSpec object.
            step_id: Target step ID.

        Returns:
            Set of all descendant step IDs depending on target step.
        """
        downstream_adj: dict[str, list[str]] = {step.id: [] for step in dag.steps}
        for step in dag.steps:
            for parent_id in step.depends_on:
                if parent_id in downstream_adj:
                    downstream_adj[parent_id].append(step.id)

        descendants: set[str] = set()
        queue = deque(downstream_adj.get(step_id, []))

        while queue:
            curr = queue.popleft()
            if curr not in descendants:
                descendants.add(curr)
                queue.extend(downstream_adj.get(curr, []))

        return descendants

    @classmethod
    def get_critical_path(cls, dag: DAGSpec) -> list[StepSpec]:
        """Compute the longest execution path (critical path) based on step timeouts.

        Args:
            dag: DAGSpec object.

        Returns:
            List of StepSpec objects forming the critical path.
        """
        step_map = {step.id: step for step in dag.steps}
        levels = cls.get_execution_levels(dag)

        # Dynamic programming for longest path: dist[step_id], parent[step_id]
        dist: dict[str, float] = {step.id: step.timeout_seconds for step in dag.steps}
        prev: dict[str, str | None] = {step.id: None for step in dag.steps}

        for level in levels:
            for step in level:
                for parent_id in step.depends_on:
                    if parent_id in dist:
                        candidate_dist = dist[parent_id] + step.timeout_seconds
                        if candidate_dist > dist[step.id]:
                            dist[step.id] = candidate_dist
                            prev[step.id] = parent_id

        # Find step with max total distance
        max_step_id = max(dist.keys(), key=lambda s_id: dist[s_id])
        path_ids: list[str] = []
        curr: str | None = max_step_id
        while curr is not None:
            path_ids.append(curr)
            curr = prev[curr]

        path_ids.reverse()
        return [step_map[s_id] for s_id in path_ids]


def sort_dag_steps(dag: DAGSpec) -> list[list[StepSpec]]:
    """Functional helper returning parallel execution levels for a DAGSpec.

    Args:
        dag: DAGSpec object.

    Returns:
        List of parallel step lists.
    """
    return DAGSorter.get_execution_levels(dag)
