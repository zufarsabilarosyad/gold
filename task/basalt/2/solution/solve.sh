#!/bin/bash
set -euo pipefail

cd /app

# The published environment may contain build-time working-tree residue. Put
# only this solution's targets back at their pinned preimage before applying
# the reference diff, so git apply cannot silently leave an empty artifact.
git checkout -q 69686949e6162606cc54293dc2af217d63161577 -- \
  src/basalt/core/dag/ast.py \
  src/basalt/core/engine/hooks.py \
  src/basalt/core/engine/runner.py
rm -f -- \
  src/basalt/core/engine/memoization.py \
  src/basalt/core/engine/memoization_admin.py \
  src/basalt/core/engine/memoization_keys.py \
  src/basalt/core/engine/memoization_serialization.py

# Apply the reference solution
git apply --whitespace=nowarn /solution/solution.patch

# Commit it like a normal submission (only committed work is graded).
git checkout -B feature/solution
git add src/basalt
git -c user.name="oracle" -c user.email="oracle@local" commit -q --no-verify -m "Apply reference solution"
