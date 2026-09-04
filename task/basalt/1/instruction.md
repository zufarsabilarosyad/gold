Implement workflow failure policies, attempt reporting, and checkpoint resumption in Basalt.

For `on_failure: retry`, execute the initial attempt plus up to `max_retries` additional attempts using the step backoff policy. When jitter is disabled, delay intervals must be deterministic; recovery unblocks downstream dependents. Record totals in `WorkflowRunResult.step_attempts: dict[str, int] = Field(default_factory=dict)`.

Emit `STEP_START` with `step_id` and one-based `attempt` on every attempt. Before each backoff delay, emit `STEP_RETRY` with `attempt`, `delay_seconds`, and error. Terminal hooks dispatch once: `STEP_SUCCESS` includes `step_id`, `attempt`, and output; `STEP_FAILURE` includes `step_id`, `attempt`, and error.

Add `WorkflowRunResult.step_attempt_history` keyed by step ID. Each entry contains `attempt`, `state`, `delay_seconds`, and `error`. Recoverable failures record state `RETRYING`; terminal entries have zero delay. Cancellation during backoff appends a `CANCELLED` entry for that attempt. Skipped steps have no history.

By default, `fail_fast` aborts pending work on terminal failure. With `on_failure: continue`, skip only direct and transitive child steps while independent branches proceed. Mark skipped steps `StepState.SKIPPED`, emit `STEP_SKIPPED` (`step_id`), and mark the workflow `FAILED`. Cancellation during execution or backoff halts further attempts and ends `CANCELLED`.

Support resumption via `WorkflowRunner.run_async(resume_from=...)` and `BasaltEngine.retry_run(run_id, new_run_id=None)`. Resuming requires status `FAILED`, `TIMEOUT`, or `CANCELLED`, and identical DAG and step IDs, raising `ValueError` on mismatch. Reuse completed steps without re-executing or dispatching step hooks, preserving outputs, counts, and histories. Reset non-completed steps with fresh retry allowances while attempt numbers, histories, and hook payloads remain cumulative.

Expose `parent_run_id`, incrementing `resume_depth`, and ordered `reused_step_ids` on results, SQLite storage, REST endpoints, and the CLI (`run retry`, status tables, and JSON details).

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
