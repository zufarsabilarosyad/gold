"""Abstract Base Task Executor Subsystem Module for Basalt Workflow Engine.

Defines the BaseExecutor abstract contract, timeout enforcement, output sanitization,
environment variable propagation, and exception hierarchy for all task executor plugins.
"""

import abc
import asyncio
import os
from collections.abc import Awaitable
from typing import Any, TypeVar

from basalt.core.dag.ast import StepSpec
from basalt.core.dag.exceptions import BasaltError
from basalt.core.engine.context import ExecutionContext
from basalt.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class ExecutorError(BasaltError):
    """Base exception for all step execution failures."""

    def __init__(
        self,
        step_id: str,
        executor_type: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = {"step_id": step_id, "executor_type": executor_type}
        if details:
            merged_details.update(details)
        super().__init__(
            message=f"Executor '{executor_type}' failed on step '{step_id}': {message}",
            code="EXECUTOR_ERROR",
            details=merged_details,
        )
        self.step_id = step_id
        self.executor_type = executor_type


class ExecutorTimeoutError(ExecutorError):
    """Raised when step execution exceeds configured timeout limit."""

    def __init__(
        self,
        step_id: str,
        executor_type: str,
        timeout_seconds: float,
    ) -> None:
        super().__init__(
            step_id=step_id,
            executor_type=executor_type,
            message=f"Execution timed out after {timeout_seconds} seconds.",
            details={"timeout_seconds": timeout_seconds},
        )
        self.timeout_seconds = timeout_seconds


class BaseExecutor(abc.ABC):
    """Abstract Base Class for all Basalt task executor plugins."""

    def __init__(self, executor_type: str) -> None:
        self.executor_type = executor_type

    @abc.abstractmethod
    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
    ) -> dict[str, Any]:
        """Asynchronously execute a task step within the given runtime context.

        Args:
            step: StepSpec definition AST model.
            context: Active ExecutionContext container.

        Returns:
            Dictionary payload returned by the step execution.

        Raises:
            ExecutorError: If step execution fails.
            ExecutorTimeoutError: If step execution times out.
        """
        pass

    def validate_step_spec(self, step: StepSpec) -> None:
        """Validate that step definition contains required parameters for this executor.

        Args:
            step: StepSpec AST model.

        Raises:
            ExecutorError: If required parameters are missing.
        """
        if step.executor_type.value != self.executor_type:
            raise ExecutorError(
                step_id=step.id,
                executor_type=self.executor_type,
                message=f"Step executor type '{step.executor_type.value}' does not match '{self.executor_type}'.",
            )

    async def execute_with_timeout(
        self,
        coro: Awaitable[T],
        timeout_seconds: float,
        step_id: str,
    ) -> T:
        """Wrap an async execution coroutine with timeout enforcement.

        Args:
            coro: Awaitable coroutine to execute.
            timeout_seconds: Timeout limit in seconds.
            step_id: Task step identifier.

        Returns:
            Return value of completed coroutine.

        Raises:
            ExecutorTimeoutError: If execution exceeds timeout limit.
        """
        if timeout_seconds <= 0.0:
            return await coro

        try:
            return await asyncio.wait_for(coro, timeout=timeout_seconds)
        except TimeoutError as exc:
            logger.error(
                f"Step '{step_id}' exceeded timeout limit of {timeout_seconds}s for executor '{self.executor_type}'"
            )
            raise ExecutorTimeoutError(
                step_id=step_id,
                executor_type=self.executor_type,
                timeout_seconds=timeout_seconds,
            ) from exc

    def merge_environment(
        self,
        step_env: dict[str, str] | None,
        context: ExecutionContext,
    ) -> dict[str, str]:
        """Merge system environment, context env, and step-specific environment variables.

        Priority order: step_env > context.env > os.environ.

        Args:
            step_env: Step-level environment variables dictionary.
            context: Active ExecutionContext container.

        Returns:
            Combined environment variables dictionary for execution.
        """
        combined = os.environ.copy()
        if context.env:
            combined.update({k: str(v) for k, v in context.env.items()})
        if step_env:
            combined.update({k: str(v) for k, v in step_env.items()})
        return combined

    def sanitize_output(self, raw_output: dict[str, Any]) -> dict[str, Any]:
        """Sanitize raw execution output dictionary for serializability.

        Args:
            raw_output: Raw dictionary output returned by step execution.

        Returns:
            Sanitized dictionary containing JSON-serializable types.
        """
        if not isinstance(raw_output, dict):
            return {"result": str(raw_output)}

        sanitized: dict[str, Any] = {}
        for k, v in raw_output.items():
            str_key = str(k)
            if isinstance(v, (str, int, float, bool, type(None))):
                sanitized[str_key] = v
            elif isinstance(v, (dict, list)):
                sanitized[str_key] = v
            else:
                sanitized[str_key] = str(v)

        return sanitized
