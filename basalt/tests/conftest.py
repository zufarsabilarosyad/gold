"""Master Pytest Shared Fixtures Subsystem for Basalt Engine.

Provides reusable pytest fixtures including temporary SQLite databases, initialized in-memory
and SQLite BasaltEngine instances, sample YAML/JSON workflow specifications, mock HTTP webhooks,
and FastAPI AsyncClient test instances.
"""

from collections.abc import AsyncGenerator

import httpx
import pytest
from httpx import ASGITransport

from basalt.api.app import create_app
from basalt.core.dag.ast import DAGSpec
from basalt.core.dag.parser import DAGParser
from basalt.core.engine.engine import BasaltEngine, EngineConfig, set_engine
from basalt.core.triggers.webhook import WebhookSignatureVerifier


@pytest.fixture
def tmp_sqlite_url(tmp_path) -> str:
    """Fixture providing temporary SQLite database URL for isolation."""
    db_file = tmp_path / "test_basalt.db"
    return f"sqlite+aiosqlite:///{db_file}"


@pytest.fixture
async def memory_engine() -> AsyncGenerator[BasaltEngine, None]:
    """Fixture providing started BasaltEngine instance in in-memory mode."""
    config = EngineConfig(use_memory_storage=True, enable_triggers=True)
    engine = BasaltEngine(config=config)
    set_engine(engine)
    await engine.start()
    yield engine
    await engine.stop()
    set_engine(None)


@pytest.fixture
async def sqlite_engine(tmp_sqlite_url: str) -> AsyncGenerator[BasaltEngine, None]:
    """Fixture providing started BasaltEngine instance backed by SQLite database."""
    config = EngineConfig(db_url=tmp_sqlite_url, use_memory_storage=False, enable_triggers=True)
    engine = BasaltEngine(config=config)
    set_engine(engine)
    await engine.start()
    yield engine
    await engine.stop()
    set_engine(None)


@pytest.fixture
async def api_client(sqlite_engine: BasaltEngine) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Fixture providing httpx.AsyncClient connected to FastAPI app with active SQLite engine."""
    app = create_app()
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client


@pytest.fixture
def sample_linear_dag_yaml() -> str:
    """Fixture providing YAML specification for a 3-step linear DAG workflow."""
    return """
id: fixture_linear_dag
name: Fixture Linear Workflow
description: Linear workflow fixture for testing.
version: "1.0.0"
tags: ["fixture", "linear"]
steps:
  - id: step_1
    name: Step One
    executor_type: subprocess
    command: "echo '{\"val\": 1}'"

  - id: step_2
    name: Step Two
    executor_type: subprocess
    command: "echo '{\"val\": 2}'"
    depends_on: ["step_1"]

  - id: step_3
    name: Step Three
    executor_type: subprocess
    command: "echo '{\"val\": 3}'"
    depends_on: ["step_2"]
"""


@pytest.fixture
def sample_diamond_dag_yaml() -> str:
    """Fixture providing YAML specification for a 4-step diamond topology DAG workflow."""
    return """
id: fixture_diamond_dag
name: Fixture Diamond Workflow
version: "1.0.0"
tags: ["fixture", "diamond"]
steps:
  - id: start_step
    executor_type: subprocess
    command: "echo '{\"status\": \"started\"}'"

  - id: branch_a
    executor_type: subprocess
    command: "echo '{\"branch\": \"a\"}'"
    depends_on: ["start_step"]

  - id: branch_b
    executor_type: subprocess
    command: "echo '{\"branch\": \"b\"}'"
    depends_on: ["start_step"]

  - id: join_step
    executor_type: subprocess
    command: "echo '{\"status\": \"joined\"}'"
    depends_on: ["branch_a", "branch_b"]
"""


@pytest.fixture
def sample_webhook_dag_yaml() -> str:
    """Fixture providing YAML specification for a webhook-triggered DAG workflow."""
    return """
id: fixture_webhook_dag
name: Fixture Webhook Workflow
steps:
  - id: handle_event
    executor_type: subprocess
    command: "echo '{\"handled\": true}'"
triggers:
  - id: trig_fix_wh
    type: webhook
    webhook_secret: "fixture_secret_123"
"""


@pytest.fixture
def sample_retry_dag_yaml() -> str:
    """Fixture providing YAML specification for a DAG workflow with retry policy."""
    return """
id: fixture_retry_dag
name: Fixture Retry Workflow
steps:
  - id: step_flaky
    executor_type: subprocess
    command: "echo '{\"attempt\": \"success\"}'"
    retry_policy:
      max_retries: 3
      initial_interval_seconds: 0.1
      backoff_factor: 2.0
"""


@pytest.fixture
def sample_conditional_dag_yaml() -> str:
    """Fixture providing YAML specification for a DAG workflow with when expression conditions."""
    return """
id: fixture_conditional_dag
name: Fixture Conditional Workflow
steps:
  - id: evaluate_flag
    executor_type: subprocess
    command: "echo '{\"enabled\": true}'"

  - id: execute_if_enabled
    executor_type: subprocess
    command: "echo '{\"executed\": true}'"
    depends_on: ["evaluate_flag"]
    when: "${steps.evaluate_flag.output.enabled} == true"
"""


@pytest.fixture
def parsed_linear_dag(sample_linear_dag_yaml: str) -> DAGSpec:
    """Fixture providing parsed AST DAGSpec model for linear workflow."""
    return DAGParser.parse_string(sample_linear_dag_yaml)


@pytest.fixture
def parsed_diamond_dag(sample_diamond_dag_yaml: str) -> DAGSpec:
    """Fixture providing parsed AST DAGSpec model for diamond workflow."""
    return DAGParser.parse_string(sample_diamond_dag_yaml)


@pytest.fixture
def make_webhook_headers():
    """Factory fixture generating HMAC signature headers for testing webhook ingestion."""

    def _gen_headers(body: bytes, secret: str) -> dict[str, str]:
        sig = WebhookSignatureVerifier.compute_signature(body, secret)
        return {
            "X-Basalt-Signature": f"sha256={sig}",
            "Content-Type": "application/json",
        }

    return _gen_headers
