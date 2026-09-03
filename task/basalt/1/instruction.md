Right now, a single step error crashes Basalt's whole pipeline. The runner just gives up, ignoring configured retry policies and failure continuation options.

First, add `step_attempts: dict[str, int] = Field(default_factory=dict)` to `WorkflowRunResult` so callers know how many times each step ran. If a step has `on_failure: retry`, keep trying it up to `max_retries` extra times until it either passes or runs out of tries. Use the step's backoff settings for delays; when `jitter` is disabled, the delays have to be exact and reproducible.

Make sure lifecycle hooks fire on every try. Emit `STEP_START` with the attempt number, `STEP_RETRY` before each backoff sleep (with `attempt`, `delay_seconds`, and `error`), and finally `STEP_SUCCESS` or `STEP_FAILURE` (passing `attempt` and `error`) once the step finishes. If a retried step recovers, let dependent child steps proceed as usual.

`fail_fast` stays the default. Under `fail_fast`, any fatal error cancels all remaining pending steps. But if a step is set to `continue`, only its direct and downstream children should be skipped. Unrelated branches must run to the end. If any step fails along the way, the workflow's final state is `FAILED`.

Cancellation takes priority everywhere. If a run is cancelled while a step is running or waiting between retries, stop execution immediately, don't start new attempts, and mark the workflow `CANCELLED`. Lastly, write attempt numbers to SQLite (`StepRunModel.attempt`). Include them in the status API and show them in the CLI (`Attempts` column in run status tables, and `attempt` in step details).

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
