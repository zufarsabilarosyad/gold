Add an in-memory workflow-run timeline. Export `RunTimeline`, `RunEvent`, `RunEventType`, `RunEventPage`, and `RunEventSummary` from `basalt.core.engine`.

`RunTimeline` requires nonempty run and DAG IDs. Its `append(type, *, step_id=None, data=None, timestamp=None)` accepts an event value or string, assigns the next one-based sequence, and returns an isolated event safe to modify. Supported strings are `workflow_started`, `step_started`, `step_succeeded`, `step_failed`, `step_skipped`, `workflow_succeeded`, `workflow_failed`, and `workflow_cancelled`. Event types expose the Boolean properties `is_workflow_event`, `is_step_event`, and `is_terminal`.

Events contain `sequence`, `run_id`, `dag_id`, `type`, `timestamp`, optional `step_id`, and dictionary `data`; the `type` field accepts an event value or supported string. Sequences are positive and identities nonempty. Timestamps require a timezone, normalize to UTC, and default to the current UTC time when appended. Copy nested input data. `snapshot()` returns a deep copy, and query results must also be safe to modify.

`restore(run_id, dag_id, events)` accepts event objects or dictionaries. Reject identity mismatches, noncontiguous one-based sequences, and timestamps that move backwards.

`query(*, event_types=None, step_id=None, after_sequence=0, limit=100)` filters by one or several event types and an exact step ID before paging. Passing `event_types=[]` matches nothing. The cursor is exclusive and nonnegative; limits are 1–200. Pages contain `run_id`, copied `events`, `next_after_sequence`, and `has_more`. The next cursor is the final returned sequence, and `has_more` indicates further filtered matches. Empty pages preserve the requested cursor.

`summarize()` returns `RunEventSummary` fields `run_id`, `total_events`, `first_timestamp`, `last_timestamp`, `elapsed_ms`, `event_counts`, `step_counts`, `started_step_ids`, `succeeded_step_ids`, `failed_step_ids`, `skipped_step_ids`, and `terminal_type`. Step lists follow observation order, and `terminal_type` is the last terminal workflow event in the timeline. Empty timelines use empty counts and `None` boundaries. `has_failures()` and `has_skips()` report whether the corresponding step lists are nonempty.

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
