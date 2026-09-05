Add step memoization and cache administration.

In `basalt.core.dag.ast`:
- `MemoizationPolicySpec(BaseModel)`: `enabled: bool = False`, `key: str | None = None`, `ttl_seconds: float | None = Field(default=None, gt=0.0)`, `include_inputs: bool = True`.
- `StepSpec`: `memoization: MemoizationPolicySpec = Field(default_factory=MemoizationPolicySpec)`.

In `basalt.core.engine.hooks`: add `LifecycleEvent.STEP_CACHE_HIT = "step_cache_hit"`.

In `basalt.core.engine.memoization`, async `ResultCache` (purges expired entries on access):
- `get(key)`: deep copy on hit; on miss/expiry returns `None`, purges entry, increments misses.
- `put(key, output, ttl_seconds=None)`: stores copy and expiry; raises `ValueError` if `ttl_seconds <= 0`.
- `invalidate(key) -> bool`: returns `True` if deleted else `False`.
- `clear() -> int` (purges all) and `purge_expired() -> int` (purges expired): return count removed.
- `keys() -> list[str]`: returns active keys.
- `stats()`: returns `{"entries": int, "hits": int, "misses": int}`.

In `basalt.core.engine.memoization_admin`:
- `CacheSummary`: dataclass (`entries: int`, `hits: int`, `misses: int`, `hit_rate: float`, `keys: tuple[str, ...]`); `as_dict()` returns dict of fields.
- `CacheAdministration(cache: ResultCache)` with async methods: `summary() -> CacheSummary` (hit rate `hits/(hits+misses)` or `0.0`), `contains(key) -> bool` (True if active else False), `keys(prefix=None) -> list[str]` (sorted active keys, prefix-filtered if given), `evict_expired() -> int`, `invalidate_prefix(prefix) -> int`, and `invalidate_many(keys) -> int` (deduplicates keys; each returns count removed).

In `WorkflowRunner`:
- `__init__` accepts optional `result_cache` (on `self.result_cache`, defaults to `ResultCache()`).
- Cache key: namespace (`policy.key` if set, else `f"{context.dag_id}:{step.id}"`), step definition (`step.model_dump(mode="json")` excluding `name`, `description`, `memoization`), upstream outputs (`{p: context.get_step_output(p) for p in sorted(step.depends_on)}`), and inputs (`context.inputs` if `include_inputs`).
- When `step.memoization.enabled`: on hit skip execution/STEP_START, set context output cached and state `COMPLETED`, trigger `STEP_CACHE_HIT` (`{"step_id": step.id, "cache_key": key, "output": cached}`) then `STEP_SUCCESS` (`{"step_id": step.id, "output": cached, "cached": True}`). On miss: execute; on success cache with TTL and trigger `STEP_SUCCESS` (`{"step_id": step.id, "output": output, "cached": False}`). Never cache failures.

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
