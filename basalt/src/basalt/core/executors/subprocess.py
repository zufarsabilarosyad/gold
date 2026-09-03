"""Asynchronous Subprocess Shell Command Executor Subsystem Module for Basalt Engine.

Handles shell command execution, environment variable propagation, template string interpolation,
working directory security guards, stdout/stderr stream capture, exit code validation,
and automatic JSON output parsing.
"""

import asyncio
import json
from typing import Any

from basalt.core.dag.ast import StepSpec
from basalt.core.engine.context import ExecutionContext
from basalt.core.engine.evaluator import ExpressionEvaluator
from basalt.core.executors.base import BaseExecutor, ExecutorError
from basalt.utils.logger import get_logger
from basalt.utils.validators import validate_safe_path

logger = get_logger(__name__)


class SubprocessExecutor(BaseExecutor):
    """Executor plugin for running shell subprocess commands asynchronously."""

    def __init__(self) -> None:
        super().__init__(executor_type="subprocess")

    def validate_command(self, step: StepSpec) -> str:
        """Validate step command string and check for null byte injection hazards.

        Args:
            step: StepSpec AST model.

        Returns:
            Validated raw command string.

        Raises:
            ExecutorError: If command is empty or contains illegal characters.
        """
        if not step.command or not step.command.strip():
            raise ExecutorError(
                step_id=step.id,
                executor_type=self.executor_type,
                message="Subprocess step missing required 'command' string.",
            )

        if "\x00" in step.command:
            raise ExecutorError(
                step_id=step.id,
                executor_type=self.executor_type,
                message="Subprocess command contains illegal null byte character.",
            )

        return step.command

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
    ) -> dict[str, Any]:
        """Asynchronously execute shell command specified in step.command.

        Args:
            step: StepSpec AST model.
            context: Active ExecutionContext.

        Returns:
            Dictionary output containing 'stdout', 'stderr', 'exit_code', 'command', and optional 'json'.

        Raises:
            ExecutorError: If command fails or returns non-zero exit code.
            ExecutorTimeoutError: If execution exceeds timeout_seconds.
        """
        self.validate_step_spec(step)
        raw_cmd = self.validate_command(step)

        # 1. Interpolate template expressions in command string (e.g. ${inputs.foo})
        interpolated_cmd = ExpressionEvaluator.interpolate_string(raw_cmd, context)
        logger.debug(f"Step '{step.id}' executing subprocess command: '{interpolated_cmd}'")

        # 2. Merge environment variables
        env = self.merge_environment(step.env, context)

        # 3. Validate and resolve working directory if specified
        cwd: str | None = None
        if step.working_dir:
            interpolated_cwd = ExpressionEvaluator.interpolate_string(step.working_dir, context)
            safe_cwd = validate_safe_path(interpolated_cwd, allow_absolute=True)
            if not safe_cwd.exists() or not safe_cwd.is_dir():
                raise ExecutorError(
                    step_id=step.id,
                    executor_type=self.executor_type,
                    message=f"Working directory '{safe_cwd}' does not exist or is not a directory.",
                )
            cwd = str(safe_cwd.resolve())

        # 4. Asynchronous command execution wrapper
        async def _run_command() -> dict[str, Any]:
            try:
                stdout, stderr, exit_code = await run_subprocess_command(
                    command=interpolated_cmd,
                    env=env,
                    cwd=cwd,
                )

                logger.debug(f"Step '{step.id}' subprocess finished with exit code {exit_code}")

                if exit_code != 0:
                    error_msg = (
                        f"Command '{interpolated_cmd}' exited with code {exit_code}. "
                        f"Stderr: {stderr[:500]}"
                    )
                    raise ExecutorError(
                        step_id=step.id,
                        executor_type=self.executor_type,
                        message=error_msg,
                        details={
                            "exit_code": exit_code,
                            "stdout": stdout,
                            "stderr": stderr,
                            "command": interpolated_cmd,
                        },
                    )

                output_payload: dict[str, Any] = {
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": exit_code,
                    "command": interpolated_cmd,
                }

                # Attempt automatic JSON parsing of stdout if payload is valid JSON object
                json_data = parse_json_stdout_if_applicable(stdout)
                if json_data is not None:
                    output_payload["json"] = json_data
                    if isinstance(json_data, dict):
                        for k, v in json_data.items():
                            if k not in output_payload:
                                output_payload[k] = v

                return self.sanitize_output(output_payload)

            except ExecutorError:
                raise
            except Exception as exc:
                raise ExecutorError(
                    step_id=step.id,
                    executor_type=self.executor_type,
                    message=f"Failed to launch process: {exc}",
                ) from exc

        # 5. Execute with timeout wrapper
        timeout = step.timeout_seconds if step.timeout_seconds else 300.0
        return await self.execute_with_timeout(
            _run_command(),
            timeout_seconds=timeout,
            step_id=step.id,
        )


async def run_subprocess_command(
    command: str,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> tuple[str, str, int]:
    """Execute a shell command string asynchronously and return (stdout, stderr, exit_code).

    Args:
        command: Shell command line string.
        env: Environment variables map.
        cwd: Working directory path string.

    Returns:
        Tuple of (stdout_text, stderr_text, exit_code).
    """
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=cwd,
    )

    stdout_bytes, stderr_bytes = await process.communicate()
    stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
    exit_code = process.returncode if process.returncode is not None else -1

    return stdout, stderr, exit_code


def parse_json_stdout_if_applicable(stdout: str) -> Any | None:
    """Try parsing stdout string as JSON if it starts with '{' or '['.

    Args:
        stdout: Raw stdout string.

    Returns:
        Parsed JSON object or None if unparseable.
    """
    s = stdout.strip()
    if not s or not (s.startswith("{") or s.startswith("[")):
        return None

    try:
        return json.loads(s)
    except Exception:
        return None


def sanitize_env_vars(env: dict[str, str]) -> dict[str, str]:
    """Filter out non-string keys and values from environment variables dictionary."""
    return {str(k): str(v) for k, v in env.items() if k and v is not None}
