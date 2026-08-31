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

# 2. Securely stash verifier vault outside /tests and remove /tests files during execution
VAULT_DIR="/tmp/.verifier_vault_$(head -c 16 /dev/urandom 2>/dev/null | xxd -p 2>/dev/null || echo 'vault_sec')"
mkdir -p "$VAULT_DIR"
cp -rf /tests/* "$VAULT_DIR/" 2>/dev/null || true
rm -rf /tests/*

for cargo_dir in "$HOME/.cargo/bin" /root/.cargo/bin /usr/local/cargo/bin /home/*/.cargo/bin; do
  if [ -f "$cargo_dir/cargo" ]; then
    export PATH="$cargo_dir:$PATH"
    break
  fi
done

set +e
python3 - << 'PYEOF' 2>&1 | tee -a "$RUN_LOG"
import os
import glob
import subprocess
import sys
import xml.etree.ElementTree as ET

env = dict(os.environ)
home = os.path.expanduser("~")
for cdir in ["/root/.cargo/bin", home + "/.cargo/bin", "/usr/local/cargo/bin"]:
    if os.path.exists(cdir + "/cargo"):
        env["PATH"] = cdir + ":" + env.get("PATH", "")
        break

def run_suite_binary(tests, xml_out):
    root = ET.Element("testsuites", name="cargo-test")
    for tname in tests:
        classname = "bigu::" + tname
        ts = ET.SubElement(root, "testsuite", name=classname)
        build_cmd = ["cargo", "test", "--no-run", "--test", tname]
        print("+ " + " ".join(build_cmd), flush=True)
        build_proc = subprocess.run(build_cmd, cwd="/app", capture_output=True, text=True, env=env)
        if build_proc.returncode != 0:
            tc = ET.SubElement(ts, "testcase", classname=classname, name="compilation")
            fail = ET.SubElement(tc, "failure", message="Compilation failed")
            fail.text = build_proc.stdout + "\n" + build_proc.stderr
            continue

        binaries = [f for f in glob.glob("/app/target/debug/deps/" + tname + "-*") if not f.endswith(".d") and os.access(f, os.X_OK)]
        if not binaries:
            tc = ET.SubElement(ts, "testcase", classname=classname, name="binary_discovery")
            fail = ET.SubElement(tc, "failure", message="No compiled test binary found")
            continue

        # Sort by modification time to get the latest built test binary
        binaries.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        bin_path = binaries[0]

        list_proc = subprocess.run([bin_path, "--list", "--format=terse"], capture_output=True, text=True)
        test_names = [line.split(": ")[0].strip() for line in list_proc.stdout.splitlines() if ": test" in line]

        for t in test_names:
            tc = ET.SubElement(ts, "testcase", classname=classname, name=t)
            res = subprocess.run([bin_path, t, "--exact", "--nocapture"], capture_output=True, text=True)
            if res.returncode != 0:
                fail = ET.SubElement(tc, "failure", message="Test failed with return code " + str(res.returncode))
                fail.text = res.stdout + "\n" + res.stderr

    os.makedirs(os.path.dirname(xml_out), exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(xml_out, encoding="utf-8", xml_declaration=True)

run_suite_binary(["arithmetic", "formatting", "modular", "primality", "rational"], "/logs/verifier/base.xml")
run_suite_binary(["polynomial", "poly_roots"], "/logs/verifier/new.xml")
PYEOF

# Restore verifier files exclusively for grader.py
cp -rf "$VAULT_DIR"/* /tests/ 2>/dev/null || true
rm -rf "$VAULT_DIR" 2>/dev/null || true
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
