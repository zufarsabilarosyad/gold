Right now, a single step failure aborts Basalt's entire workflow run, skipping all remaining work and ignoring configured retry policies and failure continuation actions.

First, add `step_attempts: dict[str, int] = Field(default_factory=dict)` to `WorkflowRunResult` to record how many times each step ran. When a step specifies `on_failure: retry`, retry it after failures up to `max_retries` additional times (yielding `1 + max_retries` total attempts) using the step's backoff policy. When `jitter` is disabled, retry delay intervals must be deterministic.

Recoverable failures must dispatch `STEP_RETRY` before each backoff sleep, including the current `attempt`, `delay_seconds`, and error. The existing success or failure hooks continue to represent the terminal step outcome. When a retried step recovers, downstream dependent steps must execute normally.

Preserve `fail_fast` as the default failure behavior, aborting all downstream pending work when a step terminally fails. When a step specifies `on_failure: continue`, skip only its direct and transitive child steps, allowing independent parallel branches and unrelated later steps to run to completion. Skipped steps must be set to `StepState.SKIPPED` and emit `STEP_SKIPPED` (passing `step_id`). If any step ends in failure under `continue`, mark the overall workflow status as `FAILED`.

Cancelling an active run while a step is executing or waiting in retry sleep must halt execution immediately, prevent any future attempts, and leave the workflow in a `CANCELLED` state. Persist attempt numbers in SQLite storage (`StepRunModel.attempt`), return them in REST API run status responses, and display them in CLI output (`Attempts` column in run status tables and `attempt` in step details).

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
