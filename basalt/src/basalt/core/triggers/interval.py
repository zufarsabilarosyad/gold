"""Fixed-Interval Timer Trigger Subsystem Module for Basalt Engine.

Provides IntervalTrigger and IntervalCalculator implementing fixed-interval timer evaluations
(seconds, minutes, hours, days), fire readiness checks, and next fire time calculations.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from basalt.core.dag.ast import TriggerSpec, TriggerType
from basalt.core.triggers.base import BaseTrigger, TriggerEvent
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class IntervalCalculator:
    """Utility helper converting time unit intervals into seconds."""

    @staticmethod
    def to_seconds(
        seconds: float = 0.0,
        minutes: float = 0.0,
        hours: float = 0.0,
        days: float = 0.0,
    ) -> float:
        """Convert multi-unit duration into total seconds.

        Returns:
            Total float seconds value.
        """
        total = (
            max(0.0, seconds)
            + max(0.0, minutes) * 60.0
            + max(0.0, hours) * 3600.0
            + max(0.0, days) * 86400.0
        )
        return max(0.1, total)

    @staticmethod
    def format_interval(seconds: float) -> str:
        """Format seconds into human-readable duration summary string."""
        if seconds < 60.0:
            return f"{seconds:.1f}s"
        elif seconds < 3600.0:
            return f"{seconds / 60.0:.1f}m"
        elif seconds < 86400.0:
            return f"{seconds / 3600.0:.1f}h"
        else:
            return f"{seconds / 86400.0:.1f}d"

    @staticmethod
    def calculate_elapsed_seconds(
        start_time: datetime,
        end_time: datetime | None = None,
    ) -> float:
        """Calculate elapsed seconds between start_time and end_time (defaults to UTC now)."""
        ref_end = end_time or datetime.now(UTC)
        return max(0.0, (ref_end - start_time).total_seconds())


class IntervalTrigger(BaseTrigger):
    """Event trigger driven by fixed time interval delays."""

    def __init__(self, trigger_spec: TriggerSpec, dag_id: str) -> None:
        super().__init__(trigger_spec, dag_id)
        if not trigger_spec.interval_seconds or trigger_spec.interval_seconds <= 0:
            raise ValueError(
                f"IntervalTrigger '{trigger_spec.id}' requires positive 'interval_seconds'."
            )
        self.interval_seconds = float(trigger_spec.interval_seconds)
        self.start_time: datetime = datetime.now(UTC)
        self.fire_count: int = 0

    def set_interval(self, seconds: float) -> None:
        """Dynamically update interval duration in seconds."""
        if seconds <= 0:
            raise ValueError("Interval seconds must be positive.")
        self.interval_seconds = float(seconds)
        logger.info(
            f"IntervalTrigger '{self.spec.id}' updated interval to {self.interval_seconds}s"
        )

    def reset(self) -> None:
        """Reset internal start and last fired timestamps."""
        self.start_time = datetime.now(UTC)
        self.last_fired_at = None
        self.fire_count = 0
        logger.info(f"IntervalTrigger '{self.spec.id}' reset fire timer")

    def should_fire(self, current_time: datetime | None = None) -> bool:
        """Check if elapsed time since last fire (or start time) exceeds interval_seconds."""
        if not self.is_active:
            return False

        now = current_time or datetime.now(UTC)
        reference_time = self.last_fired_at or self.start_time
        elapsed_seconds = (now - reference_time).total_seconds()

        return elapsed_seconds >= self.interval_seconds

    def is_due(self, current_time: datetime | None = None) -> bool:
        """Alias for should_fire method."""
        return self.should_fire(current_time)

    def get_next_fire_time(self, current_time: datetime | None = None) -> datetime | None:
        """Calculate next scheduled fire timestamp for this interval trigger."""
        if not self.is_active:
            return None

        now = current_time or datetime.now(UTC)
        reference_time = self.last_fired_at or self.start_time
        next_time = reference_time + timedelta(seconds=self.interval_seconds)

        # If next_time is in the past relative to now, catch up to next interval boundary
        if next_time < now:
            overdue_seconds = (now - reference_time).total_seconds()
            intervals_passed = int(overdue_seconds // self.interval_seconds) + 1
            next_time = reference_time + timedelta(seconds=intervals_passed * self.interval_seconds)

        return next_time

    def get_fire_stats(self) -> dict[str, Any]:
        """Retrieve timer statistics dict."""
        return {
            "trigger_id": self.spec.id,
            "dag_id": self.dag_id,
            "interval_seconds": self.interval_seconds,
            "fire_count": self.fire_count,
            "last_fired_at": self.last_fired_at.isoformat() if self.last_fired_at else None,
        }

    def evaluate(
        self,
        current_time: datetime | None = None,
        extra_payload: dict[str, Any] | None = None,
    ) -> TriggerEvent | None:
        """Evaluate interval trigger and attach interval metadata to payload."""
        now = current_time or datetime.now(UTC)
        if self.should_fire(now):
            self.fire_count += 1

        interval_meta = {
            "interval_seconds": self.interval_seconds,
            "interval_formatted": IntervalCalculator.format_interval(self.interval_seconds),
            "fire_count": self.fire_count,
        }
        if extra_payload:
            interval_meta.update(extra_payload)

        return super().evaluate(current_time=now, extra_payload=interval_meta)


def create_interval_trigger(
    trigger_id: str,
    dag_id: str,
    interval_seconds: float,
    enabled: bool = True,
) -> IntervalTrigger:
    """Helper shortcut function to create an IntervalTrigger instance."""
    spec = TriggerSpec(
        id=trigger_id,
        type=TriggerType.INTERVAL,
        interval_seconds=interval_seconds,
        enabled=enabled,
    )
    return IntervalTrigger(trigger_spec=spec, dag_id=dag_id)
