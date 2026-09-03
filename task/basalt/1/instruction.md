Right now, if any step in Basalt fails, the runner immediately aborts the whole workflow and skips everything else. Even though steps already define `retry_policy` and `on_failure` settings, the runner simply doesn't use them.

We need `WorkflowRunner` to actually handle retries and branch continuation:

- **Retries**: If a step has `on_failure: retry`, retry it after failures up to `max_retries` times (1 initial attempt + `max_retries` retries) using the configured backoff delays. When `jitter` is disabled, delays must be deterministic. If a retry succeeds, downstream dependants should run normally.
- **Hooks**: Fire `STEP_START` on every attempt with the attempt count. Fire `STEP_RETRY` before sleeping between retries (passing `attempt`, `delay_seconds`, and `error`). Fire `STEP_SUCCESS` or `STEP_FAILURE` when finished.
- **Failure actions**: Keep `fail_fast` as the default (skip all downstream pending work on failure). If a step has `on_failure: continue`, skip only its direct and transitive children; let independent branches and later unrelated steps finish running. If any step fails terminally, mark the overall workflow as `FAILED`.
- **Cancellation**: Cancelling a run while a step is executing or waiting in a retry sleep must stop immediately, prevent subsequent attempts, and leave the workflow `CANCELLED`.
- **Storage**: Record attempt counts in SQLite (`StepRunModel.attempt`) and expose them in the run status API and CLI views.

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
