"""Lightweight Database Schema Migration Subsystem Module for Basalt Engine.

Provides automatic table creation, schema version tracking via the schema_versions table,
and incremental SQL migration execution.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Integer, Text, select, text
from sqlalchemy.orm import Mapped, mapped_column

from basalt.storage.database import Base, DatabaseManager
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class SchemaVersionModel(Base):
    """ORM table tracking database schema migration history."""

    __tablename__ = "schema_versions"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)


class Migration(BaseModel):
    """Data object representing a single version migration step."""

    version: int = Field(..., ge=1)
    description: str = Field(...)
    up_sql: list[str] = Field(default_factory=list)


class MigrationHistoryRecord(BaseModel):
    """Data record for an applied schema migration entry."""

    version: int
    applied_at: datetime
    description: str


# Defined schema migration registry
MIGRATION_REGISTRY: list[Migration] = [
    Migration(
        version=1,
        description="Initial Basalt database tables schema",
        up_sql=[
            "CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY, applied_at DATETIME NOT NULL, description TEXT NOT NULL);",
        ],
    ),
    Migration(
        version=2,
        description="Add performance indices on dag_runs and step_runs",
        up_sql=[
            "CREATE INDEX IF NOT EXISTS idx_dag_runs_dag_state ON dag_runs (dag_id, state);",
            "CREATE INDEX IF NOT EXISTS idx_step_runs_run_step ON step_runs (run_id, step_id);",
        ],
    ),
    Migration(
        version=3,
        description="Add index on dead_letter_queue created_at",
        up_sql=[
            "CREATE INDEX IF NOT EXISTS idx_dlq_created_at ON dead_letter_queue (created_at);",
        ],
    ),
]


class SchemaMigrator:
    """Manager for schema version inspection and sequential migration execution."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager

    async def get_current_version(self) -> int:
        """Query highest applied schema migration version from database."""
        await self.db_manager.create_tables()

        async with self.db_manager.session() as session:
            stmt = (
                select(SchemaVersionModel.version)
                .order_by(SchemaVersionModel.version.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            curr = result.scalar_one_or_none()
            return curr if curr is not None else 0

    async def get_migration_history(self) -> list[MigrationHistoryRecord]:
        """Query complete history of applied schema migrations."""
        await self.db_manager.create_tables()

        async with self.db_manager.session() as session:
            stmt = select(SchemaVersionModel).order_by(SchemaVersionModel.version.asc())
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [
                MigrationHistoryRecord(
                    version=row.version,
                    applied_at=row.applied_at,
                    description=row.description,
                )
                for row in rows
            ]

    async def apply_migrations(self) -> int:
        """Apply all pending migrations sequentially.

        Returns:
            Count of newly applied migration scripts.
        """
        current_version = await self.get_current_version()
        applied_count = 0

        for migration in MIGRATION_REGISTRY:
            if migration.version <= current_version:
                continue

            logger.info(f"Applying migration v{migration.version}: '{migration.description}'")

            async with self.db_manager.session() as session:
                # Execute migration SQL statements
                for sql in migration.up_sql:
                    await session.execute(text(sql))

                # Record migration version entry
                ver_entry = SchemaVersionModel(
                    version=migration.version,
                    description=migration.description,
                    applied_at=datetime.now(UTC),
                )
                session.add(ver_entry)

            applied_count += 1
            logger.info(f"Successfully applied migration v{migration.version}")

        if applied_count == 0:
            logger.debug(f"Database schema is up-to-date at version v{current_version}")

        return applied_count

    async def check_pending_migrations(self) -> list[Migration]:
        """Return list of registered migrations that have not been applied yet."""
        curr = await self.get_current_version()
        return [m for m in MIGRATION_REGISTRY if m.version > curr]

    async def reset_database(self) -> None:
        """Drop all tables and recreate clean schema."""
        logger.warning("Resetting database schema to clean state...")
        await self.db_manager.drop_tables()
        await self.db_manager.create_tables()
        await self.apply_migrations()


async def run_migrations(db_manager: DatabaseManager) -> int:
    """Helper shortcut function to run all pending database migrations."""
    migrator = SchemaMigrator(db_manager)
    return await migrator.apply_migrations()
