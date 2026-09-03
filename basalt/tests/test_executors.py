"""Unit Tests for BaseExecutor, SubprocessExecutor, PythonInlineExecutor, and HTTPExecutor.

Validates shell execution, stdout/stderr stream parsing, environment variable merging,
JSON output parsing, in-process Python callables, argument injection, HTTP requests,
and timeout error guards.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from basalt.core.dag.ast import ExecutorType, StepSpec
from basalt.core.engine.context import ExecutionContext
from basalt.core.executors.base import BaseExecutor, ExecutorError, ExecutorTimeoutError
from basalt.core.executors.http import HTTPExecutor
from basalt.core.executors.inline import (
    PythonInlineExecutor,
    clear_python_callable_registry,
    register_python_callable,
)
from basalt.core.executors.subprocess import (
    SubprocessExecutor,
    parse_json_stdout_if_applicable,
    sanitize_env_vars,
)


class DummyExecutor(BaseExecutor):
    """Concrete Dummy Executor for BaseExecutor testing."""

    def __init__(self) -> None:
        super().__init__(executor_type="dummy")

    async def execute(self, step: StepSpec, context: ExecutionContext):
        return {"ok": True}


@pytest.fixture
def context() -> ExecutionContext:
    """Fixture returning populated ExecutionContext."""
    return ExecutionContext(
        run_id="run_test_exec",
        dag_id="test_dag",
        inputs={"name": "Alice", "count": 5},
        env={"GLOBAL_VAR": "global_value"},
    )


# --- BaseExecutor Tests ---


def test_base_executor_spec_validation() -> None:
    """Verify validate_step_spec raises ExecutorError when executor_type mismatches."""
    executor = DummyExecutor()
    mismatched_step = StepSpec(id="s1", executor_type=ExecutorType.SUBPROCESS, command="echo")

    with pytest.raises(ExecutorError) as exc_info:
        executor.validate_step_spec(mismatched_step)

    assert "does not match" in str(exc_info.value.message)


def test_base_executor_sanitize_output() -> None:
    """Verify sanitize_output handles non-serializable objects and non-dict values."""
    executor = DummyExecutor()

    class CustomObj:
        def __str__(self) -> str:
            return "custom_str"

    raw = {"str": "hello", "int": 10, "custom": CustomObj()}
    sanitized = executor.sanitize_output(raw)

    assert sanitized["str"] == "hello"
    assert sanitized["int"] == 10
    assert sanitized["custom"] == "custom_str"


# --- SubprocessExecutor Tests ---


@pytest.mark.asyncio
async def test_subprocess_executor_success(context: ExecutionContext) -> None:
    """Verify successful shell command execution."""
    executor = SubprocessExecutor()
    step = StepSpec(
        id="step_echo",
        executor_type=ExecutorType.SUBPROCESS,
        command='echo "Hello ${inputs.name}"',
    )

    result = await executor.execute(step, context)

    assert result["exit_code"] == 0
    assert "Hello Alice" in result["stdout"]
    assert result["stderr"] == ""


@pytest.mark.asyncio
async def test_subprocess_executor_failure(context: ExecutionContext) -> None:
    """Verify non-zero exit code raises ExecutorError."""
    executor = SubprocessExecutor()
    step = StepSpec(
        id="step_fail",
        executor_type=ExecutorType.SUBPROCESS,
        command="exit 42",
    )

    with pytest.raises(ExecutorError) as exc_info:
        await executor.execute(step, context)

    assert exc_info.value.code == "EXECUTOR_ERROR"
    assert exc_info.value.details["exit_code"] == 42


@pytest.mark.asyncio
async def test_subprocess_executor_env_and_cwd(tmp_path: Path, context: ExecutionContext) -> None:
    """Verify environment variable propagation and working directory."""
    executor = SubprocessExecutor()
    step = StepSpec(
        id="step_pwd_env",
        executor_type=ExecutorType.SUBPROCESS,
        command="pwd && echo $STEP_ENV",
        env={"STEP_ENV": "step_specific_value"},
        working_dir=str(tmp_path),
    )

    result = await executor.execute(step, context)

    assert result["exit_code"] == 0
    assert "step_specific_value" in result["stdout"]


@pytest.mark.asyncio
async def test_subprocess_executor_json_parsing(context: ExecutionContext) -> None:
    """Verify automatic JSON parsing of stdout payload."""
    executor = SubprocessExecutor()
    step = StepSpec(
        id="step_json",
        executor_type=ExecutorType.SUBPROCESS,
        command='echo \'{"status": "ok", "items": [1, 2]}\'',
    )

    result = await executor.execute(step, context)

    assert result["exit_code"] == 0
    assert result["json"] == {"status": "ok", "items": [1, 2]}
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_subprocess_executor_timeout(context: ExecutionContext) -> None:
    """Verify command exceeding timeout raises ExecutorTimeoutError."""
    executor = SubprocessExecutor()
    step = StepSpec(
        id="step_sleep",
        executor_type=ExecutorType.SUBPROCESS,
        command="sleep 2",
        timeout_seconds=0.1,
    )

    with pytest.raises(ExecutorTimeoutError) as exc_info:
        await executor.execute(step, context)

    assert exc_info.value.timeout_seconds == 0.1


# --- PythonInlineExecutor Tests ---


@pytest.mark.asyncio
async def test_python_inline_sync_function(context: ExecutionContext) -> None:
    """Verify executing registered synchronous Python function."""
    clear_python_callable_registry()

    def add_numbers(a: int, b: int) -> int:
        return a + b

    register_python_callable("add", add_numbers)

    executor = PythonInlineExecutor()
    step = StepSpec(
        id="step_add",
        executor_type=ExecutorType.PYTHON_INLINE,
        callable_name="add",
        parameters={"a": 10, "b": 20},
    )

    result = await executor.execute(step, context)
    assert result["result"] == 30


@pytest.mark.asyncio
async def test_python_inline_async_coroutine(context: ExecutionContext) -> None:
    """Verify executing registered asynchronous coroutine function with dict output."""
    clear_python_callable_registry()

    async def fetch_user(name: str) -> dict:
        return {"user": name, "authenticated": True}

    register_python_callable("get_user", fetch_user)

    executor = PythonInlineExecutor()
    step = StepSpec(
        id="step_user",
        executor_type=ExecutorType.PYTHON_INLINE,
        callable_name="get_user",
        parameters={"name": "${inputs.name}"},
    )

    result = await executor.execute(step, context)
    assert result["user"] == "Alice"
    assert result["authenticated"] is True


@pytest.mark.asyncio
async def test_python_inline_module_import(context: ExecutionContext) -> None:
    """Verify executing Python stdlib module function via module_path and function_name."""
    executor = PythonInlineExecutor()
    step = StepSpec(
        id="step_sqrt",
        executor_type=ExecutorType.PYTHON_INLINE,
        module_path="math",
        function_name="sqrt",
        parameters={"x": 16},
    )

    result = await executor.execute(step, context)
    assert result["result"] == 4.0


@pytest.mark.asyncio
async def test_python_inline_context_injection(context: ExecutionContext) -> None:
    """Verify automatic context injection into function kwargs."""
    clear_python_callable_registry()

    def inspect_ctx(ctx: ExecutionContext) -> str:
        return ctx.run_id

    register_python_callable("inspect", inspect_ctx)

    executor = PythonInlineExecutor()
    step = StepSpec(
        id="step_inspect",
        executor_type=ExecutorType.PYTHON_INLINE,
        callable_name="inspect",
    )

    result = await executor.execute(step, context)
    assert result["result"] == "run_test_exec"


@pytest.mark.asyncio
async def test_python_inline_unregistered_error(context: ExecutionContext) -> None:
    """Verify unregistered callable name raises ExecutorError."""
    executor = PythonInlineExecutor()
    step = StepSpec(
        id="step_ghost",
        executor_type=ExecutorType.PYTHON_INLINE,
        callable_name="non_existent_func",
    )

    with pytest.raises(ExecutorError) as exc_info:
        await executor.execute(step, context)

    assert "not found" in str(exc_info.value.message).lower()


# --- HTTPExecutor Tests ---


def test_http_executor_helpers(context: ExecutionContext) -> None:
    """Verify HTTP method validation and header construction helpers."""
    executor = HTTPExecutor()

    assert executor.validate_method("get", "step1") == "GET"
    assert executor.validate_method("post", "step1") == "POST"

    with pytest.raises(ExecutorError):
        executor.validate_method("INVALID_VERB", "step1")

    headers = executor.build_headers({"Auth": "Bearer ${env.GLOBAL_VAR}"}, context)
    assert headers["Auth"] == "Bearer global_value"
    assert "User-Agent" in headers


@pytest.mark.asyncio
async def test_http_executor_invalid_url(context: ExecutionContext) -> None:
    """Verify invalid URL format raises ValidationError or ExecutorError."""
    executor = HTTPExecutor()
    with pytest.raises((ValidationError, ExecutorError)) as exc_info:
        step = StepSpec(
            id="step_bad_url",
            executor_type=ExecutorType.HTTP,
            url="ftp://invalid_scheme",
        )
        await executor.execute(step, context)

    assert "invalid" in str(exc_info.value).lower()


def test_parse_json_stdout_utility() -> None:
    """Verify parse_json_stdout_if_applicable utility parser."""
    assert parse_json_stdout_if_applicable('{"a": 1}') == {"a": 1}
    assert parse_json_stdout_if_applicable("[1, 2, 3]") == [1, 2, 3]
    assert parse_json_stdout_if_applicable("plain text") is None
    assert parse_json_stdout_if_applicable("") is None
    assert sanitize_env_vars({"a": "b", 1: 2}) == {"a": "b", "1": "2"}
