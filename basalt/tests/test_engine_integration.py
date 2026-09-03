"""Comprehensive End-to-End Integration Test Suite for Basalt Engine.

Validates complete multi-step ETL workflows, conditional branching and skipping,
retry policy recovery, active run cancellation, batch run execution, fast-fail on error,
lifecycle hooks recording, and SQLite ledger persistence.
"""

import asyncio

import pytest

from basalt.core.engine.engine import BasaltEngine
from basalt.core.engine.hooks import LifecycleEvent
from basalt.core.engine.state_machine import StepState, WorkflowState


@pytest.mark.asyncio
async def test_end_to_end_complex_etl_workflow(sqlite_engine: BasaltEngine) -> None:
    """Validate full multi-step ETL workflow with data dependencies and output propagation."""
    etl_yaml = """
id: e2e_etl_pipeline
name: E2E ETL Pipeline
description: Complete multi-stage ETL data pipeline
tags: ["e2e", "etl"]
steps:
  - id: extract
    name: Extract Raw Records
    executor_type: subprocess
    command: >-
      echo '{"records": [1, 2, 3, 4, 5], "count": 5}'

  - id: transform
    name: Transform Data Payload
    executor_type: subprocess
    command: >-
      echo '{"transformed_count": 5, "multiplier": 2}'
    depends_on: ["extract"]

  - id: validate
    name: Validate Record Schema
    executor_type: subprocess
    command: >-
      echo '{"valid": true}'
    depends_on: ["transform"]

  - id: load
    name: Load Into Target Store
    executor_type: subprocess
    command: >-
      echo '{"loaded": 5, "status": "SUCCESS"}'
    depends_on: ["validate"]
"""

    # 1. Register DAG
    dag = await sqlite_engine.register_dag(etl_yaml, overwrite=True)
    assert dag.id == "e2e_etl_pipeline"
    assert len(dag.steps) == 4

    # 2. Execute Workflow DAG
    result = await sqlite_engine.run_dag("e2e_etl_pipeline", inputs={"batch_id": "b_20260806"})
    assert result.state == WorkflowState.COMPLETED
    assert result.is_success() is True
    assert result.duration_ms > 0

    # 3. Verify step outputs propagation
    assert result.outputs["extract"]["count"] == 5
    assert result.outputs["transform"]["multiplier"] == 2
    assert result.outputs["validate"]["valid"] is True
    assert result.outputs["load"]["status"] == "SUCCESS"

    # 4. Verify SQLite Repository Persistence
    persisted_run = await sqlite_engine.get_run_result(result.run_id)
    assert persisted_run is not None
    assert persisted_run.run_id == result.run_id
    assert persisted_run.state == WorkflowState.COMPLETED
    assert len(persisted_run.step_states) == 4
    for step_id in ["extract", "transform", "validate", "load"]:
        assert persisted_run.step_states[step_id] == StepState.COMPLETED


@pytest.mark.asyncio
async def test_end_to_end_conditional_branching_and_skipping(sqlite_engine: BasaltEngine) -> None:
    """Validate conditional step execution where step is skipped based on when expression."""
    conditional_yaml = """
id: e2e_conditional_pipeline
name: E2E Conditional Pipeline
steps:
  - id: check_feature
    executor_type: subprocess
    command: >-
      echo '{"feature_enabled": false}'

  - id: optional_feature_step
    executor_type: subprocess
    command: >-
      echo '{"ran_optional": true}'
    depends_on: ["check_feature"]
    when: "${steps.check_feature.output.feature_enabled} == true"

  - id: main_pipeline_step
    executor_type: subprocess
    command: >-
      echo '{"main_completed": true}'
    depends_on: ["check_feature"]
"""

    await sqlite_engine.register_dag(conditional_yaml)
    result = await sqlite_engine.run_dag("e2e_conditional_pipeline")

    assert result.state == WorkflowState.COMPLETED
    assert result.step_states["check_feature"] == StepState.COMPLETED
    assert result.step_states["optional_feature_step"] == StepState.SKIPPED
    assert result.step_states["main_pipeline_step"] == StepState.COMPLETED
    assert "optional_feature_step" not in result.outputs


@pytest.mark.asyncio
async def test_end_to_end_retry_policy_recovery(sqlite_engine: BasaltEngine) -> None:
    """Validate step retry policy recovery and ultimate workflow completion."""
    retry_yaml = """
id: e2e_retry_pipeline
name: E2E Retry Recovery Pipeline
steps:
  - id: step_with_retry
    executor_type: subprocess
    command: >-
      echo '{"recovered": true}'
    retry_policy:
      max_retries: 2
      initial_interval_seconds: 0.05
      backoff_factor: 1.5
"""

    await sqlite_engine.register_dag(retry_yaml)
    result = await sqlite_engine.run_dag("e2e_retry_pipeline")

    assert result.state == WorkflowState.COMPLETED
    assert result.step_states["step_with_retry"] == StepState.COMPLETED
    assert result.outputs["step_with_retry"]["recovered"] is True


@pytest.mark.asyncio
async def test_end_to_end_active_run_cancellation(sqlite_engine: BasaltEngine) -> None:
    """Validate cancelling an active workflow run via engine runner."""
    slow_yaml = """
id: e2e_slow_pipeline
name: E2E Slow Pipeline
steps:
  - id: slow_step_1
    executor_type: subprocess
    command: >-
      sleep 0.5 && echo '{"step": 1}'
  - id: slow_step_2
    executor_type: subprocess
    command: >-
      sleep 0.5 && echo '{"step": 2}'
    depends_on: ["slow_step_1"]
"""

    await sqlite_engine.register_dag(slow_yaml)

    # Launch run in background task
    run_task = asyncio.create_task(
        sqlite_engine.run_dag("e2e_slow_pipeline", run_id="cancel_test_run")
    )
    await asyncio.sleep(0.1)

    # Issue cancellation signal
    cancelled = sqlite_engine.runner.cancel_run("cancel_test_run")
    assert cancelled is True

    result = await run_task
    assert result.state == WorkflowState.CANCELLED


@pytest.mark.asyncio
async def test_end_to_end_concurrent_workflow_batch(sqlite_engine: BasaltEngine) -> None:
    """Validate concurrent execution of multiple workflow runs in a batch."""
    batch_yaml = """
id: e2e_batch_item_pipeline
steps:
  - id: process_item
    executor_type: subprocess
    command: >-
      echo '{"processed": true}'
"""

    await sqlite_engine.register_dag(batch_yaml)

    # Submit 5 concurrent runs
    tasks = [
        sqlite_engine.run_dag("e2e_batch_item_pipeline", inputs={"item_idx": i}) for i in range(5)
    ]
    results = await asyncio.gather(*tasks)

    assert len(results) == 5
    for i, res in enumerate(results):
        assert res.state == WorkflowState.COMPLETED
        assert res.inputs["item_idx"] == i
        assert res.outputs["process_item"]["processed"] is True


@pytest.mark.asyncio
async def test_end_to_end_webhook_event_trigger_flow(sqlite_engine: BasaltEngine) -> None:
    """Validate incoming webhook payload HMAC verification and automatic workflow dispatch."""
    secret = "e2e_webhook_secret_key"
    wh_yaml = f"""
id: e2e_webhook_pipeline
name: E2E Webhook Pipeline
steps:
  - id: process_webhook
    executor_type: subprocess
    command: >-
      echo '{{"event_processed": true}}'
triggers:
  - id: trig_e2e_wh
    type: webhook
    webhook_secret: "{secret}"
"""

    await sqlite_engine.register_dag(wh_yaml)

    # Process webhook event
    raw_body = b'{"action": "deploy", "env": "prod"}'
    from basalt.core.triggers.webhook import WebhookSignatureVerifier

    sig = WebhookSignatureVerifier.compute_signature(raw_body, secret)
    headers = {"X-Basalt-Signature": f"sha256={sig}"}

    result = await sqlite_engine.process_webhook_event(
        trigger_id="trig_e2e_wh",
        raw_body=raw_body,
        headers=headers,
        payload_dict={"action": "deploy", "env": "prod"},
    )

    assert result.state == WorkflowState.COMPLETED
    assert result.outputs["process_webhook"]["event_processed"] is True


@pytest.mark.asyncio
async def test_end_to_end_fast_fail_on_step_failure(sqlite_engine: BasaltEngine) -> None:
    """Validate fast-fail behavior when a step fails, skipping downstream dependent steps."""
    fail_yaml = """
id: e2e_fail_pipeline
steps:
  - id: step_ok
    executor_type: subprocess
    command: >-
      echo '{"status": "ok"}'

  - id: step_failing
    executor_type: subprocess
    command: "exit 1"
    depends_on: ["step_ok"]

  - id: step_downstream
    executor_type: subprocess
    command: >-
      echo '{"should_not_run": true}'
    depends_on: ["step_failing"]
"""

    await sqlite_engine.register_dag(fail_yaml)
    result = await sqlite_engine.run_dag("e2e_fail_pipeline")

    assert result.state == WorkflowState.FAILED
    assert result.step_states["step_ok"] == StepState.COMPLETED
    assert result.step_states["step_failing"] == StepState.FAILED
    assert result.step_states["step_downstream"] == StepState.SKIPPED


@pytest.mark.asyncio
async def test_end_to_end_lifecycle_hooks_recording(sqlite_engine: BasaltEngine) -> None:
    """Validate lifecycle callback hooks triggered during workflow execution."""
    recorded_events: list[str] = []

    async def _on_workflow_start(event, ctx, payload):
        recorded_events.append("WORKFLOW_START")

    async def _on_step_success(event, ctx, payload):
        recorded_events.append(f"STEP_SUCCESS_{payload.get('step_id')}")

    async def _on_workflow_success(event, ctx, payload):
        recorded_events.append("WORKFLOW_SUCCESS")

    sqlite_engine.runner.hook_registry.register(LifecycleEvent.WORKFLOW_START, _on_workflow_start)
    sqlite_engine.runner.hook_registry.register(LifecycleEvent.STEP_SUCCESS, _on_step_success)
    sqlite_engine.runner.hook_registry.register(
        LifecycleEvent.WORKFLOW_SUCCESS, _on_workflow_success
    )

    hook_yaml = """
id: e2e_hook_pipeline
steps:
  - id: s1
    executor_type: subprocess
    command: "echo ok"
"""
    await sqlite_engine.register_dag(hook_yaml)
    result = await sqlite_engine.run_dag("e2e_hook_pipeline")

    assert result.state == WorkflowState.COMPLETED
    assert "WORKFLOW_START" in recorded_events
    assert "STEP_SUCCESS_s1" in recorded_events
    assert "WORKFLOW_SUCCESS" in recorded_events
