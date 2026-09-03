"""Execution Context Container Module for Basalt Workflow Engine.

Provides thread-safe and async-safe runtime state management, storing workflow inputs,
environment variables, step output payloads, execution metadata, and step records.
"""

from threading import Lock
from typing import Any

from basalt.core.engine.state_machine import StepExecutionRecord, StepState
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class ExecutionContext:
    """Thread-safe runtime execution context storing workflow data and step outputs."""

    def __init__(
        self,
        run_id: str,
        dag_id: str,
        inputs: dict[str, Any] | None = None,
        env: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.run_id = run_id
        self.dag_id = dag_id
        self.inputs = inputs.copy() if inputs else {}
        self.env = env.copy() if env else {}
        self.metadata = metadata.copy() if metadata else {}

        # Internal state stores protected by lock
        self._lock = Lock()
        self._step_outputs: dict[str, dict[str, Any]] = {}
        self._step_states: dict[str, StepState] = {}
        self._step_records: dict[str, StepExecutionRecord] = {}

    def set_input(self, key: str, value: Any) -> None:
        """Store or update a workflow input parameter.

        Args:
            key: Input parameter name.
            value: Parameter value.
        """
        with self._lock:
            self.inputs[key] = value

    def set_env(self, key: str, value: str) -> None:
        """Store or update an environment variable.

        Args:
            key: Variable name.
            value: Variable string value.
        """
        with self._lock:
            self.env[key] = str(value)

    def set_metadata(self, key: str, value: Any) -> None:
        """Store or update custom execution metadata.

        Args:
            key: Metadata key name.
            value: Value.
        """
        with self._lock:
            self.metadata[key] = value

    def set_step_state(self, step_id: str, state: StepState) -> None:
        """Record or update active state for a step.

        Args:
            step_id: Step identifier.
            state: Active StepState.
        """
        with self._lock:
            self._step_states[step_id] = state
            if step_id not in self._step_records:
                self._step_records[step_id] = StepExecutionRecord(step_id=step_id, state=state)
            else:
                self._step_records[step_id].state = state

    def begin_attempt(self, step_id: str, max_retries: int) -> int:
        """Start an execution attempt while retaining retry metadata for status reporting."""
        with self._lock:
            record = self._step_records.get(step_id)
            if record is None:
                record = StepExecutionRecord(step_id=step_id, attempt=0, max_retries=max_retries)
                self._step_records[step_id] = record
            record.attempt += 1
            record.max_retries = max_retries
            record.mark_running()
            self._step_states[step_id] = StepState.RUNNING
            return record.attempt

    def mark_retrying(self, step_id: str, error: str, delay_seconds: float = 0.0) -> None:
        """Expose a recoverable failure without resetting the current attempt count."""
        with self._lock:
            record = self._step_records.get(step_id)
            if record is not None:
                record.state = StepState.RETRYING
                record.error_message = error
            self._step_states[step_id] = StepState.RETRYING

    def set_step_attempt(self, step_id: str, attempt: int) -> None:
        """Explicitly set attempt count on active step execution record."""
        with self._lock:
            record = self._step_records.get(step_id)
            if record is not None:
                record.attempt = attempt
            else:
                self._step_records[step_id] = StepExecutionRecord(step_id=step_id, attempt=attempt)

    def get_step_attempt(self, step_id: str) -> int:
        """Retrieve execution attempt count recorded for a step."""
        with self._lock:
            record = self._step_records.get(step_id)
            return record.attempt if record is not None else 1

    def step_attempts(self) -> dict[str, int]:
        """Return completed or in-flight attempt counts by step ID."""
        with self._lock:
            return {step_id: record.attempt for step_id, record in self._step_records.items()}

    def get_all_step_attempts(self) -> dict[str, int]:
        """Return snapshot dictionary mapping all step IDs to their attempt counts."""
        return self.step_attempts()


    def get_step_state(self, step_id: str) -> StepState:
        """Retrieve active state for a step.

        Args:
            step_id: Step identifier.

        Returns:
            StepState (defaults to StepState.PENDING if unrecorded).
        """
        with self._lock:
            return self._step_states.get(step_id, StepState.PENDING)

    def is_step_completed(self, step_id: str) -> bool:
        """Check if step state is COMPLETED."""
        return self.get_step_state(step_id) == StepState.COMPLETED

    def is_step_failed(self, step_id: str) -> bool:
        """Check if step state is FAILED."""
        return self.get_step_state(step_id) in (StepState.FAILED, StepState.TIMEOUT)

    def set_step_output(self, step_id: str, output: dict[str, Any]) -> None:
        """Store output data payload returned by step execution.

        Args:
            step_id: Step identifier.
            output: Dictionary payload returned by step executor.
        """
        with self._lock:
            self._step_outputs[step_id] = output or {}
            if step_id in self._step_records:
                self._step_records[step_id].output_data = output or {}

    def merge_step_output(self, step_id: str, partial_output: dict[str, Any]) -> None:
        """Merge additional key-value pairs into existing step output dictionary.

        Args:
            step_id: Step identifier.
            partial_output: Dictionary key-value pairs to merge.
        """
        with self._lock:
            existing = self._step_outputs.get(step_id, {})
            existing.update(partial_output or {})
            self._step_outputs[step_id] = existing
            if step_id in self._step_records:
                self._step_records[step_id].output_data = existing

    def get_step_output(self, step_id: str) -> dict[str, Any]:
        """Retrieve output data payload for a completed step.

        Args:
            step_id: Step identifier.

        Returns:
            Dictionary output payload (empty dict if not recorded).
        """
        with self._lock:
            return self._step_outputs.get(step_id, {}).copy()

    def get_step_record(self, step_id: str) -> StepExecutionRecord | None:
        """Retrieve StepExecutionRecord snapshot for step_id."""
        with self._lock:
            record = self._step_records.get(step_id)
            return record.model_copy() if record else None

    def get_all_step_states(self) -> dict[str, StepState]:
        """Retrieve copy of all recorded step states."""
        with self._lock:
            return self._step_states.copy()

    def get_all_step_outputs(self) -> dict[str, dict[str, Any]]:
        """Retrieve copy of all step outputs dictionary."""
        with self._lock:
            return {k: v.copy() for k, v in self._step_outputs.items()}

    def resolve_variable_path(self, path_expression: str) -> Any:
        """Resolve dot-separated variable path expression within context.

        Supported namespaces:
        - 'steps.<step_id>.output.<key>' -> Output dictionary from step
        - 'inputs.<key>' -> Workflow input parameters
        - 'env.<VAR_NAME>' -> Environment variable
        - 'run.id' -> Active workflow run ID
        - 'dag.id' -> Active DAG ID

        Args:
            path_expression: Dot-separated lookup string (e.g. 'steps.fetch.output.id').

        Returns:
            Resolved value if path exists, None otherwise.
        """
        clean_path = path_expression.strip()
        parts = clean_path.split(".")

        if not parts:
            return None

        root = parts[0].lower()

        # Handle 'run' namespace
        if root == "run":
            if len(parts) > 1 and parts[1].lower() == "id":
                return self.run_id
            return self.run_id

        # Handle 'dag' namespace
        if root == "dag":
            if len(parts) > 1 and parts[1].lower() == "id":
                return self.dag_id
            return self.dag_id

        # Handle 'inputs' namespace
        if root == "inputs":
            with self._lock:
                if len(parts) == 1:
                    return self.inputs.copy()
                curr: Any = self.inputs
                for p in parts[1:]:
                    if isinstance(curr, dict) and p in curr:
                        curr = curr[p]
                    else:
                        return None
                return curr

        # Handle 'env' namespace
        if root == "env":
            with self._lock:
                if len(parts) == 1:
                    return self.env.copy()
                var_name = parts[1]
                return self.env.get(var_name)

        # Handle 'steps' namespace: steps.<step_id>.output.<key>
        if root == "steps":
            if len(parts) < 2:
                return self.get_all_step_outputs()

            step_id = parts[1]
            step_output = self.get_step_output(step_id)

            if len(parts) == 2:
                return step_output

            if len(parts) >= 3 and parts[2].lower() == "output":
                if len(parts) == 3:
                    return step_output

                curr: Any = step_output
                for p in parts[3:]:
                    if isinstance(curr, dict) and p in curr:
                        curr = curr[p]
                    else:
                        return None
                return curr

        return None

    def snapshot(self) -> dict[str, Any]:
        """Create a complete serializable dictionary snapshot of execution context."""
        with self._lock:
            return {
                "run_id": self.run_id,
                "dag_id": self.dag_id,
                "inputs": self.inputs.copy(),
                "env": self.env.copy(),
                "metadata": self.metadata.copy(),
                "step_states": {k: v.value for k, v in self._step_states.items()},
                "step_outputs": {k: v.copy() for k, v in self._step_outputs.items()},
            }
