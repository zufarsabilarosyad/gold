"""Async Trigger Event Dispatcher Subsystem Module for Basalt Engine.

Provides TriggerDispatcher managing active event triggers (Cron, Interval, Webhook),
running background evaluation polling loops, dispatching TriggerEvents to registered listeners,
and triggering workflow execution runs.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from basalt.core.dag.ast import DAGSpec, TriggerType
from basalt.core.triggers.base import BaseTrigger, TriggerEvent
from basalt.core.triggers.cron import CronTrigger
from basalt.core.triggers.interval import IntervalTrigger
from basalt.core.triggers.webhook import WebhookTrigger
from basalt.utils.logger import get_logger

logger = get_logger(__name__)

# Callback type definition for trigger event listeners
EventListener = Callable[[TriggerEvent], Awaitable[None]]


class TriggerDispatcher:
    """Async event dispatcher evaluating active triggers and notifying workflow execution listeners."""

    def __init__(self, poll_interval_seconds: float = 1.0) -> None:
        self.poll_interval_seconds = max(0.1, float(poll_interval_seconds))
        self._triggers: dict[str, BaseTrigger] = {}
        self._listeners: list[EventListener] = []
        self._event_queue: asyncio.Queue[TriggerEvent] = asyncio.Queue()
        self._polling_task: asyncio.Task | None = None
        self._dispatch_task: asyncio.Task | None = None
        self._running: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        """Check if background evaluation loop is currently running."""
        return self._running

    @property
    def pending_event_count(self) -> int:
        """Count of unconsumed trigger events pending in event queue."""
        return self._event_queue.qsize()

    def register_trigger(self, trigger: BaseTrigger) -> None:
        """Register an event trigger instance.

        Args:
            trigger: BaseTrigger subclass instance (CronTrigger, IntervalTrigger, WebhookTrigger).
        """
        self._triggers[trigger.spec.id] = trigger
        logger.info(
            f"Registered {trigger.__class__.__name__} '{trigger.spec.id}' for DAG '{trigger.dag_id}'"
        )

    def register_dag_triggers(self, dag: DAGSpec) -> list[BaseTrigger]:
        """Instantiate and register all triggers defined in a DAGSpec AST.

        Args:
            dag: Workflow DAGSpec object.

        Returns:
            List of newly registered BaseTrigger objects.
        """
        registered: list[BaseTrigger] = []

        for trig_spec in dag.triggers:
            if trig_spec.type == TriggerType.CRON:
                trig = CronTrigger(trig_spec, dag_id=dag.id)
            elif trig_spec.type == TriggerType.INTERVAL:
                trig = IntervalTrigger(trig_spec, dag_id=dag.id)
            elif trig_spec.type == TriggerType.WEBHOOK:
                trig = WebhookTrigger(trig_spec, dag_id=dag.id)
            else:
                logger.warning(f"Unsupported trigger type '{trig_spec.type}' in DAG '{dag.id}'")
                continue

            self.register_trigger(trig)
            registered.append(trig)

        return registered

    def unregister_trigger(self, trigger_id: str) -> bool:
        """Remove a trigger by ID from the dispatcher.

        Args:
            trigger_id: Identifier of trigger to remove.

        Returns:
            True if trigger was found and removed, False otherwise.
        """
        if trigger_id in self._triggers:
            trig = self._triggers.pop(trigger_id)
            trig.stop()
            logger.info(f"Unregistered trigger '{trigger_id}' from dispatcher")
            return True
        return False

    def get_trigger(self, trigger_id: str) -> BaseTrigger | None:
        """Fetch registered trigger instance by ID."""
        return self._triggers.get(trigger_id)

    def pause_trigger(self, trigger_id: str) -> bool:
        """Pause a trigger by ID."""
        trig = self.get_trigger(trigger_id)
        if trig:
            trig.pause()
            return True
        return False

    def resume_trigger(self, trigger_id: str) -> bool:
        """Resume a paused trigger by ID."""
        trig = self.get_trigger(trigger_id)
        if trig:
            trig.resume()
            return True
        return False

    def list_triggers(self, dag_id: str | None = None) -> list[BaseTrigger]:
        """Query registered triggers with optional DAG filter."""
        if dag_id:
            return [t for t in self._triggers.values() if t.dag_id == dag_id]
        return list(self._triggers.values())

    def add_listener(self, listener: EventListener) -> None:
        """Register an async callback listener to receive fired TriggerEvents."""
        if listener not in self._listeners:
            self._listeners.append(listener)
            logger.debug(f"Added trigger event listener callback ({listener.__name__})")

    def remove_listener(self, listener: EventListener) -> bool:
        """Remove a registered callback listener."""
        if listener in self._listeners:
            self._listeners.remove(listener)
            return True
        return False

    def clear(self) -> None:
        """Clear all registered triggers and listeners."""
        for trig in self._triggers.values():
            trig.stop()
        self._triggers.clear()
        self._listeners.clear()
        logger.info("Cleared all registered triggers and listeners from dispatcher")

    async def emit_event(self, event: TriggerEvent) -> None:
        """Manually push a TriggerEvent onto the event queue for processing."""
        await self._event_queue.put(event)
        logger.debug(f"Emitted TriggerEvent '{event.event_id}' for trigger '{event.trigger_id}'")

    async def _evaluate_triggers_tick(self, now: datetime) -> list[TriggerEvent]:
        """Evaluate all active registered triggers for the current tick timestamp."""
        events: list[TriggerEvent] = []

        for trig in list(self._triggers.values()):
            if not trig.is_active:
                continue

            try:
                event = trig.evaluate(current_time=now)
                if event is not None:
                    events.append(event)
            except Exception as e:
                logger.error(
                    f"Error evaluating trigger '{trig.spec.id}' for DAG '{trig.dag_id}': {e}",
                    exc_info=True,
                )

        return events

    async def process_tick_immediately(self, current_time: datetime | None = None) -> int:
        """Trigger an immediate evaluation tick and dispatch generated events synchronously.

        Returns:
            Count of triggered events.
        """
        now = current_time or datetime.now(UTC)
        events = await self._evaluate_triggers_tick(now)

        for ev in events:
            for listener in list(self._listeners):
                try:
                    await listener(ev)
                except Exception as e:
                    logger.error(f"Listener error in process_tick_immediately: {e}", exc_info=True)

        return len(events)

    async def _polling_loop(self) -> None:
        """Background loop periodically evaluating active triggers."""
        logger.info(
            f"TriggerDispatcher polling loop started (poll_interval={self.poll_interval_seconds}s)"
        )

        while self._running:
            try:
                now = datetime.now(UTC)
                events = await self._evaluate_triggers_tick(now)

                for ev in events:
                    await self._event_queue.put(ev)

                await asyncio.sleep(self.poll_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"Unexpected error in TriggerDispatcher polling loop: {e}", exc_info=True
                )
                await asyncio.sleep(self.poll_interval_seconds)

        logger.info("TriggerDispatcher polling loop stopped")

    async def _dispatch_loop(self) -> None:
        """Background loop consuming fired TriggerEvents and invoking listeners."""
        logger.info("TriggerDispatcher event consumer loop started")

        while self._running:
            try:
                event = await self._event_queue.get()
                logger.info(
                    f"Dispatching TriggerEvent '{event.event_id}' (DAG='{event.dag_id}', Trigger='{event.trigger_id}')"
                )

                for listener in list(self._listeners):
                    try:
                        await listener(event)
                    except Exception as e:
                        logger.error(
                            f"Listener failed processing TriggerEvent '{event.event_id}': {e}",
                            exc_info=True,
                        )

                self._event_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"Unexpected error in TriggerDispatcher dispatch loop: {e}", exc_info=True
                )

        logger.info("TriggerDispatcher event consumer loop stopped")

    async def start(self) -> None:
        """Start background polling and event dispatching loops."""
        async with self._lock:
            if self._running:
                logger.warning("TriggerDispatcher is already running")
                return

            self._running = True
            self._polling_task = asyncio.create_task(self._polling_loop())
            self._dispatch_task = asyncio.create_task(self._dispatch_loop())
            logger.info("TriggerDispatcher background tasks successfully launched")

    async def stop(self) -> None:
        """Gracefully stop background polling and event dispatching loops."""
        async with self._lock:
            if not self._running:
                return

            self._running = False

            if self._polling_task:
                self._polling_task.cancel()
                try:
                    await self._polling_task
                except asyncio.CancelledError:
                    pass
                self._polling_task = None

            if self._dispatch_task:
                self._dispatch_task.cancel()
                try:
                    await self._dispatch_task
                except asyncio.CancelledError:
                    pass
                self._dispatch_task = None

            logger.info("TriggerDispatcher cleanly stopped")


_dispatcher_singleton: TriggerDispatcher | None = None


def get_trigger_dispatcher(poll_interval_seconds: float = 1.0) -> TriggerDispatcher:
    """Retrieve process-wide TriggerDispatcher singleton instance."""
    global _dispatcher_singleton
    if _dispatcher_singleton is None:
        _dispatcher_singleton = TriggerDispatcher(poll_interval_seconds=poll_interval_seconds)
    return _dispatcher_singleton
