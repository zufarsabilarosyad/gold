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
# Anti-cheating & integrity:
# 1. Reset Cargo.toml to base version so custom [[test]] targets or harness=false cannot be injected
git checkout -f 043beee3891e151b882db84156b6882b5e3d4588 -- /app/Cargo.toml 2>/dev/null || true
rm -rf /app/build.rs /app/.cargo /app/Cargo.lock

# 2. Remove test.patch so candidate code running in tests cannot inspect hidden test contents
rm -f /tests/test.patch 2>/dev/null || true
chmod 444 /tests/config.json /app/tests/*.rs /app/Cargo.toml 2>/dev/null || true

for cargo_dir in "$HOME/.cargo/bin" /root/.cargo/bin /usr/local/cargo/bin /home/*/.cargo/bin; do
  if [ -f "$cargo_dir/cargo" ]; then
    export PATH="$cargo_dir:$PATH"
    break
  fi
done

set +e
python3 - << 'PYEOF' 2>&1 | tee -a "$RUN_LOG"
import os
import json
import subprocess
import sys
import xml.etree.ElementTree as ET

with open("/tests/config.json") as f:
    cfg = json.load(f)

suite_tests = {}
for node_id in cfg.get("p2p_node_ids", []) + cfg.get("f2p_node_ids", []):
    parts = node_id.split(".")
    suite_part = parts[0].replace("bigu::", "")
    test_name = parts[1]
    suite_tests.setdefault(suite_part, []).append(test_name)

env = dict(os.environ)
home = os.path.expanduser("~")
for cdir in ["/root/.cargo/bin", home + "/.cargo/bin", "/usr/local/cargo/bin"]:
    if os.path.exists(cdir + "/cargo"):
        env["PATH"] = cdir + ":" + env.get("PATH", "")
        break

def run_suite_authenticated(suites, xml_out):
    root = ET.Element("testsuites", name="cargo-test")
    for tname in suites:
        classname = "bigu::" + tname
        ts = ET.SubElement(root, "testsuite", name=classname)
        test_list = suite_tests.get(tname, [])

        # Pre-build test suite once so each individual test run is instant
        subprocess.run(["cargo", "test", "--no-run", "--test", tname], cwd="/app", capture_output=True, text=True, env=env)

        for t in test_list:
            cmd = ["cargo", "test", "--test", tname, "--", t, "--exact", "--nocapture"]
            print("+ " + " ".join(cmd), flush=True)
            proc = subprocess.run(cmd, cwd="/app", capture_output=True, text=True, env=env)
            out = proc.stdout + "\n" + proc.stderr
            print(out, flush=True)

            if proc.returncode == 0 and "test result: ok. 1 passed" in proc.stdout:
                ET.SubElement(ts, "testcase", classname=classname, name=t)
            else:
                tc = ET.SubElement(ts, "testcase", classname=classname, name=t)
                fail = ET.SubElement(tc, "failure", message="Test failed with returncode " + str(proc.returncode))
                fail.text = out

    os.makedirs(os.path.dirname(xml_out), exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(xml_out, encoding="utf-8", xml_declaration=True)

run_suite_authenticated(["arithmetic", "formatting", "modular", "primality", "rational"], "/logs/verifier/base.xml")
run_suite_authenticated(["polynomial", "poly_roots"], "/logs/verifier/new.xml")
PYEOF

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
