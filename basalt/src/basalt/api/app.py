"""FastAPI Master Application Assembly and Lifespan Manager Subsystem.

Assembles FastAPI application instance, router mounts, CORS policy, custom middleware pipeline,
global error handlers, health telemetry endpoints, metrics endpoints, and async lifespan engine lifecycle management.
"""

import sys
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware

from basalt.api.middleware import (
    APIVersionHeaderMiddleware,
    RequestTracingMiddleware,
    SecurityHeadersMiddleware,
    StructuredLoggingMiddleware,
    setup_exception_handlers,
)
from basalt.api.router_dags import router as router_dags
from basalt.api.router_runs import router as router_runs
from basalt.api.router_triggers import router as router_triggers
from basalt.api.schemas import HealthResponse, SystemInfoResponse
from basalt.core.engine.engine import EngineConfig, get_engine
from basalt.utils.logger import get_logger

logger = get_logger(__name__)

# Start timestamp for uptime calculation
START_TIME = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI async lifespan context manager initializing and shutting down BasaltEngine."""
    logger.info("Initializing BasaltEngine facade for FastAPI application lifespan...")
    engine = get_engine()
    await engine.start()

    yield

    logger.info("Shutting down BasaltEngine facade from FastAPI application lifespan...")
    await engine.stop()


def create_app(config: EngineConfig | None = None) -> FastAPI:
    """FastAPI Application Factory function.

    Args:
        config: Optional EngineConfig override for application initialization.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="Basalt DAG Execution Engine REST API",
        description="Production-grade Embedded Event-Driven Workflow & DAG Execution Engine REST API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # 1. CORS Configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 2. Custom Middlewares
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(APIVersionHeaderMiddleware, api_version="v1")
    app.add_middleware(StructuredLoggingMiddleware)
    app.add_middleware(RequestTracingMiddleware)

    # 3. Global Exception Handlers
    setup_exception_handlers(app)

    # 4. Include Subsystem Routers
    app.include_router(router_dags)
    app.include_router(router_runs)
    app.include_router(router_triggers)

    # 5. Core Health & System Telemetry Endpoints

    @app.get(
        "/health",
        response_model=HealthResponse,
        status_code=status.HTTP_200_OK,
        tags=["System"],
        summary="Engine Health Check",
        description="Returns real-time engine health status, active storage backend, and active run count.",
    )
    async def health_check() -> HealthResponse:
        engine = get_engine()
        backend_name = "sqlite" if engine.repository else "memory"
        active_runs_count = len(engine.runner.get_active_run_ids())

        return HealthResponse(
            status="healthy" if engine.is_running else "degraded",
            version="1.0.0",
            storage_backend=backend_name,
            active_runs=active_runs_count,
        )

    @app.get(
        "/info",
        response_model=SystemInfoResponse,
        status_code=status.HTTP_200_OK,
        tags=["System"],
        summary="System Telemetry & Environment Info",
        description="Returns Python version, worker concurrency bounds, loaded DAG count, and uptime telemetry.",
    )
    async def system_info() -> SystemInfoResponse:
        engine = get_engine()
        dags = await engine.list_dags()
        uptime = time.time() - START_TIME

        return SystemInfoResponse(
            engine_name="Basalt Engine",
            version="1.0.0",
            python_version=sys.version,
            loaded_dags_count=len(dags),
            worker_concurrency=engine.config.max_concurrency,
            uptime_seconds=round(uptime, 2),
        )

    @app.get(
        "/metrics",
        response_model=dict[str, float],
        status_code=status.HTTP_200_OK,
        tags=["System"],
        summary="Worker Pool Telemetry Metrics",
        description="Returns live worker pool slot allocation metrics and step counters.",
    )
    async def metrics() -> dict[str, float]:
        engine = get_engine()
        m = engine.worker_pool.get_metrics()
        return {
            "max_concurrency": float(m.max_concurrency),
            "active_workers": float(m.active_workers),
            "available_slots": float(m.available_slots),
            "total_steps_executed": float(m.total_steps_executed),
            "total_steps_succeeded": float(m.total_steps_succeeded),
            "total_steps_failed": float(m.total_steps_failed),
            "total_steps_timed_out": float(m.total_steps_timed_out),
        }

    @app.get(
        "/",
        status_code=status.HTTP_200_OK,
        tags=["System"],
        summary="API Root Information",
    )
    async def root_info() -> dict:
        return {
            "name": "Basalt DAG Execution Engine API",
            "version": "1.0.0",
            "documentation": "/docs",
            "health": "/health",
            "metrics": "/metrics",
        }

    return app


# Default ASGI app instance for uvicorn/hypercorn app execution
app = create_app()
