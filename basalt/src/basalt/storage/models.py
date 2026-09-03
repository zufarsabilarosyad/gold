"""SQLAlchemy 2.0 ORM Database Models Subsystem Module for Basalt Engine.

Defines database schemas for DAG definitions (DAGModel), workflow executions (DAGRunModel),
step execution states (StepRunModel), event triggers (TriggerModel), and Dead-Letter Queue (DLQModel).
"""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from basalt.storage.database import Base


class DAGModel(Base):
    """ORM model representing persisted workflow DAG definitions."""

    __tablename__ = "dags"

    id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="1.0.0")
    owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=3600.0)
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    spec_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    runs: Mapped[list["DAGRunModel"]] = relationship(
        "DAGRunModel", back_populates="dag", cascade="all, delete-orphan"
    )
    triggers: Mapped[list["TriggerModel"]] = relationship(
        "TriggerModel", back_populates="dag", cascade="all, delete-orphan"
    )

    @property
    def tags(self) -> list[str]:
        """Deserialize tags_json string into a list of tags."""
        try:
            return json.loads(self.tags_json)
        except Exception:
            return []

    @tags.setter
    def tags(self, value: list[str]) -> None:
        """Serialize tags list into JSON string."""
        self.tags_json = json.dumps(value or [])

    def to_dict(self) -> dict[str, Any]:
        """Serialize model instance to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "owner": self.owner,
            "tags": self.tags,
            "timeout_seconds": self.timeout_seconds,
            "max_concurrency": self.max_concurrency,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class DAGRunModel(Base):
    """ORM model representing an individual execution run log of a workflow DAG."""

    __tablename__ = "dag_runs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    dag_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("dags.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    inputs_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    outputs_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    dag: Mapped["DAGModel"] = relationship("DAGModel", back_populates="runs")
    step_runs: Mapped[list["StepRunModel"]] = relationship(
        "StepRunModel", back_populates="dag_run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_dag_runs_dag_id_state", "dag_id", "state"),
        Index("idx_dag_runs_start_time_desc", "start_time"),
    )

    @property
    def inputs(self) -> dict[str, Any]:
        """Deserialize inputs_json string into dictionary."""
        try:
            return json.loads(self.inputs_json)
        except Exception:
            return {}

    @inputs.setter
    def inputs(self, value: dict[str, Any]) -> None:
        """Serialize inputs dictionary into JSON string."""
        self.inputs_json = json.dumps(value or {})

    @property
    def outputs(self) -> dict[str, Any]:
        """Deserialize outputs_json string into dictionary."""
        try:
            return json.loads(self.outputs_json)
        except Exception:
            return {}

    @outputs.setter
    def outputs(self, value: dict[str, Any]) -> None:
        """Serialize outputs dictionary into JSON string."""
        self.outputs_json = json.dumps(value or {})

    def to_dict(self) -> dict[str, Any]:
        """Serialize model instance to dictionary representation."""
        return {
            "id": self.id,
            "dag_id": self.dag_id,
            "state": self.state,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "error_message": self.error_message,
        }


class StepRunModel(Base):
    """ORM model representing step execution record within a workflow run."""

    __tablename__ = "step_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("dag_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    dag_run: Mapped["DAGRunModel"] = relationship("DAGRunModel", back_populates="step_runs")

    __table_args__ = (Index("idx_step_runs_run_step", "run_id", "step_id"),)

    @property
    def output(self) -> Any | None:
        """Deserialize output_json into Python object."""
        if not self.output_json:
            return None
        try:
            return json.loads(self.output_json)
        except Exception:
            return self.output_json

    @output.setter
    def output(self, value: Any) -> None:
        """Serialize Python object into JSON string."""
        if value is None:
            self.output_json = None
        else:
            self.output_json = json.dumps(value)

    def to_dict(self) -> dict[str, Any]:
        """Serialize model instance to dictionary representation."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "state": self.state,
            "attempt": self.attempt,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "output": self.output,
            "error_message": self.error_message,
        }


class TriggerModel(Base):
    """ORM model representing an event trigger definition associated with a DAG."""

    __tablename__ = "triggers"

    id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    dag_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("dags.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    cron: Mapped[str | None] = mapped_column(String(64), nullable=True)
    interval_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(256), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # Relationships
    dag: Mapped["DAGModel"] = relationship("DAGModel", back_populates="triggers")

    def to_dict(self) -> dict[str, Any]:
        """Serialize model instance to dictionary representation."""
        return {
            "id": self.id,
            "dag_id": self.dag_id,
            "type": self.type,
            "cron": self.cron,
            "interval_seconds": self.interval_seconds,
            "webhook_secret": self.webhook_secret,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DLQModel(Base):
    """ORM model for Dead-Letter Queue storing unrecoverable payloads for manual inspection/replay."""

    __tablename__ = "dead_letter_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payload_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    dag_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    step_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str] = mapped_column(String(64), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )

    @property
    def payload(self) -> dict[str, Any]:
        """Deserialize payload_json into Python dictionary."""
        try:
            return json.loads(self.payload_json)
        except Exception:
            return {}

    @payload.setter
    def payload(self, value: dict[str, Any]) -> None:
        """Serialize Python dictionary into JSON string."""
        self.payload_json = json.dumps(value or {})

    def to_dict(self) -> dict[str, Any]:
        """Serialize model instance to dictionary representation."""
        return {
            "id": self.id,
            "payload_id": self.payload_id,
            "dag_id": self.dag_id,
            "step_id": self.step_id,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "payload": self.payload,
            "retry_count": self.retry_count,
            "processed": self.processed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
