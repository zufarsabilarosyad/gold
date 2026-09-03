"""Complete Async DAG Workflow Lifecycle Runner Subsystem Module for Basalt Engine.

Orchestrates topological execution level progression, conditional when evaluation,
parallel step execution via WorkerPool, state machine transitions, lifecycle hook dispatch,
cancellation support, batch execution, and error handling.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from basalt.core.dag.ast import DAGSpec, OnFailureAction, StepSpec
from basalt.core.dag.sorter import DAGSorter
from basalt.core.dag.validator import DAGValidator
from basalt.core.engine.retry_control import RetryController, RetrySchedule

from basalt.core.engine.context import ExecutionContext
from basalt.core.engine.evaluator import ExpressionEvaluator
from basalt.core.engine.hooks import HookRegistry, LifecycleEvent, get_hook_registry
from basalt.core.engine.state_machine import StateMachine, StepState, WorkflowState
from basalt.core.executors.pool import WorkerPool
from basalt.utils.crypto import generate_run_id
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class WorkflowRunResult(BaseModel):
    """Complete summary result container returned after workflow execution."""

    run_id: str
    dag_id: str
    state: WorkflowState
    start_time: datetime
    end_time: datetime
    duration_ms: float
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    step_states: dict[str, StepState] = Field(default_factory=dict)
    step_attempts: dict[str, int] = Field(default_factory=dict)
    error_message: str | None = None


    def is_success(self) -> bool:
        """Check if workflow finished in COMPLETED state."""
        return self.state == WorkflowState.COMPLETED

    def is_failed(self) -> bool:
        """Check if workflow finished in FAILED or TIMEOUT state."""
        return self.state in (WorkflowState.FAILED, WorkflowState.TIMEOUT)


class WorkflowRunner:
    """Core DAG Workflow Execution Runner engine."""

    def __init__(
        self,
        worker_pool: WorkerPool | None = None,
        hook_registry: HookRegistry | None = None,
    ) -> None:
        self.worker_pool = worker_pool or WorkerPool()
        self.hook_registry = hook_registry or get_hook_registry()
        self._active_runs: dict[str, asyncio.Event] = {}

    def get_active_run_ids(self) -> list[str]:
        """Retrieve list of currently executing workflow run IDs."""
        return list(self._active_runs.keys())

    def is_run_active(self, run_id: str) -> bool:
        """Check if a specific workflow run ID is currently active."""
        return run_id in self._active_runs

    def validate_dag(self, dag: DAGSpec) -> None:
        """Validate DAG structural integrity before execution.

        Args:
            dag: DAGSpec AST model definition.
        """
        DAGValidator.validate_dag(dag)

    def run(
        self,
        dag: DAGSpec,
        inputs: dict[str, Any] | None = None,
        env: dict[str, str] | None = None,
        run_id: str | None = None,
    ) -> WorkflowRunResult:
        """Synchronous wrapper for running a DAG workflow to completion."""
        return asyncio.run(self.run_async(dag=dag, inputs=inputs, env=env, run_id=run_id))

    async def run_async(
        self,
        dag: DAGSpec,
        inputs: dict[str, Any] | None = None,
        env: dict[str, str] | None = None,
        run_id: str | None = None,
    ) -> WorkflowRunResult:
        """Asynchronously execute a DAG workflow from start to finish.

        Args:
            dag: DAGSpec AST model definition.
            inputs: Initial input parameters dictionary.
            env: Initial environment variables dictionary.
            run_id: Custom or auto-generated workflow run identifier.

        Returns:
            WorkflowRunResult snapshot container.
        """
        # Validate structural integrity
        self.validate_dag(dag)

        active_run_id = run_id or generate_run_id()
        cancel_event = asyncio.Event()
        self._active_runs[active_run_id] = cancel_event

        start_time = datetime.now(UTC)

        context = ExecutionContext(
            run_id=active_run_id,
            dag_id=dag.id,
            inputs=inputs,
            env=env,
        )

        logger.info(
            f"Starting workflow run '{active_run_id}' for DAG '{dag.id}' with {len(dag.steps)} steps."
        )

        # Trigger WORKFLOW_START hook
        await self.hook_registry.trigger(LifecycleEvent.WORKFLOW_START, context)

        workflow_state = WorkflowState.RUNNING
        error_message: str | None = None

        try:
            # 1. Topological sorting into parallel execution levels
            execution_levels = DAGSorter.get_execution_levels(dag)

            # 2. Iterate through level progression
            for level_idx, level_steps in enumerate(execution_levels):
                if cancel_event.is_set():
                    logger.warning(
                        f"Workflow run '{active_run_id}' cancelled before level {level_idx + 1}"
                    )
                    workflow_state = WorkflowState.CANCELLED
                    error_message = "Workflow execution cancelled by request."
                    break

                logger.debug(
                    f"Run '{active_run_id}' executing level {level_idx + 1}/{len(execution_levels)} "
                    f"with {len(level_steps)} step(s)"
                )

                # Separate steps to execute vs steps to skip due to conditions/upstream failures
                runnable_steps: list[StepSpec] = []

                for step in level_steps:
                    # Check upstream dependency states
                    if self._should_skip_due_to_upstream(step, context):
                        logger.info(f"Skipping step '{step.id}' due to upstream failure/skip.")
                        context.set_step_state(step.id, StepState.SKIPPED)
                        await self.hook_registry.trigger(
                            LifecycleEvent.STEP_SKIPPED, context, {"step_id": step.id}
                        )
                        continue

                    # Evaluate conditional 'when' expression if present
                    if step.when:
                        condition_pass = ExpressionEvaluator.evaluate_condition(step.when, context)
                        if not condition_pass:
                            logger.info(
                                f"Skipping step '{step.id}' because condition 'when: {step.when}' evaluated to False."
                            )
                            context.set_step_state(step.id, StepState.SKIPPED)
                            await self.hook_registry.trigger(
                                LifecycleEvent.STEP_SKIPPED, context, {"step_id": step.id}
                            )
                            continue

                    runnable_steps.append(step)

                if not runnable_steps:
                    continue

                # Execute level steps in parallel via WorkerPool with retry support
                level_results = await self._execute_level(
                    runnable_steps, context, cancel_event
                )

                # Process results and trigger step completion hooks
                level_failed = False
                fast_fail = False
                for step in runnable_steps:
                    state, output, step_err = level_results.get(
                        step.id, (StepState.FAILED, {}, "No result")
                    )
                    attempt = context.get_step_attempt(step.id)
                    if state == StepState.COMPLETED:
                        await self.hook_registry.trigger(
                            LifecycleEvent.STEP_SUCCESS,
                            context,
                            {"step_id": step.id, "attempt": attempt, "output": output},
                        )
                    elif state == StepState.CANCELLED:
                        pass
                    else:
                        level_failed = True
                        if not error_message:
                            error_message = f"Step '{step.id}' failed: {step_err}"
                        await self.hook_registry.trigger(
                            LifecycleEvent.STEP_FAILURE,
                            context,
                            {"step_id": step.id, "attempt": attempt, "error": step_err},
                        )
                        fast_fail = fast_fail or step.on_failure == OnFailureAction.FAIL_FAST or step.on_failure != OnFailureAction.CONTINUE

                # Fast-fail workflow if a step failed with fail_fast
                if fast_fail:
                    logger.warning(
                        f"Level execution failed in run '{active_run_id}'. Aborting downstream steps."
                    )
                    for rem_level in execution_levels[level_idx + 1 :]:
                        for rem_step in rem_level:
                            if context.get_step_state(rem_step.id) == StepState.PENDING:
                                context.set_step_state(rem_step.id, StepState.SKIPPED)
                                await self.hook_registry.trigger(
                                    LifecycleEvent.STEP_SKIPPED, context, {"step_id": rem_step.id}
                                )
                    break

            # Aggregate final workflow state
            if workflow_state == WorkflowState.RUNNING:
                all_states = context.get_all_step_states()
                workflow_state = StateMachine.aggregate_workflow_state(all_states)


        except Exception as exc:
            logger.error(
                f"Workflow execution pipeline crashed for run '{active_run_id}': {exc}",
                exc_info=True,
            )
            workflow_state = WorkflowState.FAILED
            error_message = f"Pipeline execution error: {exc}"
        finally:
            self._active_runs.pop(active_run_id, None)

        end_time = datetime.now(UTC)
        duration_ms = (end_time - start_time).total_seconds() * 1000.0

        # Trigger final workflow lifecycle hooks
        if workflow_state == WorkflowState.COMPLETED:
            await self.hook_registry.trigger(LifecycleEvent.WORKFLOW_SUCCESS, context)
        elif workflow_state == WorkflowState.CANCELLED:
            await self.hook_registry.trigger(LifecycleEvent.WORKFLOW_CANCELLED, context)
        elif workflow_state in (WorkflowState.FAILED, WorkflowState.TIMEOUT):
            await self.hook_registry.trigger(
                LifecycleEvent.WORKFLOW_FAILURE, context, {"error": error_message}
            )

        logger.info(
            f"Workflow run '{active_run_id}' finished in state '{workflow_state.value}' "
            f"in {duration_ms:.2f}ms."
        )

        return WorkflowRunResult(
            run_id=active_run_id,
            dag_id=dag.id,
            state=workflow_state,
            start_time=start_time,
            end_time=end_time,
            duration_ms=duration_ms,
            inputs=context.inputs.copy(),
            outputs=context.get_all_step_outputs(),
            step_states=context.get_all_step_states(),
            step_attempts=context.step_attempts(),
            error_message=error_message,
        )

    def is_run_active(self, run_id: str) -> bool:
        """Check if a workflow execution run is currently registered as active."""
        return run_id in self._active_runs

    async def _execute_level(
        self, steps: list[StepSpec], context: ExecutionContext, cancel_event: asyncio.Event
    ) -> dict[str, tuple[StepState, dict[str, Any], str | None]]:
        """Run independent steps concurrently, including their individual retry loops."""
        results = await asyncio.gather(
            *(self._execute_with_retry(step, context, cancel_event) for step in steps)
        )
        return dict(zip((step.id for step in steps), results))

    async def _execute_with_retry(
        self, step: StepSpec, context: ExecutionContext, cancel_event: asyncio.Event
    ) -> tuple[StepState, dict[str, Any], str | None]:
        """Execute a step until it succeeds, exhausts retries, or cancellation wins."""
        policy = step.retry_policy
        retries = policy.max_retries if policy and step.on_failure == OnFailureAction.RETRY else 0
        controller = RetryController(RetrySchedule(policy, retries > 0), cancel_event)

        async def execute_attempt() -> tuple[StepState, dict[str, Any], str | None]:
            attempt = context.begin_attempt(step.id, retries)
            await self.hook_registry.trigger(
                LifecycleEvent.STEP_START, context, {"step_id": step.id, "attempt": attempt}
            )
            return await self.worker_pool.execute_step(step, context, cancel_event=cancel_event)


        async def announce_retry(attempt: int, error: str | None, delay: float) -> None:
            context.mark_retrying(step.id, error or "Step execution failed.", delay)
            await self.hook_registry.trigger(
                LifecycleEvent.STEP_RETRY,
                context,
                {"step_id": step.id, "attempt": attempt, "error": error, "delay_seconds": delay},
            )

        result = await controller.run(execute_attempt, announce_retry)
        if result[0] == StepState.CANCELLED:
            context.set_step_state(step.id, StepState.CANCELLED)
        return result


    def cancel_run(self, run_id: str) -> bool:
        """Signal cancellation for an active workflow run ID.

        Args:
            run_id: Active workflow run identifier.

        Returns:
            True if run was active and cancellation signal was sent, False otherwise.
        """
        cancel_event = self._active_runs.get(run_id)
        if cancel_event:
            cancel_event.set()
            logger.warning(f"Cancellation requested for active workflow run '{run_id}'")
            return True
        return False

    async def run_batch_async(
        self,
        dags: list[DAGSpec],
        inputs_list: list[dict[str, Any] | None] | None = None,
    ) -> list[WorkflowRunResult]:
        """Execute a batch list of DAG workflows concurrently.

        Args:
            dags: List of DAGSpec definitions.
            inputs_list: Optional parallel list of input dictionaries.

        Returns:
            List of WorkflowRunResult objects in original input order.
        """
        if not dags:
            return []

        tasks = []
        for i, dag in enumerate(dags):
            dag_inputs = inputs_list[i] if (inputs_list and i < len(inputs_list)) else None
            tasks.append(self.run_async(dag=dag, inputs=dag_inputs))

        return await asyncio.gather(*tasks)

    def _should_skip_due_to_upstream(
        self,
        step: StepSpec,
        context: ExecutionContext,
    ) -> bool:
        """Check if step should be skipped because any of its upstream dependencies failed or were skipped."""
        if not step.depends_on:
            return False

        for parent_id in step.depends_on:
            parent_state = context.get_step_state(parent_id)
            if parent_state in (
                StepState.FAILED,
                StepState.TIMEOUT,
                StepState.SKIPPED,
                StepState.CANCELLED,
            ):
                return True

        return False


async def run_dag_workflow(
    dag: DAGSpec,
    inputs: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> WorkflowRunResult:
    """Helper shortcut function to run a single DAG workflow using standard runner."""
    runner = WorkflowRunner()
    return await runner.run_async(dag=dag, inputs=inputs, env=env)
