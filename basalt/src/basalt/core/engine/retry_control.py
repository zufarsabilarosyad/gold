"""Reusable policy control for retryable workflow step execution.

The runner owns DAG ordering; this module owns the state machine that
turns a failed attempt into either a final result, a retry notification, or a
cancelled wait. Keeping it separate makes the public retry contract usable by
alternative runners without coupling it to a particular executor.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from basalt.core.dag.ast import RetryPolicySpec
from basalt.core.engine.state_machine import StepState
from basalt.core.resilience.backoff import BackoffPolicy, JitterStrategy
from basalt.utils.logger import get_logger

logger = get_logger(__name__)

AttemptResult = tuple[StepState, dict[str, Any], str | None]
AttemptCallable = Callable[[], Awaitable[AttemptResult]]
RetryCallback = Callable[[int, str | None, float], Awaitable[None]]


@dataclass(frozen=True)
class RetryStatus:
    """A serializable description of one decision made by a retry loop."""

    attempt: int
    retries_remaining: int
    state: StepState
    delay_seconds: float = 0.0
    cancelled: bool = False

    @property
    def terminal(self) -> bool:
        """Whether no further attempt may be started."""
        return self.cancelled or self.state in {
            StepState.COMPLETED,
            StepState.FAILED,
            StepState.TIMEOUT,
            StepState.CANCELLED,
        }

    def as_dict(self) -> dict[str, Any]:
        """Expose stable primitive values for hook and API consumers."""
        return {
            "attempt": self.attempt,
            "retries_remaining": self.retries_remaining,
            "state": self.state.value,
            "delay_seconds": self.delay_seconds,
            "cancelled": self.cancelled,
            "terminal": self.terminal,
        }


@dataclass
class RetryAuditRecord:
    """Audit log entry capturing details of an individual retry transition."""

    attempt: int
    state: StepState
    delay_seconds: float
    error_message: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Serialize audit record to dictionary."""
        return {
            "attempt": self.attempt,
            "state": self.state.value,
            "delay_seconds": self.delay_seconds,
            "error_message": self.error_message,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class RetryMetrics:
    """Summary metrics describing the outcome of a step retry sequence."""

    total_attempts: int = 0
    total_retries: int = 0
    total_delay_seconds: float = 0.0
    exhausted: bool = False
    recovered: bool = False
    cancelled: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert retry metrics into dictionary representation."""
        return {
            "total_attempts": self.total_attempts,
            "total_retries": self.total_retries,
            "total_delay_seconds": self.total_delay_seconds,
            "exhausted": self.exhausted,
            "recovered": self.recovered,
            "cancelled": self.cancelled,
        }


class RetrySchedule:
    """Translate a DAG retry specification into deterministic retry decisions."""

    def __init__(self, policy: RetryPolicySpec | None, enabled: bool) -> None:
        self.policy = policy or RetryPolicySpec()
        self.enabled = enabled
        self.max_retries = self.policy.max_retries if enabled else 0
        self.backoff = BackoffPolicy(
            initial_delay_seconds=self.policy.initial_delay_seconds,
            max_delay_seconds=self.policy.max_delay_seconds,
            backoff_factor=self.policy.backoff_factor,
            jitter=JitterStrategy.FULL if self.policy.jitter else JitterStrategy.NONE,
        )

    @property
    def max_attempts(self) -> int:
        """The initial attempt plus the configured retry budget."""
        return self.max_retries + 1

    def can_retry(self, attempt: int, state: StepState) -> bool:
        """Only failed and timed-out attempts consume the retry budget."""
        return state in {StepState.FAILED, StepState.TIMEOUT} and attempt <= self.max_retries

    def delay_for(self, attempt: int) -> float:
        """Return the wait after a failed one-based attempt."""
        if not self.can_retry(attempt, StepState.FAILED):
            return 0.0
        return self.backoff.calculate_delay(attempt)

    def status_for(self, attempt: int, state: StepState) -> RetryStatus:
        """Build the public status for an attempt outcome."""
        retrying = self.can_retry(attempt, state)
        return RetryStatus(
            attempt=attempt,
            retries_remaining=max(0, self.max_retries - attempt + 1) if retrying else 0,
            state=StepState.RETRYING if retrying else state,
            delay_seconds=self.delay_for(attempt) if retrying else 0.0,
        )

    def summary(self) -> dict[str, Any]:
        """Return high-level summary of retry schedule configuration."""
        return {
            "enabled": self.enabled,
            "max_retries": self.max_retries,
            "max_attempts": self.max_attempts,
            "initial_delay_seconds": self.policy.initial_delay_seconds,
            "max_delay_seconds": self.policy.max_delay_seconds,
            "backoff_factor": self.policy.backoff_factor,
            "jitter": self.policy.jitter,
        }


class CancellableSleeper:
    """Wait for a retry delay, returning early when workflow cancellation wins."""

    @staticmethod
    async def wait(cancel_event: asyncio.Event, delay_seconds: float) -> bool:
        """Return True when cancellation was signalled before the delay elapsed."""
        if cancel_event.is_set():
            return True
        if delay_seconds <= 0:
            await asyncio.sleep(0)
            return cancel_event.is_set()
        try:
            await asyncio.wait_for(cancel_event.wait(), timeout=delay_seconds)
            return True
        except asyncio.TimeoutError:
            return cancel_event.is_set()


class RetryController:
    """Run an async attempt callable according to a RetrySchedule.

    It intentionally has no knowledge of DAGs, executors, hooks, or storage.
    Callers provide a fresh attempt callable and optionally observe each retry.
    This keeps retry accounting consistent for subprocess, HTTP, and inline
    executors while allowing the workflow runner to own context mutation.
    """

    def __init__(self, schedule: RetrySchedule, cancel_event: asyncio.Event) -> None:
        self.schedule = schedule
        self.cancel_event = cancel_event
        self.history: list[RetryStatus] = []
        self.audit_log: list[RetryAuditRecord] = []

    @property
    def attempts_started(self) -> int:
        """Number of attempt callables invoked so far."""
        return len(self.history)

    @property
    def last_status(self) -> RetryStatus | None:
        """Most recent retry decision, if execution has started."""
        return self.history[-1] if self.history else None

    def get_metrics(self) -> RetryMetrics:
        """Compute aggregate retry metrics from execution history."""
        total_attempts = len(self.history)
        total_retries = max(0, total_attempts - 1)
        total_delay = sum(
            r.delay_seconds for r in self.history if r.state == StepState.RETRYING
        )
        is_cancelled = any(r.cancelled for r in self.history)
        is_recovered = (
            total_retries > 0
            and bool(self.history)
            and self.history[-1].state == StepState.COMPLETED
        )
        is_exhausted = (
            total_attempts >= self.schedule.max_attempts
            and bool(self.history)
            and self.history[-1].state in (StepState.FAILED, StepState.TIMEOUT)
        )
        return RetryMetrics(
            total_attempts=total_attempts,
            total_retries=total_retries,
            total_delay_seconds=total_delay,
            exhausted=is_exhausted,
            recovered=is_recovered,
            cancelled=is_cancelled,
        )

    def get_audit_trail(self) -> list[dict[str, Any]]:
        """Return list of serialized audit records."""
        return [record.to_dict() for record in self.audit_log]

    async def run(
        self, attempt_callable: AttemptCallable, on_retry: RetryCallback | None = None
    ) -> AttemptResult:
        """Run attempts until completion, exhaustion, or cancellation."""
        for attempt in range(1, self.schedule.max_attempts + 1):
            if self.cancel_event.is_set():
                status = RetryStatus(attempt - 1, 0, StepState.CANCELLED, cancelled=True)
                self.history.append(status)
                self.audit_log.append(
                    RetryAuditRecord(
                        attempt=attempt - 1,
                        state=StepState.CANCELLED,
                        delay_seconds=0.0,
                        error_message="Workflow execution cancelled by request.",
                    )
                )
                return StepState.CANCELLED, {}, "Workflow execution cancelled by request."

            state, output, error = await attempt_callable()

            if self.cancel_event.is_set():
                status = RetryStatus(attempt, 0, StepState.CANCELLED, cancelled=True)
                self.history.append(status)
                self.audit_log.append(
                    RetryAuditRecord(
                        attempt=attempt,
                        state=StepState.CANCELLED,
                        delay_seconds=0.0,
                        error_message="Workflow execution cancelled by request.",
                    )
                )
                return StepState.CANCELLED, {}, "Workflow execution cancelled by request."

            status = self.schedule.status_for(attempt, state)
            self.history.append(status)
            self.audit_log.append(
                RetryAuditRecord(
                    attempt=attempt,
                    state=status.state,
                    delay_seconds=status.delay_seconds,
                    error_message=error,
                )
            )

            if not self.schedule.can_retry(attempt, state):
                return state, output, error

            if on_retry is not None:
                await on_retry(attempt, error, status.delay_seconds)

            if await CancellableSleeper.wait(self.cancel_event, status.delay_seconds):
                cancelled = RetryStatus(attempt, 0, StepState.CANCELLED, cancelled=True)
                self.history.append(cancelled)
                self.audit_log.append(
                    RetryAuditRecord(
                        attempt=attempt,
                        state=StepState.CANCELLED,
                        delay_seconds=0.0,
                        error_message="Workflow execution cancelled by request.",
                    )
                )
                return StepState.CANCELLED, {}, "Workflow execution cancelled by request."

        return StepState.FAILED, {}, "Retry controller exhausted unexpectedly."
