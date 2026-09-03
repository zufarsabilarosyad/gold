"""Abstract Base Trigger Interface & Event Model Subsystem Module for Basalt Engine.

Defines TriggerEvent container, TriggerStatus classification, and BaseTrigger abstract interface
for Cron, Interval, and Webhook event trigger engines.
"""

import abc
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from basalt.core.dag.ast import TriggerSpec, TriggerType
from basalt.utils.crypto import generate_uuid
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class TriggerStatus(str, Enum):
    """Operational lifecycle status of an event trigger."""

    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"


class TriggerEvent(BaseModel):
    """Container payload generated when an event trigger fires."""

    event_id: str = Field(default_factory=generate_uuid)
    trigger_id: str = Field(..., description="Target trigger identifier.")
    dag_id: str = Field(..., description="Target workflow DAG identifier.")
    trigger_type: TriggerType = Field(..., description="Trigger classification type.")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Event generation timestamp in UTC.",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event payload data passed into workflow run inputs.",
    )


class BaseTrigger(abc.ABC):
    """Abstract Base Class for event triggers."""

    def __init__(self, trigger_spec: TriggerSpec, dag_id: str) -> None:
        self.spec = trigger_spec
        self.dag_id = dag_id
        self.status = TriggerStatus.ACTIVE if trigger_spec.enabled else TriggerStatus.PAUSED
        self.last_fired_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        """Check if trigger is currently active."""
        return self.status == TriggerStatus.ACTIVE and self.spec.enabled

    def pause(self) -> None:
        """Pause trigger evaluations."""
        self.status = TriggerStatus.PAUSED
        logger.info(f"Trigger '{self.spec.id}' for DAG '{self.dag_id}' paused")

    def resume(self) -> None:
        """Resume trigger evaluations."""
        self.status = TriggerStatus.ACTIVE
        logger.info(f"Trigger '{self.spec.id}' for DAG '{self.dag_id}' resumed")

    def stop(self) -> None:
        """Stop trigger evaluations permanently."""
        self.status = TriggerStatus.STOPPED
        logger.info(f"Trigger '{self.spec.id}' for DAG '{self.dag_id}' stopped")

    @abc.abstractmethod
    def should_fire(self, current_time: datetime | None = None) -> bool:
        """Evaluate if trigger conditions are met for current_time.

        Args:
            current_time: Optional evaluation timestamp (defaults to UTC now).

        Returns:
            True if trigger condition is satisfied, False otherwise.
        """
        pass

    @abc.abstractmethod
    def get_next_fire_time(self, current_time: datetime | None = None) -> datetime | None:
        """Calculate next anticipated fire timestamp.

        Args:
            current_time: Base reference timestamp.

        Returns:
            Next fire datetime in UTC, or None if trigger has no future fires.
        """
        pass

    def evaluate(
        self,
        current_time: datetime | None = None,
        extra_payload: dict[str, Any] | None = None,
    ) -> TriggerEvent | None:
        """Evaluate trigger and construct TriggerEvent if conditions match.

        Args:
            current_time: Evaluation timestamp.
            extra_payload: Additional payload data to attach to TriggerEvent.

        Returns:
            TriggerEvent if trigger fired, None otherwise.
        """
        if not self.is_active:
            return None

        now = current_time or datetime.now(UTC)
        if self.should_fire(now):
            self.last_fired_at = now
            event_payload = {"fired_at": now.isoformat()}
            if extra_payload:
                event_payload.update(extra_payload)

            event = TriggerEvent(
                trigger_id=self.spec.id,
                dag_id=self.dag_id,
                trigger_type=self.spec.type,
                timestamp=now,
                payload=event_payload,
            )
            logger.info(
                f"Trigger '{self.spec.id}' fired event '{event.event_id}' for DAG '{self.dag_id}'"
            )
            return event

        return None
