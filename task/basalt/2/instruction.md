Add workflow step result memoization to Basalt.

In `basalt.core.dag.ast`:
- Expose `MemoizationPolicySpec(BaseModel)` with fields `enabled: bool = False`, `key: str | None = None`, `ttl_seconds: float | None = Field(default=None, gt=0.0)`, and `include_inputs: bool = True`.
- Add `memoization: MemoizationPolicySpec = Field(default_factory=MemoizationPolicySpec)` to `StepSpec`.

In `basalt.core.engine.hooks`:
- Add `STEP_CACHE_HIT = "step_cache_hit"` to `LifecycleEvent`.

In `basalt.core.engine.memoization`, implement concurrency-safe `ResultCache` with async methods:
- `get(key)`: on hit returns deep-copied dict and increments hits; on missing or expired key returns `None`, purges expired entry, and increments misses.
- `put(key, output, ttl_seconds=None)`: stores deep-copied dict and expiry (`time.monotonic() + ttl_seconds` if provided).
- `invalidate(key)`: deletes key, returns `True` if present else `False`.
- `clear()`: deletes all entries, returns int count removed.
- `keys()`: purges expired entries, returns `list[str]` of active keys.
- `stats()`: purges expired entries, returns `{"entries": int, "hits": int, "misses": int}`.

In `WorkflowRunner.__init__`, accept optional `result_cache: ResultCache | None = None` (stored on `self.result_cache`, defaulting to a new `ResultCache()`).
Derive the cache key string (e.g. SHA-256) from: namespace (`step.memoization.key or f"{context.dag_id}:{step.id}"`), step definition (`step.model_dump(mode="json")` excluding `"name"`, `"description"`, `"memoization"`), upstream outputs (`{p: context.get_step_output(p) for p in sorted(step.depends_on)}`), and `context.inputs` when `include_inputs` is True.

In `WorkflowRunner.run_async`, when `step.memoization.enabled`:
- On hit: skip execution and `STEP_START`, set `context.set_step_state(step.id, StepState.COMPLETED)` and `context.set_step_output(step.id, cached)`, trigger `STEP_CACHE_HIT` with `{"step_id": step.id, "cache_key": key, "output": cached}`, then `STEP_SUCCESS` with `{"step_id": step.id, "output": cached, "cached": True}`.
- On miss: execute step; on success cache output with TTL and trigger `STEP_SUCCESS` with `{"step_id": step.id, "output": output, "cached": False}`. Do not cache failures.

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
