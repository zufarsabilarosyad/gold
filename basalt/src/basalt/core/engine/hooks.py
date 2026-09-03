"""Workflow Lifecycle Hooks and Callback Registry Module for Basalt Engine.

Provides an asynchronous event hook system for reacting to workflow and step lifecycle events
(on_start, on_success, on_failure, on_retry, on_skip, on_cancelled) without coupling core engine logic.
"""

import inspect
from collections.abc import Awaitable, Callable
from enum import Enum
from functools import lru_cache
from typing import Any

from basalt.core.engine.context import ExecutionContext
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class LifecycleEvent(str, Enum):
    """Supported workflow and step lifecycle event classifications."""

    WORKFLOW_START = "workflow_start"
    WORKFLOW_SUCCESS = "workflow_success"
    WORKFLOW_FAILURE = "workflow_failure"
    WORKFLOW_CANCELLED = "workflow_cancelled"

    STEP_START = "step_start"
    STEP_SUCCESS = "step_success"
    STEP_FAILURE = "step_failure"
    STEP_RETRY = "step_retry"
    STEP_SKIPPED = "step_skipped"


# Type alias for sync or async hook callback functions
HookCallback = Callable[
    [LifecycleEvent, ExecutionContext, dict[str, Any] | None], None | Awaitable[None]
]


class HookRegistry:
    """Registry managing subscription and execution of workflow lifecycle hooks."""

    def __init__(self) -> None:
        self._hooks: dict[LifecycleEvent, list[HookCallback]] = {
            event: [] for event in LifecycleEvent
        }

    def register(self, event: LifecycleEvent, callback: HookCallback) -> None:
        """Register a callback listener for a specific lifecycle event.

        Args:
            event: LifecycleEvent enum.
            callback: Sync or async callable taking (event, context, payload).
        """
        if callback not in self._hooks[event]:
            self._hooks[event].append(callback)
            logger.debug(f"Registered lifecycle hook for '{event.value}': {callback.__name__}")

    def unregister(self, event: LifecycleEvent, callback: HookCallback) -> None:
        """Unregister a callback listener for a lifecycle event.

        Args:
            event: LifecycleEvent enum.
            callback: Registered callback function to remove.
        """
        if callback in self._hooks[event]:
            self._hooks[event].remove(callback)
            logger.debug(f"Unregistered lifecycle hook for '{event.value}': {callback.__name__}")

    def clear(self) -> None:
        """Clear all registered lifecycle hooks."""
        for event in LifecycleEvent:
            self._hooks[event].clear()

    def get_registered_hooks(self, event: LifecycleEvent) -> list[HookCallback]:
        """Retrieve copy of registered callbacks list for event."""
        return self._hooks.get(event, []).copy()

    def has_hooks(self, event: LifecycleEvent) -> bool:
        """Check if any callbacks are registered for event."""
        return bool(self._hooks.get(event))

    async def trigger(
        self,
        event: LifecycleEvent,
        context: ExecutionContext,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Asynchronously trigger all registered callbacks for a lifecycle event.

        Exceptions raised by individual hooks are caught and logged to prevent
        failing the core engine execution pipeline.

        Args:
            event: Triggered LifecycleEvent.
            context: Active ExecutionContext.
            payload: Optional metadata dictionary (e.g. step_id, error_message, duration_ms).
        """
        callbacks = self._hooks.get(event, [])
        if not callbacks:
            return

        event_payload = payload or {}
        logger.debug(
            f"Triggering {len(callbacks)} hook(s) for event '{event.value}' in run '{context.run_id}'"
        )

        for callback in callbacks:
            try:
                if inspect.iscoroutinefunction(callback):
                    await callback(event, context, event_payload)
                else:
                    callback(event, context, event_payload)
            except Exception as exc:
                logger.error(
                    f"Lifecycle hook '{callback.__name__}' raised exception during '{event.value}': {exc}",
                    exc_info=True,
                )

    def on_workflow_start(self, callback: HookCallback) -> HookCallback:
        """Decorator helper for registering workflow_start hook."""
        self.register(LifecycleEvent.WORKFLOW_START, callback)
        return callback

    def on_workflow_success(self, callback: HookCallback) -> HookCallback:
        """Decorator helper for registering workflow_success hook."""
        self.register(LifecycleEvent.WORKFLOW_SUCCESS, callback)
        return callback

    def on_workflow_failure(self, callback: HookCallback) -> HookCallback:
        """Decorator helper for registering workflow_failure hook."""
        self.register(LifecycleEvent.WORKFLOW_FAILURE, callback)
        return callback

    def on_workflow_cancelled(self, callback: HookCallback) -> HookCallback:
        """Decorator helper for registering workflow_cancelled hook."""
        self.register(LifecycleEvent.WORKFLOW_CANCELLED, callback)
        return callback

    def on_step_start(self, callback: HookCallback) -> HookCallback:
        """Decorator helper for registering step_start hook."""
        self.register(LifecycleEvent.STEP_START, callback)
        return callback

    def on_step_success(self, callback: HookCallback) -> HookCallback:
        """Decorator helper for registering step_success hook."""
        self.register(LifecycleEvent.STEP_SUCCESS, callback)
        return callback

    def on_step_failure(self, callback: HookCallback) -> HookCallback:
        """Decorator helper for registering step_failure hook."""
        self.register(LifecycleEvent.STEP_FAILURE, callback)
        return callback

    def on_step_retry(self, callback: HookCallback) -> HookCallback:
        """Decorator helper for registering step_retry hook."""
        self.register(LifecycleEvent.STEP_RETRY, callback)
        return callback

    def on_step_skipped(self, callback: HookCallback) -> HookCallback:
        """Decorator helper for registering step_skipped hook."""
        self.register(LifecycleEvent.STEP_SKIPPED, callback)
        return callback


@lru_cache(maxsize=1)
def get_hook_registry() -> HookRegistry:
    """Retrieve global singleton instance of HookRegistry."""
    return HookRegistry()
