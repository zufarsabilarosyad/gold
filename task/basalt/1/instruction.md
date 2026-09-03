Right now, Basalt's workflow runner immediately aborts whenever a level fails, ignoring step-level retry policies and the `continue` failure action. We need real retry loops and branch-aware failure handling wired into the engine.

When a step fails with `on_failure: retry`, retry it up to `max_retries` times until it either completes, runs out of attempts, or gets cancelled. Make sure backoff delays are calculated without randomness when `jitter` is false. Each execution attempt needs to fire the standard lifecycle hooks (`STEP_START`, `STEP_RETRY`, `STEP_SUCCESS`, or `STEP_FAILURE`) carrying the current attempt number and retry delay. If a step recovers on retry, let downstream dependent tasks execute as usual.

Preserve `fail_fast` as the default behavior: terminally failed steps skip all remaining pending work across the workflow. When a step uses `on_failure: continue`, skip its direct and transitive child tasks, but allow independent parallel branches and later unrelated steps to run to completion. If any step ends in failure, mark the overall workflow status as `FAILED`.

Cancelling an active run—whether inside a running task or during a retry backoff sleep—must abort immediately, prevent any future attempts, and leave the workflow in a `CANCELLED` state. Finally, track and persist per-step attempt counts in SQLite storage, and include them in the run status API responses and CLI output.

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
