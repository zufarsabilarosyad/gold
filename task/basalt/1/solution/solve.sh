#!/bin/bash
set -e

cd "${APP_DIR:-/app}"

git config --global --add safe.directory /app 2>/dev/null || true
git config --global --add safe.directory "*" 2>/dev/null || true

# Find and apply the reference solution patch
PATCH_FILE=""
if [ -f /solution/solution.patch ]; then
  PATCH_FILE="/solution/solution.patch"
elif [ -f "$(dirname "$0")/solution.patch" ]; then
  PATCH_FILE="$(dirname "$0")/solution.patch"
elif [ -f solution/solution.patch ]; then
  PATCH_FILE="solution/solution.patch"
fi

if [ -n "$PATCH_FILE" ]; then
  git apply --whitespace=nowarn "$PATCH_FILE"
fi

# Commit it like a normal submission (only committed work is graded).
git checkout -b feature/solution 2>/dev/null || true
git add -A
git -c user.name="oracle" -c user.email="oracle@local" commit -q --no-verify -m "Apply reference solution" || true

