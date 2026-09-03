"""5-Field Cron Expression Evaluator & Trigger Subsystem Module for Basalt Engine.

Provides CronEvaluator and CronTrigger implementing 5-field Cron schedule matching,
wildcard/step/range/list parsing, and next execution timestamp calculations.
"""

from datetime import UTC, datetime, timedelta

from basalt.core.dag.ast import TriggerSpec
from basalt.core.dag.exceptions import BasaltError
from basalt.core.triggers.base import BaseTrigger
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class CronParseError(BasaltError):
    """Raised when a 5-field cron expression fails syntax parsing."""

    def __init__(self, cron_expr: str, reason: str) -> None:
        super().__init__(
            message=f"Invalid cron expression '{cron_expr}': {reason}",
            code="CRON_PARSE_ERROR",
            details={"cron_expr": cron_expr, "reason": reason},
        )


class CronEvaluator:
    """Pure Python 5-field Cron schedule field evaluator."""

    @staticmethod
    def parse_field(field_str: str, min_val: int, max_val: int) -> set[int]:
        """Parse a single cron field string into a set of allowed integer values.

        Supports '*', ',', '-', '/' syntax patterns.
        """
        result: set[int] = set()

        for part in field_str.split(","):
            part = part.strip()
            if not part:
                continue

            if "/" in part:
                range_part, step_str = part.split("/", 1)
                try:
                    step = int(step_str)
                    if step <= 0:
                        raise ValueError()
                except ValueError:
                    raise CronParseError(field_str, f"Invalid step size '{step_str}'")

                if range_part == "*":
                    low, high = min_val, max_val
                elif "-" in range_part:
                    low_s, high_s = range_part.split("-", 1)
                    low, high = int(low_s), int(high_s)
                else:
                    low, high = int(range_part), max_val

                for v in range(max(min_val, low), min(max_val, high) + 1, step):
                    result.add(v)

            elif "-" in part:
                low_s, high_s = part.split("-", 1)
                try:
                    low, high = int(low_s), int(high_s)
                    if low < min_val or high > max_val or low > high:
                        raise CronParseError(
                            field_str, f"Range [{low}, {high}] out of bounds [{min_val}, {max_val}]"
                        )
                except ValueError:
                    raise CronParseError(field_str, f"Invalid range values in '{part}'")
                for v in range(max(min_val, low), min(max_val, high) + 1):
                    result.add(v)

            elif part == "*":
                for v in range(min_val, max_val + 1):
                    result.add(v)

            else:
                try:
                    v = int(part)
                    if min_val <= v <= max_val:
                        result.add(v)
                    else:
                        raise CronParseError(
                            field_str, f"Value {v} out of bounds [{min_val}, {max_val}]"
                        )
                except ValueError:
                    raise CronParseError(field_str, f"Invalid integer token '{part}'")

        return result

    @classmethod
    def validate_cron_expression(cls, cron_expr: str) -> bool:
        """Validate if a string is a syntactically valid 5-field cron expression."""
        try:
            parts = cron_expr.strip().split()
            if len(parts) != 5:
                return False
            cls.parse_field(parts[0], 0, 59)
            cls.parse_field(parts[1], 0, 23)
            cls.parse_field(parts[2], 1, 31)
            cls.parse_field(parts[3], 1, 12)
            cls.parse_field(parts[4], 0, 6)
            return True
        except Exception:
            return False

    @classmethod
    def matches_timestamp(cls, cron_expr: str, dt: datetime) -> bool:
        """Check if datetime dt matches the 5-field cron expression.

        Fields: [minute (0-59), hour (0-23), day_of_month (1-31), month (1-12), day_of_week (0-6)]
        """
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise CronParseError(cron_expr, f"Expected 5 fields, got {len(parts)}")

        minutes = cls.parse_field(parts[0], 0, 59)
        hours = cls.parse_field(parts[1], 0, 23)
        days_of_month = cls.parse_field(parts[2], 1, 31)
        months = cls.parse_field(parts[3], 1, 12)
        days_of_week = cls.parse_field(parts[4], 0, 6)

        # Python datetime weekday: Monday=0 ... Sunday=6 -> Convert to Sunday=0
        dow = (dt.weekday() + 1) % 7

        return (
            dt.minute in minutes
            and dt.hour in hours
            and dt.day in days_of_month
            and dt.month in months
            and dow in days_of_week
        )

    @classmethod
    def get_next_fire_time(
        cls,
        cron_expr: str,
        base_time: datetime | None = None,
        max_search_days: int = 366,
    ) -> datetime | None:
        """Search forward minute-by-minute for the next matching fire time."""
        ref = (base_time or datetime.now(UTC)).replace(second=0, microsecond=0)
        curr = ref + timedelta(minutes=1)
        limit = ref + timedelta(days=max_search_days)

        while curr <= limit:
            if cls.matches_timestamp(cron_expr, curr):
                return curr
            curr += timedelta(minutes=1)

        return None

    @classmethod
    def explain(cls, cron_expr: str) -> str:
        """Provide human-readable explanation summary of a cron expression."""
        if not cls.validate_cron_expression(cron_expr):
            return f"Invalid cron expression: '{cron_expr}'"
        parts = cron_expr.strip().split()
        return (
            f"Fires on minute={parts[0]}, hour={parts[1]}, "
            f"day_of_month={parts[2]}, month={parts[3]}, day_of_week={parts[4]}"
        )


class CronTrigger(BaseTrigger):
    """Event trigger driven by a 5-field Cron schedule expression."""

    def __init__(self, trigger_spec: TriggerSpec, dag_id: str) -> None:
        super().__init__(trigger_spec, dag_id)
        if not trigger_spec.cron:
            raise ValueError(f"CronTrigger '{trigger_spec.id}' requires 'cron' expression.")
        self.cron_expr = trigger_spec.cron

    def should_fire(self, current_time: datetime | None = None) -> bool:
        """Check if current timestamp matches cron expression and has not already fired this minute."""
        if not self.is_active:
            return False

        now = (current_time or datetime.now(UTC)).replace(second=0, microsecond=0)

        # Prevent duplicate firing within the same minute
        if self.last_fired_at is not None:
            last_minute = self.last_fired_at.replace(second=0, microsecond=0)
            if now <= last_minute:
                return False

        return CronEvaluator.matches_timestamp(self.cron_expr, now)

    def get_next_fire_time(self, current_time: datetime | None = None) -> datetime | None:
        """Calculate next scheduled fire timestamp for this cron trigger."""
        return CronEvaluator.get_next_fire_time(self.cron_expr, base_time=current_time)
