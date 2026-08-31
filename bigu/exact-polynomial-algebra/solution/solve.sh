#!/bin/bash

cd "${APP_DIR:-/app}" || exit 0

# Apply the reference solution
if [ -f /solution/solution.patch ]; then
  git apply --whitespace=nowarn /solution/solution.patch
elif [ -f "$(dirname "$0")/solution.patch" ]; then
  git apply --whitespace=nowarn "$(dirname "$0")/solution.patch"
elif [ -f solution/solution.patch ]; then
  git apply --whitespace=nowarn solution/solution.patch
fi

# Commit it like a normal submission (only committed work is graded).
git checkout -b feature/solution 2>/dev/null || true
git add -A
git -c user.name="oracle" -c user.email="oracle@local" commit -q --no-verify -m "Apply reference solution" || true
