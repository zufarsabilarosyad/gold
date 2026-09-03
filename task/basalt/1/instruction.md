Workflow steps already expose retry policies and an `on_failure` action, but
the runner treats every failed execution level as an unconditional fast-fail.
Make those policies part of real workflow execution.

A retry-enabled step must be attempted again after an executor failure until it
succeeds, its retry budget is exhausted, or the run is cancelled. Retry delay
uses the existing policy values; when jitter is disabled it must be
deterministic. Each attempt must be visible through the existing lifecycle
hooks and the final run detail must retain the terminal step state, output, and
attempt count. A successful retry is a successful step and its dependants may
run normally.

Keep `fail_fast` as the default: after a terminal failure, pending downstream
work is skipped and the run fails. With `on_failure: continue`, independent
branches and later work that does not depend on the failed step must still run,
while direct and transitive dependants remain skipped. The workflow should be
reported as failed if any step terminally fails. Cancellation during an
executor attempt or its retry wait must prevent another attempt and produce a
cancelled run. Surface attempt information through the existing run status
interfaces and persist it for SQLite-backed runs.

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
