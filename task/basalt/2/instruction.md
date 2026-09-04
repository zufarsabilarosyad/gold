Add workflow step result memoization and cache administration to Basalt.

In `basalt.core.dag.ast`:
- Expose `MemoizationPolicySpec(BaseModel)` with fields `enabled: bool = False`, `key: str | None = None`, `ttl_seconds: float | None = Field(default=None, gt=0.0)`, and `include_inputs: bool = True`.
- Add `memoization: MemoizationPolicySpec = Field(default_factory=MemoizationPolicySpec)` to `StepSpec`.

In `basalt.core.engine.hooks`:
- Add `STEP_CACHE_HIT = "step_cache_hit"` to `LifecycleEvent`.

In `basalt.core.engine.memoization`, implement async `ResultCache`:
- `get(key)`: returns deep-copied dict and increments hits; on missing or expired key returns `None`, purges entry, and increments misses.
- `put(key, output, ttl_seconds=None)`: stores deep-copied dict and optional expiry.
- `invalidate(key)`: deletes key, returns `True` if present else `False`.
- `clear()`: deletes all entries, returns int count removed.
- `keys()`: purges expired entries, returns `list[str]` of active keys.
- `stats()`: purges expired entries, returns `{"entries": int, "hits": int, "misses": int}`.

In `basalt.core.engine.memoization_admin`:
- `CacheSummary`: dataclass with `entries: int`, `hits: int`, `misses: int`, `hit_rate: float` (`hits / (hits + misses)` or `0.0`), `keys: tuple[str, ...]`, and `as_dict()`.
- `CacheAdministration(cache: ResultCache)`: async `summary() -> CacheSummary`, `contains(key) -> bool`, `invalidate_prefix(prefix) -> int`, and `invalidate_many(keys) -> int` (deduplicating keys).

In `WorkflowRunner`:
- `__init__` accepts optional `result_cache: ResultCache | None = None`.
- Cache key derives from namespace (`policy.key` or `f"{context.dag_id}:{step.id}"`), step definition (`step.model_dump(mode="json")` excluding `name`, `description`, `memoization`), upstream outputs (`{p: context.get_step_output(p) for p in sorted(step.depends_on)}`), and `context.inputs` when `include_inputs` is True.
- When `step.memoization.enabled`: on hit, skip execution and `STEP_START`, set step state `COMPLETED` and output in `context`, trigger `STEP_CACHE_HIT` (`{"step_id": step.id, "cache_key": key, "output": cached}`) then `STEP_SUCCESS` (`{"step_id": step.id, "output": cached, "cached": True}`). On miss, execute; on success cache output with TTL and trigger `STEP_SUCCESS` (`{"step_id": step.id, "output": output, "cached": False}`). Never cache failures.

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
