Right now, if any step in Basalt fails, the runner immediately aborts the whole workflow and skips everything else, ignoring configured retry policies and failure actions.

We need `WorkflowRunner` to honor step retries and branch continuation:

- **Model**: Add `step_attempts: dict[str, int] = Field(default_factory=dict)` to `WorkflowRunResult` mapping each executed step ID to its total number of attempts.
- **Retries**: When a step defines `on_failure: retry`, retry it after failures up to `max_retries` times (1 initial attempt + `max_retries` retries) using the configured backoff delays. When `jitter` is disabled, delays must be deterministic. If a retry succeeds, downstream dependants should execute normally.
- **Hooks**: Fire `STEP_START` on every attempt with `attempt`. Fire `STEP_RETRY` before sleeping between retries (passing `attempt`, `delay_seconds`, and `error`). Fire `STEP_SUCCESS` or `STEP_FAILURE` on step completion (passing `attempt` and `error` on failure).
- **Failure actions**: Keep `fail_fast` as the default (skip all remaining downstream work on failure). If a step has `on_failure: continue`, skip only its direct and transitive children; let independent branches and later unrelated tasks finish running. If any step ends failed, mark the workflow state as `FAILED`.
- **Cancellation**: Cancelling a run while a step is executing or waiting in retry sleep must halt execution immediately, prevent further attempts, and mark the workflow `CANCELLED`.
- **API & CLI**: Persist attempt counts in SQLite (`StepRunModel.attempt`), surface them in REST API run status responses, and display them in CLI output (`Attempts` table column and step details).

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
