"""Async SQLite Database Engine & Session Subsystem Module for Basalt Engine.

Configures async SQLAlchemy 2.0 engine using aiosqlite, WAL mode pragmas, foreign key enforcement,
and async session factory context managers.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.ext.asyncio import (
    create_async_engine as _create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""

    pass


class DatabaseManager:
    """Manager for async SQLAlchemy database engine and session lifecycle."""

    def __init__(self, database_url: str = "sqlite+aiosqlite:///basalt.db") -> None:
        self.database_url = self._normalize_url(database_url)
        self.engine: AsyncEngine | None = None
        self.session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def is_connected(self) -> bool:
        """Check if AsyncEngine is initialized and active."""
        return self.engine is not None

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Ensure database URL uses sqlite+aiosqlite driver prefix."""
        if url.startswith("sqlite://"):
            return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
        if not url.startswith("sqlite+aiosqlite://") and not url.startswith(
            "postgresql+asyncpg://"
        ):
            return f"sqlite+aiosqlite:///{url}"
        return url

    def initialize(self, echo: bool = False) -> AsyncEngine:
        """Initialize AsyncEngine and sessionmaker factory with WAL mode pragmas.

        Args:
            echo: SQL query echo logging boolean.

        Returns:
            Initialized AsyncEngine instance.
        """
        if self.engine is not None:
            return self.engine

        is_memory = ":memory:" in self.database_url

        connect_args = {"check_same_thread": False}
        poolclass = StaticPool if is_memory else None

        self.engine = _create_async_engine(
            self.database_url,
            echo=echo,
            connect_args=connect_args,
            poolclass=poolclass,
        )

        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        logger.info(f"Initialized DatabaseManager async engine for '{self.database_url}'")
        return self.engine

    async def configure_sqlite_pragmas(self) -> None:
        """Execute SQLite PRAGMA journal_mode=WAL and foreign_keys=ON."""
        if self.engine is None:
            self.initialize()

        assert self.engine is not None
        if "sqlite" in self.database_url:
            async with self.engine.begin() as conn:
                await conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
                await conn.exec_driver_sql("PRAGMA foreign_keys=ON;")
                logger.debug("Configured SQLite PRAGMA WAL mode and foreign_keys=ON")

    async def create_tables(self) -> None:
        """Create all database tables defined in Base metadata."""
        if self.engine is None:
            self.initialize()

        assert self.engine is not None
        await self.configure_sqlite_pragmas()
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Created all database tables via Base metadata")

    async def drop_tables(self) -> None:
        """Drop all database tables defined in Base metadata."""
        if self.engine is None:
            return

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        logger.warning("Dropped all database tables")

    async def execute_raw_sql(self, sql_query: str, params: dict[str, Any] | None = None) -> Any:
        """Execute a raw SQL query string."""
        async with self.session() as session:
            result = await session.execute(sql_query, params or {})
            return result

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Async context manager yielding a database session with auto-rollback on exception."""
        if self.session_factory is None:
            self.initialize()

        assert self.session_factory is not None
        async_session = self.session_factory()
        try:
            yield async_session
            await async_session.commit()
        except Exception as exc:
            await async_session.rollback()
            logger.error(f"Database session rolled back due to error: {exc}")
            raise
        finally:
            await async_session.close()

    async def close(self) -> None:
        """Dispose AsyncEngine and release connections."""
        if self.engine is not None:
            await self.engine.dispose()
            self.engine = None
            self.session_factory = None
            logger.info("Disposed DatabaseManager engine")


@lru_cache(maxsize=1)
def get_db_manager(db_url: str = "sqlite+aiosqlite:///basalt.db") -> DatabaseManager:
    """Retrieve global singleton DatabaseManager instance."""
    db_mgr = DatabaseManager(database_url=db_url)
    db_mgr.initialize()
    return db_mgr
