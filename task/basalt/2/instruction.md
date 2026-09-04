Add workflow step result memoization and cache administration to Basalt.

In `basalt.core.dag.ast`:
- Expose `MemoizationPolicySpec(BaseModel)` with fields `enabled: bool = False`, `key: str | None = None`, `ttl_seconds: float | None = Field(default=None, gt=0.0)`, `include_inputs: bool = True`.
- Add `memoization: MemoizationPolicySpec = Field(default_factory=MemoizationPolicySpec)` to `StepSpec`.

In `basalt.core.engine.hooks`:
- Add `STEP_CACHE_HIT = "step_cache_hit"` to `LifecycleEvent`.

In `basalt.core.engine.memoization`, implement async `ResultCache`:
- `get(key)`: returns deep copy, increments hits; on miss or expired key returns `None`, purges key, increments misses.
- `put(key, output, ttl_seconds=None)`: stores deep copy and optional expiry.
- `invalidate(key)`: deletes key, returns bool.
- `clear()`: purges entries, returns int removed count.
- `keys()`: purges expired entries, returns `list[str]` active keys.
- `stats()`: purges expired entries, returns `{"entries": int, "hits": int, "misses": int}`.

In `basalt.core.engine.memoization_admin`:
- `CacheSummary`: dataclass (`entries: int`, `hits: int`, `misses: int`, `hit_rate: float`, `keys: tuple[str, ...]`, `as_dict()`).
- `CacheAdministration(cache)`: async `summary() -> CacheSummary`, `contains(key) -> bool`, `invalidate_prefix(prefix) -> int`, `invalidate_many(keys) -> int` (deduplicating keys).
- `CacheHealth`: dataclass (`healthy: bool`, `hit_rate: float`, `minimum_hit_rate: float`, `observations: int`, `reason: str`, `as_dict()`).
- async `assess_cache_health(cache, minimum_hit_rate=0.0, minimum_observations=1) -> CacheHealth`: validates thresholds; healthy if observations < minimum or hit_rate >= minimum.

In `WorkflowRunner`:
- Accept optional `result_cache: ResultCache | None = None` in `__init__`.
- Cache key derives from namespace (`policy.key` or `f"{context.dag_id}:{step.id}"`), step definition (excluding `name`, `description`, `memoization`), upstream outputs, and inputs (when `include_inputs` is True).
- When `step.memoization.enabled`: on hit, skip execution and `STEP_START`, set step `COMPLETED` and output in `context`, trigger `STEP_CACHE_HIT` (`{"step_id": step.id, "cache_key": key, "output": cached}`) then `STEP_SUCCESS` (`{"step_id": step.id, "output": cached, "cached": True}`). On miss, execute; on success cache output with TTL and trigger `STEP_SUCCESS` (`{"step_id": step.id, "output": output, "cached": False}`). Never cache failures.

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
