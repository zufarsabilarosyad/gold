"""End-to-End Integration Tests for FastAPI REST API Subsystem.

Validates all REST API endpoints using httpx.AsyncClient including DAG registration,
validation, topology inspection, run execution triggering, batch runs, cancellation, retries,
webhook ingestion, trigger pause/resume, DLQ inspection, error handling, and custom header middleware.
"""

from collections.abc import AsyncGenerator

import httpx
import pytest
from httpx import ASGITransport

from basalt.api.app import create_app
from basalt.core.triggers.webhook import WebhookSignatureVerifier


@pytest.fixture
async def async_client(tmp_path) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Pytest fixture initializing FastAPI app with temporary SQLite database and AsyncClient."""
    db_file = tmp_path / "api_test.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    # Import and configure engine for tests
    from basalt.core.engine.engine import BasaltEngine, EngineConfig, set_engine

    engine = BasaltEngine(
        config=EngineConfig(db_url=db_url, use_memory_storage=False, enable_triggers=True)
    )
    set_engine(engine)
    await engine.start()

    app = create_app()

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client

    await engine.stop()
    set_engine(None)


# --- System Telemetry & Health Tests ---


@pytest.mark.asyncio
async def test_health_and_info_endpoints(async_client: httpx.AsyncClient) -> None:
    """Verify GET /health, GET /info, GET /metrics, and GET / root endpoints."""
    # 1. Health endpoint
    resp_health = await async_client.get("/health")
    assert resp_health.status_code == 200
    data_health = resp_health.json()
    assert data_health["status"] in ("healthy", "degraded")
    assert data_health["version"] == "1.0.0"
    assert "X-Request-ID" in resp_health.headers
    assert "X-Process-Time-MS" in resp_health.headers
    assert resp_health.headers["X-Content-Type-Options"] == "nosniff"

    # 2. System info endpoint
    resp_info = await async_client.get("/info")
    assert resp_info.status_code == 200
    data_info = resp_info.json()
    assert data_info["engine_name"] == "Basalt Engine"
    assert data_info["worker_concurrency"] > 0

    # 3. Metrics endpoint
    resp_metrics = await async_client.get("/metrics")
    assert resp_metrics.status_code == 200
    data_metrics = resp_metrics.json()
    assert "max_concurrency" in data_metrics
    assert "active_workers" in data_metrics

    # 4. Root endpoint
    resp_root = await async_client.get("/")
    assert resp_root.status_code == 200
    assert resp_root.json()["documentation"] == "/docs"


# --- Workflow DAG Endpoints Tests ---


@pytest.mark.asyncio
async def test_dag_registration_validation_and_lifecycle(async_client: httpx.AsyncClient) -> None:
    """Verify DAG registration, validation, retrieval, graph topology query, listing, and deletion."""
    sample_yaml = """
id: api_dag_1
name: API Test Workflow
description: Workflow for API testing
tags: ["api", "integration"]
steps:
  - id: step_a
    executor_type: subprocess
    command: >-
      echo '{"status": "ok"}'
  - id: step_b
    executor_type: subprocess
    command: >-
      echo '{"step": "b"}'
    depends_on: ["step_a"]
"""

    # 1. Validate spec without registering
    resp_val = await async_client.post(
        "/api/v1/dags/validate",
        json={"spec": sample_yaml},
    )
    assert resp_val.status_code == 200
    assert resp_val.json()["valid"] is True
    assert resp_val.json()["step_count"] == 2

    # 2. Register DAG
    resp_reg = await async_client.post(
        "/api/v1/dags/",
        json={"spec": sample_yaml, "overwrite": True},
    )
    assert resp_reg.status_code == 201
    dag_data = resp_reg.json()
    assert dag_data["id"] == "api_dag_1"
    assert dag_data["step_count"] == 2

    # 3. Query single DAG
    resp_get = await async_client.get("/api/v1/dags/api_dag_1")
    assert resp_get.status_code == 200
    assert resp_get.json()["name"] == "API Test Workflow"

    # 4. Query DAG Graph Topology
    resp_graph = await async_client.get("/api/v1/dags/api_dag_1/graph")
    assert resp_graph.status_code == 200
    assert len(resp_graph.json()["execution_stages"]) == 2

    # 5. List DAGs with tag filter
    resp_list = await async_client.get("/api/v1/dags/?tag=api")
    assert resp_list.status_code == 200
    assert resp_list.json()["total"] == 1
    assert resp_list.json()["dags"][0]["id"] == "api_dag_1"

    # 6. Delete DAG
    resp_del = await async_client.delete("/api/v1/dags/api_dag_1")
    assert resp_del.status_code == 200
    assert resp_del.json()["deleted"] is True

    # 7. Verify deletion (404)
    resp_get_404 = await async_client.get("/api/v1/dags/api_dag_1")
    assert resp_get_404.status_code == 404
    assert resp_get_404.json()["error"]["code"] == "DAG_NOT_FOUND"


# --- Workflow Run Execution Endpoints Tests ---


@pytest.mark.asyncio
async def test_workflow_run_trigger_and_query(async_client: httpx.AsyncClient) -> None:
    """Verify triggering workflow execution, querying run status, step details, active runs, and run history."""
    dag_yaml = """
id: api_run_dag
name: Run Execution DAG
steps:
  - id: step_calc
    executor_type: subprocess
    command: >-
      echo '{"computed": 84}'
"""
    # Register DAG
    await async_client.post("/api/v1/dags/", json={"spec": dag_yaml})

    # 1. Trigger execution
    resp_run = await async_client.post(
        "/api/v1/dags/api_run_dag/runs",
        json={"inputs": {"x": 42}},
    )
    assert resp_run.status_code == 201
    run_data = resp_run.json()
    run_id = run_data["run_id"]
    assert run_data["state"].upper() == "COMPLETED"
    assert run_data["outputs"]["step_calc"]["computed"] == 84

    # 2. Get active runs endpoint
    resp_active = await async_client.get("/api/v1/runs/active")
    assert resp_active.status_code == 200

    # 3. Get run status by ID
    resp_status = await async_client.get(f"/api/v1/runs/{run_id}")
    assert resp_status.status_code == 200
    assert resp_status.json()["run_id"] == run_id

    # 4. Get specific step output
    resp_step = await async_client.get(f"/api/v1/runs/{run_id}/steps/step_calc")
    assert resp_step.status_code == 200
    assert resp_step.json()["output"]["computed"] == 84

    # 5. List historical run logs
    resp_list_runs = await async_client.get("/api/v1/runs?dag_id=api_run_dag")
    assert resp_list_runs.status_code == 200
    assert resp_list_runs.json()["total"] >= 1


@pytest.mark.asyncio
async def test_batch_runs_and_cancellation(async_client: httpx.AsyncClient) -> None:
    """Verify batch workflow run submission and cancellation error handling."""
    dag_yaml = """
id: api_batch_dag
name: Batch Run DAG
steps:
  - id: s1
    executor_type: subprocess
    command: >-
      echo '{"msg": "batch"}'
"""
    await async_client.post("/api/v1/dags/", json={"spec": dag_yaml})

    # 1. Batch run submission
    resp_batch = await async_client.post(
        "/api/v1/dags/api_batch_dag/runs/batch",
        json={
            "requests": [
                {"inputs": {"batch_item": 1}},
                {"inputs": {"batch_item": 2}},
            ]
        },
    )
    assert resp_batch.status_code == 200
    assert resp_batch.json()["total_submitted"] == 2
    assert len(resp_batch.json()["runs"]) == 2

    # 2. Cancel non-active run (expect 400 Bad Request)
    resp_cancel = await async_client.post("/api/v1/runs/non_existent_run_id/cancel")
    assert resp_cancel.status_code == 400
    assert resp_cancel.json()["error"]["code"] == "RUN_NOT_ACTIVE"


# --- Event Triggers, Webhooks, & DLQ Tests ---


@pytest.mark.asyncio
async def test_webhook_trigger_and_dlq_endpoints(async_client: httpx.AsyncClient) -> None:
    """Verify HTTP Webhook ingestion, trigger pause/resume, and DLQ operations."""
    secret = "wh_api_secret_789"
    dag_yaml = f"""
id: api_wh_dag
name: Webhook API DAG
steps:
  - id: s_wh
    executor_type: subprocess
    command: >-
      echo '{{"received": true}}'
triggers:
  - id: trig_wh_api
    type: webhook
    webhook_secret: "{secret}"
"""
    await async_client.post("/api/v1/dags/", json={"spec": dag_yaml})

    # 1. List registered triggers
    resp_trigs = await async_client.get("/api/v1/triggers?dag_id=api_wh_dag")
    assert resp_trigs.status_code == 200
    assert resp_trigs.json()["total"] == 1

    # 2. Pause and Resume Trigger
    resp_pause = await async_client.post("/api/v1/triggers/trig_wh_api/pause")
    assert resp_pause.status_code == 200
    assert resp_pause.json()["status"] == "paused"

    resp_resume = await async_client.post("/api/v1/triggers/trig_wh_api/resume")
    assert resp_resume.status_code == 200
    assert resp_resume.json()["status"] == "active"

    # 3. Post HTTP Webhook event
    raw_body = b'{"event": "user_created"}'
    sig = WebhookSignatureVerifier.compute_signature(raw_body, secret)
    headers = {
        "X-Basalt-Signature": f"sha256={sig}",
        "Content-Type": "application/json",
    }

    resp_wh = await async_client.post(
        "/api/v1/webhooks/trig_wh_api",
        content=raw_body,
        headers=headers,
    )
    assert resp_wh.status_code == 200
    assert resp_wh.json()["state"].upper() == "COMPLETED"

    # 4. DLQ List endpoint
    resp_dlq = await async_client.get("/api/v1/dlq")
    assert resp_dlq.status_code == 200
    assert "total" in resp_dlq.json()


@pytest.mark.asyncio
async def test_api_error_handling_and_validation(async_client: httpx.AsyncClient) -> None:
    """Verify HTTP status codes and error responses for bad payloads, invalid triggers, and non-existent runs."""
    # 1. Invalid JSON body (422 Unprocessable Entity)
    resp_val_err = await async_client.post(
        "/api/v1/dags/",
        headers={"Content-Type": "application/json"},
        content=b"invalid json format",
    )
    assert resp_val_err.status_code == 422
    assert resp_val_err.json()["error"]["code"] == "VALIDATION_ERROR"

    # 2. Trigger non-existent DAG (404 Not Found)
    resp_404 = await async_client.post("/api/v1/dags/non_existent_dag_99/runs")
    assert resp_404.status_code == 404
    assert resp_404.json()["error"]["code"] == "DAG_NOT_FOUND"

    # 3. Webhook signature verification failure (401 Unauthorized)
    secret = "secret_key_abc"
    dag_yaml = f"""
id: dag_auth_fail
steps:
  - id: s1
    executor_type: subprocess
    command: "echo ok"
triggers:
  - id: trig_auth_fail
    type: webhook
    webhook_secret: "{secret}"
"""
    await async_client.post("/api/v1/dags/", json={"spec": dag_yaml})

    bad_headers = {"X-Basalt-Signature": "sha256=invalid_signature_hash"}
    resp_unauth = await async_client.post(
        "/api/v1/webhooks/trig_auth_fail",
        content=b"{}",
        headers=bad_headers,
    )
    assert resp_unauth.status_code == 401
    assert resp_unauth.json()["error"]["code"] == "WEBHOOK_AUTH_ERROR"
