#!/bin/bash
# Verifier entrypoint (canonical frame). Patching and grading live in
# tests/grader.py; this script owns the task-specific part: run the suites,
# write machine-readable reports under /logs/verifier/, and apply any report
# fixups before grading. Edit ONLY between the RUN TESTS markers.
set -uo pipefail
trap 'if [ ! -f /logs/verifier/reward.json ] && [ ! -f /logs/verifier/reward.txt ]; then mkdir -p /logs/verifier; echo -1 > /logs/verifier/reward.txt; fi' EXIT
log() { echo "[verifier] $*"; }
cd /app || { mkdir -p /logs/verifier; exit 6; }

python3 /tests/grader.py prepare || exit $?
[ -f /logs/verifier/reward.json ] && exit 0   # model.patch didn't apply -> graded 0

# Canonical raw-output log: send every suite's combined stdout+stderr here
# (use run_log, or pipe through tee -a "$RUN_LOG" when feeding a reporter) so
# the reason a test failed is never lost. Never silence a test run.
export RUN_LOG=/logs/verifier/run.log
: > "$RUN_LOG" 2>/dev/null || true
run_log() { echo "+ $*" >> "$RUN_LOG" 2>/dev/null; "$@" 2>&1 | tee -a "$RUN_LOG"; return "${PIPESTATUS[0]}"; }

# >>> RUN TESTS (task-specific) <<<
_bad_path=""
while IFS= read -r _model_path; do
  case "$_model_path" in src/basalt/*) ;; *) _bad_path="$_model_path"; break ;; esac
done < <(python3 /tests/grader.py patch-paths /logs/artifacts/model.patch)
if [ -n "$_bad_path" ]; then
  log "ERROR: submission touches out-of-scope path: $_bad_path"
  : > /logs/verifier/base.xml
  : > /logs/verifier/new.xml
  python3 /tests/grader.py grade
  exit 0
fi

if [ -d "/app/.venv/bin" ]; then
  export PATH="/app/.venv/bin:$PATH"
fi
export PYTHONPATH="/app/src:${PYTHONPATH:-}"

git checkout -q 69686949e6162606cc54293dc2af217d63161577 -- tests/conftest.py 2>/dev/null || true

set +e
PYTEST_ADDOPTS="-p no:cacheprovider --confcutdir=/app/tests -c /dev/null --asyncio-mode=auto --junitxml=/logs/verifier/base.xml" run_log python3 -m pytest -q \
  tests/test_engine.py tests/test_dag_sorter.py tests/test_executors.py \
  tests/test_resilience.py tests/test_state_machine.py
PYTEST_ADDOPTS="-p no:cacheprovider --confcutdir=/app/tests -c /dev/null --asyncio-mode=auto --junitxml=/logs/verifier/new.xml" run_log python3 -m pytest -q \
  tests/test_result_memoization.py tests/test_result_memoization_contract_notes.py
set -e
# >>> END RUN TESTS <<<

# Surface raw suite output into stdout (the harness captures it) so failures
# stay debuggable even when a framework report omits the reason.
_seen=""
for _rl in "$RUN_LOG" /logs/verifier/*_run.log /logs/verifier/*-run.log /logs/verifier/*.log /logs/verifier/*.out; do
  [ -f "$_rl" ] && [ -s "$_rl" ] || continue
  case " $_seen " in *" $_rl "*) continue ;; esac
  case "${_rl##*/}" in *convert*.log|ctrf*.log|junit*.log) continue ;; esac
  _seen="$_seen $_rl"
  echo "===== raw suite output: ${_rl##*/} ====="
  cat "$_rl"
done 2>/dev/null
echo "===== grade ====="

python3 /tests/grader.py grade
log "reward.json=$(cat /logs/verifier/reward.json 2>/dev/null)"

# Uniform top level: keep only the canonical artifacts in /logs/verifier and
# move every framework-native report/log under reports/.
mkdir -p /logs/verifier/reports 2>/dev/null
for _f in /logs/verifier/*; do
  case "${_f##*/}" in
    reward.json|reward.txt|ctrf.json|run.log|test-stdout.txt|reports) continue ;;
  esac
  [ -f "$_f" ] && mv -f "$_f" /logs/verifier/reports/ 2>/dev/null
done
