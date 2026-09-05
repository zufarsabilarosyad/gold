Basalt currently runs every workflow step from scratch, even when a deterministic step has already produced a result for the same inputs. Add an opt-in memoization layer so repeated work can be reused while existing workflows continue to behave exactly as they do today.

Define `MemoizationPolicySpec` in `basalt.core.dag.ast` and expose it through a new `memoization` field on `StepSpec`. The policy should default to disabled and provide `key: str | None = None`, `ttl_seconds: float | None = None`, and `include_inputs: bool = True`. Reject TTL values that are zero or negative.

The cache itself should be available as the asynchronous `ResultCache` in `basalt.core.engine.memoization`. Give it `get(key)`, `put(key, output, ttl_seconds=None)`, `invalidate(key)`, `clear()`, `keys()`, and `stats()` operations. A missing or expired lookup returns `None`; invalidation says whether anything was removed; clearing returns the number of removed entries; and statistics report integer `entries`, `hits`, and `misses`. Store and return deep copies so one caller cannot accidentally change a value seen by another.

Finally, allow `WorkflowRunner` to receive an optional `result_cache`, creating a fresh cache when none is supplied. An enabled step should reuse a successful result when its policy key and applicable workflow inputs match. Explicit keys must remain separate, `include_inputs: false` must allow reuse across different inputs, expired results must run again, and failures must never enter the cache. Cache hits should still appear as ordinary completed steps with their usual workflow outputs. Sharing one cache between runner instances must also work.

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
