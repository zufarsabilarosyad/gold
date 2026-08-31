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

# 2. Setup unprivileged runner user 'tester'
if [ "$(id -u)" -eq 0 ]; then
  id -u tester >/dev/null 2>&1 || useradd -m -s /bin/bash tester 2>/dev/null || true
  for dir in /root "$HOME" /home/* /usr/local; do
    [ -d "$dir" ] && chmod 755 "$dir" 2>/dev/null || true
  done
  for cdir in "$HOME/.cargo" /root/.cargo /usr/local/cargo; do
    [ -d "$cdir" ] && chmod -R 755 "$cdir" 2>/dev/null || true
  done
  for rdir in "$HOME/.rustup" /root/.rustup /usr/local/rustup; do
    [ -d "$rdir" ] && chmod -R 755 "$rdir" 2>/dev/null || true
  done
  mkdir -p /tmp/target /tmp/.cargo_cache
  chmod -R 777 /tmp/target /tmp/.cargo_cache
fi

# 3. Strictly protect /tests, /app/tests, and /app/Cargo.toml against unprivileged modification
cp /tests/config.json /tmp/.config_backup.json 2>/dev/null || true
chown -R root:root /tests /app/tests /app/Cargo.toml 2>/dev/null || true
chmod 700 /tests 2>/dev/null || true
chmod 400 /tests/config.json /tests/test.patch 2>/dev/null || true
chmod 555 /app/tests /tests/test.sh /tests/grader.py 2>/dev/null || true
chmod 444 /app/tests/*.rs /app/Cargo.toml 2>/dev/null || true

for cargo_dir in "$HOME/.cargo/bin" /root/.cargo/bin /usr/local/cargo/bin /home/*/.cargo/bin; do
  if [ -f "$cargo_dir/cargo" ]; then
    export PATH="$cargo_dir:$PATH"
    break
  fi
done

for rdir in "$HOME/.rustup" /root/.rustup /usr/local/rustup; do
  if [ -d "$rdir" ]; then
    export RUSTUP_HOME="$rdir"
    break
  fi
done

set +e
python3 - << 'PYEOF' 2>&1 | tee -a "$RUN_LOG"
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

def run_suite(tests, xml_out):
    root = ET.Element("testsuites", name="cargo-test")
    env = dict(os.environ)
    home = os.path.expanduser("~")
    for cdir in ["/root/.cargo/bin", f"{home}/.cargo/bin", "/usr/local/cargo/bin"]:
        if os.path.exists(f"{cdir}/cargo"):
            env["PATH"] = f"{cdir}:{env.get('PATH', '')}"
            break

    for tname in tests:
        classname = f"bigu::{tname}"
        ts = ET.SubElement(root, "testsuite", name=classname)
        if os.getuid() == 0:
            cmd = [
                "runuser", "-u", "tester", "--",
                "env",
                f"PATH={env.get('PATH', '')}",
                f"RUSTUP_HOME={env.get('RUSTUP_HOME', '')}",
                "CARGO_TARGET_DIR=/tmp/target",
                "CARGO_HOME=/tmp/.cargo_cache",
                "cargo", "test", "--test", tname, "--", "--nocapture"
            ]
        else:
            cmd = ["cargo", "test", "--test", tname, "--", "--nocapture"]

        print(f"+ {' '.join(cmd)}", flush=True)
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        out = proc.stdout + "\n" + proc.stderr
        print(out, flush=True)

        if proc.returncode != 0 or "test result: ok." not in proc.stdout:
            tc = ET.SubElement(ts, "testcase", classname=classname, name="compilation_or_execution")
            fail = ET.SubElement(tc, "failure", message=f"{tname} failed with return code {proc.returncode}")
            fail.text = out
            continue

        m_start = re.search(r"^running (\d+) tests?", proc.stdout, re.M)
        m_end = re.search(r"^test result: ok\. (\d+) passed;", proc.stdout, re.M)
        if not m_start or not m_end or int(m_start.group(1)) != int(m_end.group(1)):
            tc = ET.SubElement(ts, "testcase", classname=classname, name="libtest_authentication_failure")
            fail = ET.SubElement(tc, "failure", message=f"{tname} failed libtest count verification")
            fail.text = out
            continue

        in_libtest_block = False
        parsed_any = False
        for line in proc.stdout.splitlines():
            line_str = line.strip()
            if line_str.startswith("running ") and " tests" in line_str:
                in_libtest_block = True
                continue
            if line_str.startswith("test result:"):
                in_libtest_block = False
                continue
            if in_libtest_block and line_str.startswith("test ") and line_str.endswith(" ... ok"):
                parts = line_str.split()
                if len(parts) >= 4 and parts[0] == "test" and parts[-2] == "...":
                    name = parts[1]
                    parsed_any = True
                    ET.SubElement(ts, "testcase", classname=classname, name=name)
            elif in_libtest_block and line_str.startswith("test ") and line_str.endswith(" ... ignored"):
                parts = line_str.split()
                if len(parts) >= 4 and parts[0] == "test" and parts[-2] == "...":
                    name = parts[1]
                    parsed_any = True
                    tc = ET.SubElement(ts, "testcase", classname=classname, name=name)
                    ET.SubElement(tc, "skipped")

        if not parsed_any:
            tc = ET.SubElement(ts, "testcase", classname=classname, name="no_tests_executed")
            fail = ET.SubElement(tc, "failure", message=f"{tname} produced no valid libtest results")
            fail.text = out

    os.makedirs(os.path.dirname(xml_out), exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(xml_out, encoding="utf-8", xml_declaration=True)

run_suite(["arithmetic", "formatting", "modular", "primality", "rational"], "/logs/verifier/base.xml")
run_suite(["polynomial", "poly_roots"], "/logs/verifier/new.xml")
PYEOF

# Restore verifier permissions for grader.py
chmod 755 /tests /tests/grader.py 2>/dev/null || true
chmod 644 /tests/config.json /tests/test.patch 2>/dev/null || true
if [ -f /tmp/.config_backup.json ]; then
  cp -f /tmp/.config_backup.json /tests/config.json 2>/dev/null || true
fi
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
