"""Time Management and High-Precision Timer Utilities Module for Basalt Workflow Engine.

Provides UTC datetime utilities, ISO-8601 parsing/formatting, epoch conversion,
timeout calculations, and high-precision execution timers.
"""

import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from dateutil import parser as dateutil_parser


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime.

    Returns:
        datetime object pinned to timezone.utc.
    """
    return datetime.now(UTC)


def now_timestamp() -> float:
    """Return current UTC epoch timestamp in seconds.

    Returns:
        Float timestamp representing seconds since Unix epoch.
    """
    return utc_now().timestamp()


def now_isoformat(microseconds: bool = True) -> str:
    """Return current UTC timestamp in canonical ISO-8601 format.

    Args:
        microseconds: Whether to include microsecond resolution.

    Returns:
        ISO-8601 string like '2026-08-06T21:38:47.123456Z'.
    """
    now = utc_now()
    if not microseconds:
        now = now.replace(microsecond=0)
    return now.isoformat().replace("+00:00", "Z")


def parse_isoformat(timestamp_str: str) -> datetime:
    """Parse an ISO-8601 timestamp string into a timezone-aware UTC datetime.

    Args:
        timestamp_str: ISO-8601 formatted datetime string.

    Returns:
        Timezone-aware UTC datetime object.

    Raises:
        ValueError: If timestamp string cannot be parsed.
    """
    if not timestamp_str or not isinstance(timestamp_str, str):
        raise ValueError("Invalid timestamp string provided.")

    try:
        dt = dateutil_parser.isoparse(timestamp_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        else:
            dt = dt.astimezone(UTC)
        return dt
    except Exception as exc:
        raise ValueError(f"Failed to parse ISO timestamp '{timestamp_str}': {exc}") from exc


def datetime_to_epoch(dt: datetime) -> float:
    """Convert datetime object to float epoch seconds.

    Args:
        dt: Datetime object.

    Returns:
        Float epoch timestamp.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def epoch_to_datetime(epoch: float) -> datetime:
    """Convert float epoch seconds to timezone-aware UTC datetime.

    Args:
        epoch: Float epoch seconds.

    Returns:
        Timezone-aware UTC datetime object.
    """
    return datetime.fromtimestamp(epoch, tz=UTC)


def format_duration(seconds: float) -> str:
    """Format duration in seconds into human-readable string.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string like '120ms', '3.45s', or '2m 15s'.
    """
    if seconds < 0.001:
        return "<1ms"
    if seconds < 1.0:
        return f"{seconds * 1000.0:.1f}ms"
    if seconds < 60.0:
        return f"{seconds:.2f}s"

    minutes = int(seconds // 60)
    rem_seconds = seconds % 60
    if minutes < 60:
        return f"{minutes}m {rem_seconds:.1f}s"

    hours = int(minutes // 60)
    rem_minutes = minutes % 60
    return f"{hours}h {rem_minutes}m"


def is_expired(start_time: datetime | float, timeout_seconds: float) -> bool:
    """Determine if a timeout period has elapsed relative to a start time.

    Args:
        start_time: Starting UTC datetime or epoch float.
        timeout_seconds: Timeout threshold duration in seconds.

    Returns:
        True if elapsed time exceeds timeout_seconds.
    """
    if timeout_seconds <= 0:
        return False

    if isinstance(start_time, datetime):
        start_epoch = datetime_to_epoch(start_time)
    else:
        start_epoch = start_time

    return (now_timestamp() - start_epoch) >= timeout_seconds


def remaining_time(start_time: datetime | float, timeout_seconds: float) -> float:
    """Calculate remaining seconds before a timeout expires.

    Args:
        start_time: Starting UTC datetime or epoch float.
        timeout_seconds: Timeout threshold duration in seconds.

    Returns:
        Remaining seconds (>= 0.0). Returns 0.0 if already expired.
    """
    if timeout_seconds <= 0:
        return 0.0

    if isinstance(start_time, datetime):
        start_epoch = datetime_to_epoch(start_time)
    else:
        start_epoch = start_time

    elapsed = now_timestamp() - start_epoch
    remaining = timeout_seconds - elapsed
    return max(0.0, remaining)


class HighPrecisionTimer:
    """High-precision execution timer using monotonic perf_counter."""

    def __init__(self) -> None:
        self._start_time: float | None = None
        self._end_time: float | None = None

    def start(self) -> "HighPrecisionTimer":
        """Start or restart the timer."""
        self._start_time = time.perf_counter()
        self._end_time = None
        return self

    def stop(self) -> float:
        """Stop the timer and return elapsed time in seconds.

        Returns:
            Elapsed time in seconds.
        """
        if self._start_time is None:
            raise RuntimeError("Timer was not started.")
        self._end_time = time.perf_counter()
        return self.elapsed_seconds

    @property
    def elapsed_seconds(self) -> float:
        """Return elapsed duration in seconds."""
        if self._start_time is None:
            return 0.0
        end = self._end_time if self._end_time is not None else time.perf_counter()
        return end - self._start_time

    @property
    def elapsed_ms(self) -> float:
        """Return elapsed duration in milliseconds."""
        return self.elapsed_seconds * 1000.0

    def __enter__(self) -> "HighPrecisionTimer":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()


@contextmanager
def measure_time() -> Generator[HighPrecisionTimer, None, None]:
    """Context manager for measuring code block execution duration.

    Usage:
        with measure_time() as t:
            do_work()
        print(f"Executed in {t.elapsed_ms:.2f} ms")
    """
    timer = HighPrecisionTimer()
    timer.start()
    try:
        yield timer
    finally:
        timer.stop()
