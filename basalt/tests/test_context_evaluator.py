"""Unit Tests for ExecutionContext, ExpressionEvaluator, and HookRegistry Modules.

Validates variable resolution, template string interpolation, AST condition evaluation,
thread-safe context snapshots, decorator handlers, and async lifecycle hook callbacks.
"""

import pytest

from basalt.core.engine.context import ExecutionContext
from basalt.core.engine.evaluator import ExpressionEvaluationError, ExpressionEvaluator
from basalt.core.engine.hooks import HookRegistry, LifecycleEvent, get_hook_registry
from basalt.core.engine.state_machine import StepState


@pytest.fixture
def context() -> ExecutionContext:
    """Fixture providing populated ExecutionContext."""
    ctx = ExecutionContext(
        run_id="run_12345",
        dag_id="etl_workflow",
        inputs={"user_id": 42, "mode": "production", "nested": {"key": "val"}},
        env={"API_KEY": "secret_token_123", "PORT": "8080"},
    )
    ctx.set_step_state("fetch_step", StepState.COMPLETED)
    ctx.set_step_output(
        "fetch_step",
        {"status_code": 200, "item_count": 150, "payload": {"data": [1, 2, 3]}},
    )
    return ctx


def test_context_variable_path_resolution(context: ExecutionContext) -> None:
    """Verify dot-separated variable path resolution across namespaces."""
    # Run and DAG namespace
    assert context.resolve_variable_path("run.id") == "run_12345"
    assert context.resolve_variable_path("dag.id") == "etl_workflow"

    # Inputs namespace
    assert context.resolve_variable_path("inputs.user_id") == 42
    assert context.resolve_variable_path("inputs.mode") == "production"
    assert context.resolve_variable_path("inputs.nested.key") == "val"
    assert context.resolve_variable_path("inputs.non_existent") is None

    # Env namespace
    assert context.resolve_variable_path("env.API_KEY") == "secret_token_123"
    assert context.resolve_variable_path("env.PORT") == "8080"
    assert context.resolve_variable_path("env.MISSING_VAR") is None

    # Steps namespace
    assert context.resolve_variable_path("steps.fetch_step.output.status_code") == 200
    assert context.resolve_variable_path("steps.fetch_step.output.item_count") == 150
    assert context.resolve_variable_path("steps.fetch_step.output.payload.data") == [1, 2, 3]
    assert context.resolve_variable_path("steps.fetch_step.output.missing") is None


def test_context_mutators_and_state_predicates(context: ExecutionContext) -> None:
    """Verify state mutators, input/env setters, and state helper predicates."""
    context.set_input("new_flag", True)
    assert context.resolve_variable_path("inputs.new_flag") is True

    context.set_env("HOST", "localhost")
    assert context.resolve_variable_path("env.HOST") == "localhost"

    context.set_metadata("source", "cli")

    assert context.is_step_completed("fetch_step") is True
    assert context.is_step_failed("fetch_step") is False

    context.set_step_state("failed_step", StepState.FAILED)
    assert context.is_step_failed("failed_step") is True


def test_context_merge_output_and_snapshot(context: ExecutionContext) -> None:
    """Verify merging partial outputs and generating context snapshot."""
    context.merge_step_output("fetch_step", {"processed": True})
    output = context.get_step_output("fetch_step")
    assert output["status_code"] == 200
    assert output["processed"] is True

    snap = context.snapshot()
    assert snap["run_id"] == "run_12345"
    assert snap["dag_id"] == "etl_workflow"
    assert snap["inputs"]["mode"] == "production"
    assert snap["step_states"]["fetch_step"] == "COMPLETED"


def test_expression_interpolator_string(context: ExecutionContext) -> None:
    """Verify interpolating template variables into strings."""
    template = "User ${inputs.user_id} connecting to http://localhost:${env.PORT}/api with key ${env.API_KEY}"
    result = ExpressionEvaluator.interpolate_string(template, context)
    assert result == "User 42 connecting to http://localhost:8080/api with key secret_token_123"

    # Missing variable returns empty string
    missing_template = "Value is '${inputs.ghost}'"
    assert ExpressionEvaluator.interpolate_string(missing_template, context) == "Value is ''"


def test_expression_interpolator_value_recursive(context: ExecutionContext) -> None:
    """Verify recursive data structure template interpolation."""
    data = {
        "user": "${inputs.user_id}",
        "url": "http://api.com/${env.PORT}",
        "items": ["${steps.fetch_step.output.status_code}", "raw_string"],
        "raw_int": 100,
    }

    interpolated = ExpressionEvaluator.interpolate_value(data, context)
    assert interpolated["user"] == 42  # Direct single match retains int type
    assert interpolated["url"] == "http://api.com/8080"
    assert interpolated["items"] == [200, "raw_string"]
    assert interpolated["raw_int"] == 100


def test_expression_interpolator_complex_dict_payload(context: ExecutionContext) -> None:
    """Verify string interpolation of dictionary payloads converts to JSON string."""
    template = "Payload is ${steps.fetch_step.output.payload}"
    result = ExpressionEvaluator.interpolate_string(template, context)
    assert '{"data": [1, 2, 3]}' in result or '"data"' in result


def test_evaluate_condition_comparisons(context: ExecutionContext) -> None:
    """Verify safe boolean condition expression evaluations."""
    # Equal comparison
    assert (
        ExpressionEvaluator.evaluate_condition(
            "${steps.fetch_step.output.status_code} == 200", context
        )
        is True
    )
    assert (
        ExpressionEvaluator.evaluate_condition(
            "${steps.fetch_step.output.status_code} == 500", context
        )
        is False
    )

    # Not equal comparison
    assert ExpressionEvaluator.evaluate_condition("${inputs.mode} != 'staging'", context) is True

    # Numeric greater than / less than
    assert (
        ExpressionEvaluator.evaluate_condition(
            "${steps.fetch_step.output.item_count} > 100", context
        )
        is True
    )
    assert (
        ExpressionEvaluator.evaluate_condition(
            "${steps.fetch_step.output.item_count} <= 50", context
        )
        is False
    )

    # Boolean shortcuts
    assert ExpressionEvaluator.evaluate_condition("true", context) is True
    assert ExpressionEvaluator.evaluate_condition("false", context) is False
    assert ExpressionEvaluator.evaluate_condition("", context) is True


def test_evaluate_condition_complex_logic(context: ExecutionContext) -> None:
    """Verify logical AND, OR, NOT and IN operators in condition evaluator."""
    # AND / OR logic
    assert (
        ExpressionEvaluator.evaluate_condition(
            "${steps.fetch_step.output.status_code} == 200 and ${steps.fetch_step.output.item_count} > 100",
            context,
        )
        is True
    )
    assert (
        ExpressionEvaluator.evaluate_condition(
            "${steps.fetch_step.output.status_code} == 500 or ${inputs.mode} == 'production'",
            context,
        )
        is True
    )

    # NOT logic
    assert (
        ExpressionEvaluator.evaluate_condition(
            "not (${steps.fetch_step.output.status_code} == 500)", context
        )
        is True
    )


def test_evaluate_condition_fallback_parser(context: ExecutionContext) -> None:
    """Verify raw fallback comparison parser."""
    assert ExpressionEvaluator._fallback_evaluate_comparison("200 == 200") is True
    assert ExpressionEvaluator._fallback_evaluate_comparison("production != staging") is True
    assert ExpressionEvaluator._fallback_evaluate_comparison("10 > 5") is True


def test_evaluate_condition_ast_errors(context: ExecutionContext) -> None:
    """Verify invalid AST nodes raise ExpressionEvaluationError."""
    with pytest.raises(ExpressionEvaluationError) as exc_info:
        ExpressionEvaluator.evaluate_condition("os.system('rm -rf /')", context)
    assert exc_info.value.code == "EXPRESSION_EVALUATION_ERROR"


@pytest.mark.asyncio
async def test_hook_registry_dispatch(context: ExecutionContext) -> None:
    """Verify lifecycle hook registration, decorators, and async dispatch."""
    registry = HookRegistry()
    events_triggered = []

    @registry.on_step_success
    def sync_success_hook(event: LifecycleEvent, ctx: ExecutionContext, payload: dict) -> None:
        events_triggered.append(f"sync_{payload.get('step_id')}")

    @registry.on_step_failure
    async def async_failure_hook(
        event: LifecycleEvent, ctx: ExecutionContext, payload: dict
    ) -> None:
        events_triggered.append(f"async_{payload.get('step_id')}")

    assert registry.has_hooks(LifecycleEvent.STEP_SUCCESS) is True
    assert registry.has_hooks(LifecycleEvent.STEP_FAILURE) is True
    assert registry.has_hooks(LifecycleEvent.WORKFLOW_START) is False

    # Trigger step success
    await registry.trigger(LifecycleEvent.STEP_SUCCESS, context, {"step_id": "step_1"})
    assert events_triggered == ["sync_step_1"]

    # Trigger step failure
    await registry.trigger(LifecycleEvent.STEP_FAILURE, context, {"step_id": "step_2"})
    assert events_triggered == ["sync_step_1", "async_step_2"]


@pytest.mark.asyncio
async def test_hook_registry_all_decorators() -> None:
    """Verify all decorator helper methods register correctly."""
    registry = HookRegistry()

    @registry.on_workflow_start
    def h1(e, c, p):
        pass

    @registry.on_workflow_success
    def h2(e, c, p):
        pass

    @registry.on_workflow_failure
    def h3(e, c, p):
        pass

    @registry.on_workflow_cancelled
    def h4(e, c, p):
        pass

    @registry.on_step_start
    def h5(e, c, p):
        pass

    @registry.on_step_retry
    def h6(e, c, p):
        pass

    @registry.on_step_skipped
    def h7(e, c, p):
        pass

    assert len(registry.get_registered_hooks(LifecycleEvent.WORKFLOW_START)) == 1
    assert len(registry.get_registered_hooks(LifecycleEvent.WORKFLOW_SUCCESS)) == 1
    assert len(registry.get_registered_hooks(LifecycleEvent.WORKFLOW_FAILURE)) == 1
    assert len(registry.get_registered_hooks(LifecycleEvent.WORKFLOW_CANCELLED)) == 1
    assert len(registry.get_registered_hooks(LifecycleEvent.STEP_START)) == 1
    assert len(registry.get_registered_hooks(LifecycleEvent.STEP_RETRY)) == 1
    assert len(registry.get_registered_hooks(LifecycleEvent.STEP_SKIPPED)) == 1


@pytest.mark.asyncio
async def test_hook_registry_unregister_and_clear(context: ExecutionContext) -> None:
    """Verify unregistering hooks and clearing registry."""
    registry = HookRegistry()

    def dummy_hook(event: LifecycleEvent, ctx: ExecutionContext, payload: dict) -> None:
        pass

    registry.register(LifecycleEvent.WORKFLOW_START, dummy_hook)
    assert registry.has_hooks(LifecycleEvent.WORKFLOW_START) is True

    registry.unregister(LifecycleEvent.WORKFLOW_START, dummy_hook)
    assert registry.has_hooks(LifecycleEvent.WORKFLOW_START) is False

    registry.register(LifecycleEvent.WORKFLOW_START, dummy_hook)
    registry.clear()
    assert registry.has_hooks(LifecycleEvent.WORKFLOW_START) is False


@pytest.mark.asyncio
async def test_hook_registry_exception_isolation(context: ExecutionContext) -> None:
    """Verify exception in hook callback is isolated and doesn't crash trigger caller."""
    registry = HookRegistry()

    def faulty_hook(event: LifecycleEvent, ctx: ExecutionContext, payload: dict) -> None:
        raise RuntimeError("Bug in hook code!")

    registry.register(LifecycleEvent.WORKFLOW_START, faulty_hook)

    # Should log exception silently and complete without raising
    await registry.trigger(LifecycleEvent.WORKFLOW_START, context)


def test_get_hook_registry_singleton() -> None:
    """Verify get_hook_registry returns LRU-cached singleton instance."""
    r1 = get_hook_registry()
    r2 = get_hook_registry()
    assert r1 is r2
