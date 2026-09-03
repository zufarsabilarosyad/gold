"""In-Process Python Callable Executor Subsystem Module for Basalt Engine.

Provides an executor for running in-process Python functions and registered callables
with automatic argument inspection, context injection, and exception wrapping.
"""

import asyncio
import importlib
import inspect
from collections.abc import Callable
from typing import Any

from basalt.core.dag.ast import StepSpec
from basalt.core.engine.context import ExecutionContext
from basalt.core.engine.evaluator import ExpressionEvaluator
from basalt.core.executors.base import BaseExecutor, ExecutorError
from basalt.utils.logger import get_logger

logger = get_logger(__name__)

# Global registry for in-process python callables
_CALLABLE_REGISTRY: dict[str, Callable[..., Any]] = {}


def register_python_callable(name: str, func: Callable[..., Any]) -> None:
    """Register an in-process python callable function for inline executor invocation.

    Args:
        name: Registry identifier name.
        func: Python function or coroutine callable.
    """
    _CALLABLE_REGISTRY[name] = func
    logger.debug(f"Registered python inline callable '{name}': {func.__name__}")


def clear_python_callable_registry() -> None:
    """Clear all registered python inline callables."""
    _CALLABLE_REGISTRY.clear()


class PythonInlineExecutor(BaseExecutor):
    """Executor plugin for executing in-process Python callables and module functions."""

    def __init__(self) -> None:
        super().__init__(executor_type="python_inline")

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
    ) -> dict[str, Any]:
        """Asynchronously execute Python function or callable.

        Args:
            step: StepSpec AST model.
            context: Active ExecutionContext.

        Returns:
            Dictionary output containing 'result' or custom dictionary returned by function.

        Raises:
            ExecutorError: If target function is not found or execution fails.
            ExecutorTimeoutError: If execution exceeds timeout limit.
        """
        self.validate_step_spec(step)

        # 1. Resolve python callable function
        func = self._resolve_callable(step, context)

        # 2. Inspect signature and resolve keyword arguments
        kwargs = self._prepare_kwargs(func, step, context)

        # 3. Inner execution wrapper
        async def _run_func() -> dict[str, Any]:
            try:
                if inspect.iscoroutinefunction(func):
                    try:
                        raw_result = await func(**kwargs)
                    except TypeError as err:
                        if "takes no keyword arguments" in str(err):
                            raw_result = await func(*kwargs.values())
                        else:
                            raise
                else:
                    # Run sync function in thread pool to prevent blocking event loop
                    loop = asyncio.get_running_loop()
                    try:
                        raw_result = await loop.run_in_executor(None, lambda: func(**kwargs))
                    except TypeError as err:
                        if "takes no keyword arguments" in str(err):
                            raw_result = await loop.run_in_executor(
                                None, lambda: func(*kwargs.values())
                            )
                        else:
                            raise

                logger.debug(f"Step '{step.id}' python inline function finished successfully")

                if isinstance(raw_result, dict):
                    return self.sanitize_output(raw_result)
                return self.sanitize_output({"result": raw_result})

            except Exception as exc:
                logger.error(
                    f"Step '{step.id}' python inline execution failed: {exc}",
                    exc_info=True,
                )
                raise ExecutorError(
                    step_id=step.id,
                    executor_type=self.executor_type,
                    message=f"Python function execution raised error: {exc}",
                ) from exc

        # 4. Timeout execution wrapper
        timeout = step.timeout_seconds if step.timeout_seconds else 300.0
        return await self.execute_with_timeout(
            _run_func(),
            timeout_seconds=timeout,
            step_id=step.id,
        )

    def _resolve_callable(
        self,
        step: StepSpec,
        context: ExecutionContext,
    ) -> Callable[..., Any]:
        """Resolve python callable from step params or global registry."""
        # 1. Check registered callable name
        if step.callable_name:
            name = ExpressionEvaluator.interpolate_string(step.callable_name, context)
            if name in _CALLABLE_REGISTRY:
                return _CALLABLE_REGISTRY[name]
            raise ExecutorError(
                step_id=step.id,
                executor_type=self.executor_type,
                message=f"Callable '{name}' not found in registered Python callables.",
            )

        # 2. Check module path and function name (e.g., module_path='math', function_name='sqrt')
        if step.module_path and step.function_name:
            mod_name = ExpressionEvaluator.interpolate_string(step.module_path, context)
            fn_name = ExpressionEvaluator.interpolate_string(step.function_name, context)
            try:
                module = importlib.import_module(mod_name)
                func = getattr(module, fn_name)
                if not callable(func):
                    raise ValueError(
                        f"Attribute '{fn_name}' in module '{mod_name}' is not callable."
                    )
                return func
            except Exception as exc:
                raise ExecutorError(
                    step_id=step.id,
                    executor_type=self.executor_type,
                    message=f"Failed to import function '{fn_name}' from module '{mod_name}': {exc}",
                ) from exc

        raise ExecutorError(
            step_id=step.id,
            executor_type=self.executor_type,
            message="Python inline step requires either 'callable_name' or 'module_path' + 'function_name'.",
        )

    def _prepare_kwargs(
        self,
        func: Callable[..., Any],
        step: StepSpec,
        context: ExecutionContext,
    ) -> dict[str, Any]:
        """Inspect function signature and build keyword arguments dictionary."""
        sig = inspect.signature(func)
        kwargs: dict[str, Any] = {}

        # 1. Process explicit parameters passed in step AST
        explicit_params = step.parameters or {}
        interpolated_params = ExpressionEvaluator.interpolate_value(explicit_params, context)

        for param_name, param in sig.parameters.items():
            # Inject context if requested in signature
            if param_name in ("context", "ctx", "execution_context"):
                kwargs[param_name] = context
                continue

            # Inject step_id if requested
            if param_name in ("step_id", "step"):
                kwargs[param_name] = step.id
                continue

            # Use explicit parameter if provided
            if param_name in interpolated_params:
                kwargs[param_name] = interpolated_params[param_name]
                continue

            # Try resolving parameter name directly from context
            val = context.resolve_variable_path(f"inputs.{param_name}")
            if val is not None:
                kwargs[param_name] = val
                continue

            # Default value check
            if param.default is inspect.Parameter.empty and param.kind not in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                logger.warning(
                    f"Parameter '{param_name}' for step '{step.id}' has no default value and was not supplied."
                )

        # Include remaining explicit kwargs if function accepts **kwargs
        has_var_keyword = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        if has_var_keyword and isinstance(interpolated_params, dict):
            for k, v in interpolated_params.items():
                if k not in kwargs:
                    kwargs[k] = v

        return kwargs
