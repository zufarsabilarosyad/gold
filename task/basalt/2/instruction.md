Add step result memoization and cache administration to Basalt.

In `basalt.core.dag.ast`:
- Expose `MemoizationPolicySpec(BaseModel)`: `enabled: bool = False`, `key: str | None = None`, `ttl_seconds: float | None = Field(default=None, gt=0.0)`, `include_inputs: bool = True`.
- Add `memoization: MemoizationPolicySpec = Field(default_factory=MemoizationPolicySpec)` to `StepSpec`.

In `basalt.core.engine.hooks`: add `STEP_CACHE_HIT = "step_cache_hit"` to `LifecycleEvent`.

In `basalt.core.engine.memoization`, implement async `ResultCache`:
- `get(key)`: deep copy on hit, else `None`; updates hits/misses; purges expired.
- `put(key, output, ttl_seconds=None)`: stores deep copy and expiry.
- `invalidate(key) -> bool`: deletes key.
- `clear() -> int`: purges entries, returns count.
- `keys() -> list[str]`: purges expired, returns active keys.
- `stats()`: purges expired, returns `{"entries": int, "hits": int, "misses": int}`.

In `basalt.core.engine.memoization_admin`:
- `CacheSummary`: dataclass (`entries: int`, `hits: int`, `misses: int`, `hit_rate: float`, `keys: tuple[str, ...]`); `as_dict()` returns dict of fields (`keys` as list).
- `CacheAdministration(cache: ResultCache)`: async `summary() -> CacheSummary` (hit rate `hits/(hits+misses)` or `0.0`), `contains(key) -> bool`, `invalidate_prefix(prefix) -> int`, and `invalidate_many(keys) -> int` (deduplicates keys; both return count removed).
- `CacheNamespace(name: str)`: validates non-empty name (else `ValueError`); `key(name: str) -> str` returns `f"{self.name}:{name}"`; async `get(cache, name)`, `put(cache, name, output, ttl_seconds=None)`, `invalidate(cache, name) -> bool`, and `clear(cache) -> int` (invalidates prefix `f"{self.name}:"`, returns count).

In `WorkflowRunner`:
- Accepts optional `result_cache` in `__init__`.
- Cache key: namespace (`policy.key` or `f"{context.dag_id}:{step.id}"`), step definition (`step.model_dump(mode="json")` excluding `name`, `description`, `memoization`), upstream outputs (`{p: context.get_step_output(p) for p in sorted(step.depends_on)}`), inputs (if `include_inputs`).
- When `step.memoization.enabled`: on hit, skip execution/STEP_START, set step `COMPLETED` and output in `context`, trigger `STEP_CACHE_HIT` (`{"step_id": step.id, "cache_key": key, "output": cached}`) then `STEP_SUCCESS` (`{"step_id": step.id, "output": cached, "cached": True}`). On miss: execute; on success cache with TTL and trigger `STEP_SUCCESS` (`{"step_id": step.id, "output": output, "cached": False}`). Never cache failures.

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
