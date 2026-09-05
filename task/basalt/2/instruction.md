Add step result memoization and cache administration to Basalt.

In `basalt.core.dag.ast`:
- Expose `MemoizationPolicySpec(BaseModel)`: `enabled: bool = False`, `key: str | None = None`, `ttl_seconds: float | None = Field(default=None, gt=0.0)`, `include_inputs: bool = True`.
- Add `memoization: MemoizationPolicySpec = Field(default_factory=MemoizationPolicySpec)` to `StepSpec`.

In `basalt.core.engine.hooks`: add `STEP_CACHE_HIT = "step_cache_hit"` to `LifecycleEvent`.

In `basalt.core.engine.memoization`, implement async `ResultCache`:
- `get(key)`: returns deep copy on hit; on miss/expiry returns `None`, purges entry, increments misses.
- `put(key, output, ttl_seconds=None)`: stores deep copy and optional expiry.
- `invalidate(key) -> bool`: deletes key, returns `True` if present else `False`.
- `clear() -> int`: purges entries, returns count removed.
- `keys() -> list[str]`: purges expired entries, returns active keys.
- `stats()`: purges expired entries, returns `{"entries": int, "hits": int, "misses": int}`.

In `basalt.core.engine.memoization_admin`:
- `CacheSummary`: dataclass (`entries: int`, `hits: int`, `misses: int`, `hit_rate: float`, `keys: tuple[str, ...]`); `as_dict()` returns dict of fields (`keys` as list).
- `CacheAdministration(cache: ResultCache)`: async `summary() -> CacheSummary` (keys as tuple; hit rate `hits/(hits+misses)` or `0.0`), `contains(key) -> bool`, `keys(prefix=None) -> list[str]` (sorted active keys, prefix-filtered if given), `invalidate_prefix(prefix) -> int`, and `invalidate_many(keys) -> int` (deduplicates keys; both return count removed).

In `WorkflowRunner`:
- `__init__` accepts optional `result_cache` (stored on `self.result_cache`, defaulting to a new `ResultCache()`).
- Cache key derives from namespace (`policy.key` or `f"{context.dag_id}:{step.id}"`), step definition (`step.model_dump(mode="json")` excluding `name`, `description`, `memoization`), upstream outputs (`{p: context.get_step_output(p) for p in sorted(step.depends_on)}`), and `context.inputs` (if `include_inputs`).
- When `step.memoization.enabled`: on hit, skip execution/STEP_START, set `context.set_step_state(step.id, StepState.COMPLETED)` and `context.set_step_output(step.id, cached)`, trigger `STEP_CACHE_HIT` (`{"step_id": step.id, "cache_key": key, "output": cached}`) then `STEP_SUCCESS` (`{"step_id": step.id, "output": cached, "cached": True}`). On miss: execute; on success cache with TTL and trigger `STEP_SUCCESS` (`{"step_id": step.id, "output": output, "cached": False}`). Never cache failures.

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
