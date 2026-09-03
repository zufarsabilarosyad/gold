"""Unit and Integration Tests for Event Triggers and Dispatcher Subsystem.

Validates BaseTrigger, CronTrigger 5-field schedule math, IntervalTrigger timers,
WebhookTrigger HMAC signature security, WebhookRegistry, and TriggerDispatcher async polling loops.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from basalt.core.dag.ast import DAGSpec, ExecutorType, StepSpec, TriggerSpec, TriggerType
from basalt.core.triggers.base import TriggerEvent, TriggerStatus
from basalt.core.triggers.cron import CronEvaluator, CronParseError, CronTrigger
from basalt.core.triggers.dispatcher import TriggerDispatcher, get_trigger_dispatcher
from basalt.core.triggers.interval import (
    IntervalCalculator,
    IntervalTrigger,
    create_interval_trigger,
)
from basalt.core.triggers.webhook import (
    WebhookAuthenticationError,
    WebhookRegistry,
    WebhookSignatureVerifier,
    create_webhook_trigger,
)


def test_base_trigger_lifecycle_and_evaluate() -> None:
    """Verify BaseTrigger status transitions and evaluation behavior."""
    spec = TriggerSpec(id="trig_base", type=TriggerType.INTERVAL, interval_seconds=10.0)
    trig = IntervalTrigger(trigger_spec=spec, dag_id="dag_base")

    assert trig.is_active is True
    assert trig.status == TriggerStatus.ACTIVE

    trig.pause()
    assert trig.is_active is False
    assert trig.status == TriggerStatus.PAUSED
    assert trig.evaluate() is None

    trig.resume()
    assert trig.is_active is True

    trig.stop()
    assert trig.is_active is False
    assert trig.status == TriggerStatus.STOPPED


def test_cron_evaluator_syntax_and_fields() -> None:
    """Verify CronEvaluator 5-field cron parsing, steps, ranges, and validation."""
    # Wildcards
    assert CronEvaluator.validate_cron_expression("* * * * *") is True
    assert CronEvaluator.validate_cron_expression("0 0 * * *") is True

    # Step and ranges
    assert CronEvaluator.validate_cron_expression("*/15 9-17 1,15 * 1-5") is True

    # Invalid syntaxes
    assert CronEvaluator.validate_cron_expression("invalid cron") is False
    assert CronEvaluator.validate_cron_expression("0 0 0 0") is False  # 4 fields

    with pytest.raises(CronParseError):
        CronEvaluator.parse_field("60-70", 0, 59)

    # Explanation helper
    explanation = CronEvaluator.explain("0 12 * * *")
    assert "minute=0" in explanation
    assert "hour=12" in explanation


def test_cron_trigger_matching_and_next_fire_time() -> None:
    """Verify CronTrigger timestamp matching and next fire time searching."""
    spec = TriggerSpec(id="cron_trig", type=TriggerType.CRON, cron="30 14 * * *")
    trig = CronTrigger(trigger_spec=spec, dag_id="dag_cron")

    # Match time: 14:30 UTC
    match_dt = datetime(2026, 8, 6, 14, 30, 0, tzinfo=UTC)
    non_match_dt = datetime(2026, 8, 6, 14, 31, 0, tzinfo=UTC)

    assert trig.should_fire(current_time=match_dt) is True
    assert trig.should_fire(current_time=non_match_dt) is False

    # Prevent duplicate firing in the same minute
    event = trig.evaluate(current_time=match_dt)
    assert event is not None
    assert event.trigger_id == "cron_trig"
    assert event.dag_id == "dag_cron"

    # Second evaluation in same minute should be rejected
    assert trig.should_fire(current_time=match_dt) is False

    # Next fire time search
    next_dt = trig.get_next_fire_time(current_time=match_dt)
    assert next_dt is not None
    assert next_dt.hour == 14
    assert next_dt.minute == 30
    assert next_dt.day == 7  # Next day at 14:30


def test_interval_calculator_and_trigger() -> None:
    """Verify IntervalCalculator conversions and IntervalTrigger timer evaluation."""
    secs = IntervalCalculator.to_seconds(minutes=5, hours=1)
    assert secs == 3900.0
    assert IntervalCalculator.format_interval(30.0) == "30.0s"
    assert IntervalCalculator.format_interval(3600.0) == "1.0h"

    trig = create_interval_trigger("int_trig", dag_id="dag_int", interval_seconds=2.0)
    start = datetime.now(UTC)
    trig.start_time = start

    # Immediately after start: should not fire
    assert trig.should_fire(current_time=start) is False

    # 3 seconds later: should fire
    later = start + timedelta(seconds=3)
    assert trig.should_fire(current_time=later) is True

    event = trig.evaluate(current_time=later)
    assert event is not None
    assert trig.fire_count == 1

    stats = trig.get_fire_stats()
    assert stats["fire_count"] == 1
    assert stats["interval_seconds"] == 2.0

    # Reset
    trig.reset()
    assert trig.fire_count == 0
    assert trig.last_fired_at is None


def test_webhook_signature_verifier_and_trigger() -> None:
    """Verify WebhookSignatureVerifier HMAC-SHA256 security and WebhookTrigger processing."""
    raw_body = b'{"action": "deploy", "env": "prod"}'
    secret = "super_secret_webhook_key_123"

    signature = WebhookSignatureVerifier.compute_signature(raw_body, secret)
    assert len(signature) == 64

    # Verify signature match
    assert (
        WebhookSignatureVerifier.verify_signature(
            payload_bytes=raw_body,
            secret=secret,
            signature_header=f"sha256={signature}",
        )
        is True
    )

    # WebhookTrigger processing
    trig = create_webhook_trigger("wh_trig", dag_id="dag_wh", secret=secret)
    headers = {"X-Basalt-Signature": f"sha256={signature}", "Content-Type": "application/json"}

    event = trig.process_webhook(
        raw_body=raw_body,
        headers=headers,
        payload_dict={"action": "deploy", "env": "prod"},
    )
    assert event.trigger_id == "wh_trig"
    assert event.dag_id == "dag_wh"
    assert event.payload["webhook_body"]["action"] == "deploy"

    # Invalid signature should raise WebhookAuthenticationError
    invalid_headers = {"X-Basalt-Signature": "sha256=invalid_hash_value"}
    with pytest.raises(WebhookAuthenticationError):
        trig.process_webhook(raw_body=raw_body, headers=invalid_headers)


def test_webhook_registry_operations() -> None:
    """Verify WebhookRegistry registration and active trigger query."""
    registry = WebhookRegistry()
    trig1 = create_webhook_trigger("wh_1", dag_id="dag_1")
    trig2 = create_webhook_trigger("wh_2", dag_id="dag_2", enabled=False)

    registry.register(trig1)
    registry.register(trig2)

    assert registry.get("wh_1") is trig1
    active = registry.list_active()
    assert len(active) == 1
    assert active[0].spec.id == "wh_1"

    assert registry.unregister("wh_1") is True
    assert registry.get("wh_1") is None

    registry.clear()
    assert len(registry.list_active()) == 0


@pytest.mark.asyncio
async def test_trigger_dispatcher_dag_registration_and_listener() -> None:
    """Verify TriggerDispatcher DAG AST parsing, listener callbacks, and immediate tick execution."""
    dispatcher = TriggerDispatcher(poll_interval_seconds=0.1)

    dag = DAGSpec(
        id="dag_dispatcher_test",
        name="Dispatcher Test DAG",
        steps=[StepSpec(id="s1", executor_type=ExecutorType.SUBPROCESS, command="echo 1")],
        triggers=[
            TriggerSpec(id="t_interval", type=TriggerType.INTERVAL, interval_seconds=1.0),
            TriggerSpec(id="t_webhook", type=TriggerType.WEBHOOK, webhook_secret="secret"),
        ],
    )

    triggers = dispatcher.register_dag_triggers(dag)
    assert len(triggers) == 2
    assert len(dispatcher.list_triggers(dag_id="dag_dispatcher_test")) == 2

    received_events: list[TriggerEvent] = []

    async def listener(event: TriggerEvent) -> None:
        received_events.append(event)

    dispatcher.add_listener(listener)

    # Process immediate tick with overdue interval
    past_time = datetime.now(UTC) + timedelta(seconds=5)
    fired_count = await dispatcher.process_tick_immediately(current_time=past_time)
    assert fired_count == 1
    assert len(received_events) == 1
    assert received_events[0].trigger_id == "t_interval"

    dispatcher.clear()
    assert len(dispatcher.list_triggers()) == 0


@pytest.mark.asyncio
async def test_trigger_dispatcher_background_polling_loop() -> None:
    """Verify TriggerDispatcher start/stop background polling loop."""
    dispatcher = TriggerDispatcher(poll_interval_seconds=0.1)

    trig = create_interval_trigger("fast_int", dag_id="dag_fast", interval_seconds=0.1)
    dispatcher.register_trigger(trig)

    received: list[TriggerEvent] = []

    async def sample_listener(ev: TriggerEvent) -> None:
        received.append(ev)

    dispatcher.add_listener(sample_listener)

    await dispatcher.start()
    assert dispatcher.is_running is True

    # Sleep to allow background polling loop to tick
    await asyncio.sleep(0.35)

    await dispatcher.stop()
    assert dispatcher.is_running is False
    assert len(received) >= 1
    assert received[0].trigger_id == "fast_int"


@pytest.mark.asyncio
async def test_dispatcher_singleton_and_event_queuing() -> None:
    """Verify get_trigger_dispatcher singleton and emit_event queue processing."""
    d1 = get_trigger_dispatcher()
    d2 = get_trigger_dispatcher()
    assert d1 is d2

    ev = TriggerEvent(trigger_id="t_manual", dag_id="dag_manual", trigger_type=TriggerType.WEBHOOK)
    await d1.emit_event(ev)
    assert d1.pending_event_count >= 1


def test_trigger_unregistration_and_listener_removal() -> None:
    """Verify unregister_trigger and remove_listener cleanup."""
    dispatcher = TriggerDispatcher()
    trig = create_interval_trigger("t_unreg", dag_id="dag_unreg", interval_seconds=10.0)
    dispatcher.register_trigger(trig)

    async def dummy_listener(event: TriggerEvent) -> None:
        pass

    dispatcher.add_listener(dummy_listener)
    assert len(dispatcher._listeners) == 1

    assert dispatcher.remove_listener(dummy_listener) is True
    assert len(dispatcher._listeners) == 0

    assert dispatcher.unregister_trigger("t_unreg") is True
    assert dispatcher.get_trigger("t_unreg") is None
