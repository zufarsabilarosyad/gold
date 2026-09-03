"""Step Execution Retry Handler & Resilience Subsystem Module for Basalt Engine.

Provides RetryHandler and @retryable decorator wrapping step executions with attempt counting,
backoff delay enforcement, exception filtering, and retry exhaustion handling.
"""

import asyncio
import functools
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import BaseModel, Field

from basalt.core.dag.ast import RetryPolicySpec
from basalt.core.dag.exceptions import BasaltError
from basalt.core.resilience.backoff import BackoffCalculator, BackoffStrategy, JitterStrategy
from basalt.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class RetryAttemptRecord(BaseModel):
    """Log record for an individual retry attempt failure."""

    attempt_number: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    delay_seconds: float
    exception_type: str
    exception_message: str


class RetryExhaustedError(BasaltError):
    """Raised when step execution fails after exhausting all retry attempts."""

    def __init__(
        self,
        step_id: str,
        attempts: int,
        last_exception: Exception,
        attempt_history: list[RetryAttemptRecord] | None = None,
    ) -> None:
        super().__init__(
            message=f"Step '{step_id}' failed after {attempts} attempts. Last error: {last_exception}",
            code="RETRY_EXHAUSTED",
            details={
                "step_id": step_id,
                "attempts": attempts,
                "last_exception_type": type(last_exception).__name__,
                "last_exception_message": str(last_exception),
                "attempt_history_count": len(attempt_history) if attempt_history else 0,
            },
        )
        self.step_id = step_id
        self.attempts = attempts
        self.last_exception = last_exception
        self.attempt_history = attempt_history or []


class RetryHandler:
    """Async retry execution handler for resilient task execution."""

    @staticmethod
    async def execute_with_retry(
        coro_fn: Callable[[], Awaitable[T]],
        retry_policy: RetryPolicySpec | None = None,
        step_id: str = "unnamed_step",
        retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
        on_retry_callback: Callable[[int, Exception, float], None] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> T:
        """Execute async function coroutine with retry policy enforcement.

        Args:
            coro_fn: Async zero-argument callable returning Awaitable[T].
            retry_policy: RetryPolicySpec AST object defining max_retries, delays, and backoff.
            step_id: Step identifier for log messages.
            retryable_exceptions: Tuple of Exception types eligible for retry.
            on_retry_callback: Optional callback invoked on retry attempt failure.
            cancel_event: Optional asyncio.Event for cancellation observation.

        Returns:
            Result object returned by successful invocation of coro_fn.

        Raises:
            RetryExhaustedError: If initial execution and all retry attempts fail.
            Exception: Re-raises non-retryable exception immediately.
        """
        policy = retry_policy or RetryPolicySpec()
        max_attempts = 1 + max(0, policy.max_retries)

        attempt = 1
        last_exc: Exception | None = None
        attempt_history: list[RetryAttemptRecord] = []

        while attempt <= max_attempts:
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError(f"Step '{step_id}' cancelled before attempt {attempt}.")

            try:
                if attempt > 1:
                    logger.info(
                        f"Executing retry attempt {attempt - 1}/{policy.max_retries} for step '{step_id}'"
                    )

                return await coro_fn()

            except retryable_exceptions as exc:
                last_exc = exc
                logger.warning(
                    f"Step '{step_id}' failed on attempt {attempt}/{max_attempts}: {exc}"
                )

                if attempt >= max_attempts:
                    logger.error(
                        f"Step '{step_id}' exhausted all {policy.max_retries} retry attempts."
                    )
                    break

                # Calculate exponential backoff sleep delay
                delay = BackoffCalculator.calculate_delay(
                    attempt=attempt,
                    initial_delay_seconds=policy.initial_delay_seconds,
                    max_delay_seconds=policy.max_delay_seconds,
                    backoff_factor=policy.backoff_factor,
                    strategy=BackoffStrategy.EXPONENTIAL,
                    jitter=JitterStrategy.FULL if policy.jitter else JitterStrategy.NONE,
                )

                attempt_history.append(
                    RetryAttemptRecord(
                        attempt_number=attempt,
                        delay_seconds=delay,
                        exception_type=type(exc).__name__,
                        exception_message=str(exc),
                    )
                )

                if on_retry_callback:
                    try:
                        on_retry_callback(attempt, exc, delay)
                    except Exception as cb_exc:
                        logger.warning(
                            f"Retry callback raised error for step '{step_id}': {cb_exc}"
                        )

                logger.debug(f"Step '{step_id}' sleeping {delay:.3f}s before attempt {attempt + 1}")
                if cancel_event:
                    if cancel_event.is_set():
                        raise asyncio.CancelledError(f"Step '{step_id}' retry wait cancelled.")
                    try:
                        await asyncio.wait_for(cancel_event.wait(), timeout=delay)
                        raise asyncio.CancelledError(f"Step '{step_id}' retry wait cancelled.")
                    except asyncio.TimeoutError:
                        pass
                else:
                    await asyncio.sleep(delay)
                attempt += 1

            except Exception as non_retryable_exc:
                logger.error(
                    f"Step '{step_id}' encountered non-retryable exception: {non_retryable_exc}"
                )
                raise

        raise RetryExhaustedError(
            step_id=step_id,
            attempts=max_attempts,
            last_exception=last_exc or RuntimeError("Unknown retry failure"),
            attempt_history=attempt_history,
        )

    @staticmethod
    async def execute_step_with_policy(
        step_fn: Callable[[int], Awaitable[T]],
        retry_policy: RetryPolicySpec | None = None,
        step_id: str = "unnamed_step",
        cancel_event: asyncio.Event | None = None,
        on_attempt_start: Callable[[int], Any] | None = None,
        on_attempt_failure: Callable[[int, Exception, float], Any] | None = None,
    ) -> T:
        """Execute step callable with attempt index tracking, hooks, and cancellation observation."""
        policy = retry_policy or RetryPolicySpec()
        max_attempts = 1 + max(0, policy.max_retries)
        attempt = 1
        last_exc: Exception | None = None
        attempt_history: list[RetryAttemptRecord] = []

        while attempt <= max_attempts:
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError(f"Execution cancelled before attempt {attempt}")

            if on_attempt_start:
                res = on_attempt_start(attempt)
                if asyncio.iscoroutine(res):
                    await res

            try:
                return await step_fn(attempt)
            except Exception as exc:
                last_exc = exc
                if attempt >= max_attempts:
                    break

                delay = BackoffCalculator.calculate_delay(
                    attempt=attempt,
                    initial_delay_seconds=policy.initial_delay_seconds,
                    max_delay_seconds=policy.max_delay_seconds,
                    backoff_factor=policy.backoff_factor,
                    strategy=BackoffStrategy.EXPONENTIAL,
                    jitter=JitterStrategy.FULL if policy.jitter else JitterStrategy.NONE,
                )

                attempt_history.append(
                    RetryAttemptRecord(
                        attempt_number=attempt,
                        delay_seconds=delay,
                        exception_type=type(exc).__name__,
                        exception_message=str(exc),
                    )
                )

                if on_attempt_failure:
                    cb_res = on_attempt_failure(attempt, exc, delay)
                    if asyncio.iscoroutine(cb_res):
                        await cb_res

                if cancel_event:
                    if cancel_event.is_set():
                        raise asyncio.CancelledError("Cancelled during retry backoff")
                    try:
                        await asyncio.wait_for(cancel_event.wait(), timeout=delay)
                        raise asyncio.CancelledError("Cancelled during retry backoff")
                    except asyncio.TimeoutError:
                        pass
                else:
                    await asyncio.sleep(delay)

                attempt += 1

        raise RetryExhaustedError(
            step_id=step_id,
            attempts=max_attempts,
            last_exception=last_exc or RuntimeError("Unknown failure"),
            attempt_history=attempt_history,
        )


    @staticmethod
    def execute_sync_with_retry(
        sync_fn: Callable[[], T],
        retry_policy: RetryPolicySpec | None = None,
        step_id: str = "unnamed_step",
        retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    ) -> T:
        """Execute synchronous function with retry policy enforcement and time.sleep."""
        policy = retry_policy or RetryPolicySpec()
        max_attempts = 1 + max(0, policy.max_retries)

        attempt = 1
        last_exc: Exception | None = None

        while attempt <= max_attempts:
            try:
                return sync_fn()
            except retryable_exceptions as exc:
                last_exc = exc
                if attempt >= max_attempts:
                    break

                delay = BackoffCalculator.calculate_delay(
                    attempt=attempt,
                    initial_delay_seconds=policy.initial_delay_seconds,
                    max_delay_seconds=policy.max_delay_seconds,
                    backoff_factor=policy.backoff_factor,
                    strategy=BackoffStrategy.EXPONENTIAL,
                    jitter=JitterStrategy.FULL if policy.jitter else JitterStrategy.NONE,
                )
                time.sleep(delay)
                attempt += 1

        raise RetryExhaustedError(
            step_id=step_id,
            attempts=max_attempts,
            last_exception=last_exc or RuntimeError("Unknown sync retry failure"),
        )


def retryable(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator for wrapping async functions with automatic retry logic.

    Args:
        max_retries: Maximum retry attempts.
        initial_delay: Initial sleep delay in seconds.
        max_delay: Maximum sleep delay in seconds.
        backoff_factor: Exponential growth factor.
        retryable_exceptions: Exception types to catch and retry.

    Returns:
        Decorated async function wrapper.
    """
    policy = RetryPolicySpec(
        max_retries=max_retries,
        initial_delay_seconds=initial_delay,
        max_delay_seconds=max_delay,
        backoff_factor=backoff_factor,
    )

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await RetryHandler.execute_with_retry(
                coro_fn=lambda: func(*args, **kwargs),
                retry_policy=policy,
                step_id=func.__name__,
                retryable_exceptions=retryable_exceptions,
            )

        return wrapper

    return decorator
