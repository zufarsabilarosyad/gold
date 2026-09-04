Basalt should let deterministic workflow steps opt in to result memoization to reuse successful outputs without re-executing.

In `basalt.core.dag.ast`, expose `MemoizationPolicySpec(BaseModel)` with fields `enabled: bool = False`, `key: str | None = None`, `ttl_seconds: float | None = None` (must be positive > 0), and `include_inputs: bool = True`. Add `memoization: MemoizationPolicySpec = Field(default_factory=MemoizationPolicySpec)` to `StepSpec`. Add `STEP_CACHE_HIT = "step_cache_hit"` to `LifecycleEvent`.

In `basalt.core.engine.memoization`, implement async `ResultCache`:
- `get(key)`: on hit returns deep-copied output dict and increments hits counter; on missing or expired key returns `None` and increments misses counter.
- `put(key, output, ttl_seconds=None)`: stores deep-copied output dict and expiration.
- `invalidate(key)`: deletes entry, returning `True` if present else `False`.
- `clear()`: deletes all entries, returning integer removed count.
- `keys()`: returns `list[str]` of active (non-expired) keys.
- `stats()`: returns dict `{"entries": int, "hits": int, "misses": int}` for active entries.

Extend `WorkflowRunner.__init__` with optional `result_cache` (defaulting to a new `ResultCache()` instance). Cache identity derives from: namespace (`policy.key` or `f"{context.dag_id}:{step.id}"`), step definition (ignoring `name`, `description`, `memoization`), upstream outputs of declared `depends_on`, and `context.inputs` when `include_inputs` is true.

In `WorkflowRunner`, when `step.memoization.enabled`:
- On cache hit: skip execution and `STEP_START`, set step state `COMPLETED` and output in `context`, emit `STEP_CACHE_HIT` with payload `{"step_id": step.id, "cache_key": key, "output": cached}`, immediately followed by `STEP_SUCCESS` with `{"step_id": step.id, "output": cached, "cached": True}`.
- On miss: execute step; on success cache output with TTL and emit `STEP_SUCCESS` with `{"step_id": step.id, "output": output, "cached": False}`. Never cache failures.

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
