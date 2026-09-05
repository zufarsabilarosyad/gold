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
# Keep checkout-controlled startup files out of the test processes and final
# Python grader. The small launcher adds src only after Python startup.
unset PYTHONPATH
export PYTHONSAFEPATH=1
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

# Restore every baseline test from the pinned commit, then load its fixtures
# from a verifier-owned temporary directory with normal conftest discovery off.
# The held-out feature files were independently reset and applied by prepare.
BASE_COMMIT=69686949e6162606cc54293dc2af217d63161577
BASE_TEST_FILES=(
  tests/__init__.py tests/conftest.py tests/test_api_routes.py tests/test_cli_commands.py
  tests/test_context_evaluator.py tests/test_dag_parser.py tests/test_dag_sorter.py
  tests/test_engine.py tests/test_engine_integration.py tests/test_executors.py
  tests/test_resilience.py tests/test_state_machine.py tests/test_storage_repository.py
  tests/test_triggers.py tests/test_worker_pool.py
)
git checkout -q "$BASE_COMMIT" -- "${BASE_TEST_FILES[@]}" || exit 7
BASE_FIXTURE_DIR=$(mktemp -d /tmp/basalt-verifier-fixtures.XXXXXX) || exit 7
export BASE_FIXTURE_DIR
git show "$BASE_COMMIT:tests/conftest.py" > "$BASE_FIXTURE_DIR/basalt_base_fixtures.py" || exit 7

set +e
# Existing Basalt regression suite (pass-to-pass coverage). Retry the complete
# suite when the base repository's timing-sensitive interval test misses its
# short scheduling window; the final report always contains the complete run.
for _base_attempt in 1 2 3; do
  PYTEST_ADDOPTS="-p no:cacheprovider -p pytest_asyncio.plugin -p basalt_base_fixtures --noconftest -c /dev/null --rootdir=/app --asyncio-mode=auto --junitxml=/logs/verifier/base.xml" run_log python3 -P -c 'import os, sys, pytest, pytest_asyncio.plugin; sys.path[:0] = [os.environ["BASE_FIXTURE_DIR"], "/app/src"]; raise SystemExit(pytest.main())' -q \
    tests/test_api_routes.py tests/test_cli_commands.py tests/test_context_evaluator.py \
    tests/test_dag_parser.py tests/test_dag_sorter.py tests/test_engine.py \
    tests/test_engine_integration.py tests/test_executors.py tests/test_resilience.py \
    tests/test_state_machine.py tests/test_storage_repository.py tests/test_triggers.py \
    tests/test_worker_pool.py && break
  echo "[verifier] baseline attempt ${_base_attempt} failed; retrying complete suite" | tee -a "$RUN_LOG"
done
# New in-memory run-event timeline behavior (fail-to-pass coverage).
PYTEST_ADDOPTS="-p no:cacheprovider -p pytest_asyncio.plugin -p basalt_base_fixtures --noconftest -c /dev/null --rootdir=/app --asyncio-mode=auto --junitxml=/logs/verifier/new.xml" run_log python3 -P -c 'import os, sys, pytest, pytest_asyncio.plugin; sys.path[:0] = [os.environ["BASE_FIXTURE_DIR"], "/app/src"]; raise SystemExit(pytest.main())' -q \
  tests/test_run_event_timeline.py tests/test_run_event_queries.py
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
