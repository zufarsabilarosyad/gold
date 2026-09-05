Add workflow step result memoization and cache administration to Basalt.

In `basalt.core.dag.ast`:
- Expose `MemoizationPolicySpec(BaseModel)`: `enabled: bool = False`, `key: str | None = None`, `ttl_seconds: float | None = Field(default=None, gt=0.0)`, `include_inputs: bool = True`.
- Add `memoization = Field(default_factory=MemoizationPolicySpec)` to `StepSpec`.

In `basalt.core.engine.hooks`: add `STEP_CACHE_HIT = "step_cache_hit"` to `LifecycleEvent`.

In `basalt.core.engine.memoization`, implement async `ResultCache`:
- `get(key)`: returns deep copy, updates hits/misses, purges expired (returning `None` on miss/expiry).
- `put(key, output, ttl_seconds=None)`: stores deep copy and expiry.
- `invalidate(key) -> bool`: deletes key.
- `clear() -> int`: purges entries, returning count.
- `keys() -> list[str]`: purges expired, returns active keys.
- `stats()`: active `{"entries": int, "hits": int, "misses": int}`.

In `basalt.core.engine.memoization_admin`:
- `CacheSummary`: dataclass (`entries: int`, `hits: int`, `misses: int`, `hit_rate: float`, `keys: tuple[str, ...]`); `as_dict()` returns dict of these fields.
- `CacheAdministration(cache)`: async `summary() -> CacheSummary`, `contains(key) -> bool`, `invalidate_prefix(prefix) -> int`, `invalidate_many(keys) -> int` (deduplicates; both return removed count).
- `CacheHealth`: dataclass (`healthy: bool`, `hit_rate: float`, `minimum_hit_rate: float`, `observations: int`, `reason: str`); `as_dict()` returns dict of these fields.
- async `assess_cache_health(cache, minimum_hit_rate=0.0, minimum_observations=1) -> CacheHealth`: validates thresholds (0.0<=rate<=1.0, obs>=0, else `ValueError`); healthy if obs < minimum or hit_rate >= minimum, else unhealthy.

In `WorkflowRunner`:
- `__init__` accepts optional `result_cache: ResultCache | None = None`.
- Cache key derives from namespace (`policy.key` or `f"{context.dag_id}:{step.id}"`), step definition (excluding `name`, `description`, `memoization`), upstream outputs, and inputs (if `include_inputs`).
- When `step.memoization.enabled`: on hit, skip execution/STEP_START, set step `COMPLETED` with output in `context`, emit `STEP_CACHE_HIT` (`{"step_id": step.id, "cache_key": key, "output": cached}`) then `STEP_SUCCESS` (`{"step_id": step.id, "output": cached, "cached": True}`). On miss: execute; on success cache output with TTL and emit `STEP_SUCCESS` (`{"step_id": step.id, "output": output, "cached": False}`). Never cache failures.

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
