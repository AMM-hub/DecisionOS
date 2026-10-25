#!/usr/bin/env bash
# DecisionOS — local launcher (Git Bash / MSYS on Windows)
# Starts the analytics API (:8100) and the Nuxt console (:3000), verifies both,
# then waits. Ctrl+C shuts BOTH down cleanly.
#
#   bash run-local.sh
#
# Optional overrides:
#   API_PORT=8100 WEB_PORT=3000 DECISIONOS_DATA_DIR=./var/worker bash run-local.sh

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$ROOT/services/analytics"
WEB_DIR="$ROOT/apps/web"
PY="$API_DIR/.venv/Scripts/python.exe"

API_PORT="${API_PORT:-8100}"
WEB_PORT="${WEB_PORT:-3000}"
export DECISIONOS_DATA_DIR="${DECISIONOS_DATA_DIR:-./var/worker}"

# Tooling can leak a PYTHONPATH pointing at a foreign venv (Hermes does on this
# box). That breaks the project venv with a pydantic_core import error. Scrub it.
unset PYTHONPATH PYTHONHOME

API_PID=""
WEB_PID=""
KILLED=0

kill_tree() {
  local pid="$1"
  [ -z "$pid" ] && return
  MSYS_NO_PATHCONV=1 taskkill /F /T /PID "$pid" >/dev/null 2>&1 || kill -9 "$pid" >/dev/null 2>&1
}

cleanup() {
  [ "$KILLED" = "1" ] && return
  KILLED=1
  echo ""
  echo "Shutting down DecisionOS..."
  kill_tree "$WEB_PID"
  kill_tree "$API_PID"
  echo "Stopped."
}
trap cleanup INT TERM EXIT

[ -x "$PY" ] || { echo "ERROR: Python venv missing at $PY"; exit 1; }
[ -d "$WEB_DIR/node_modules" ] || { echo "ERROR: run 'npm install' in apps/web first"; exit 1; }

# probe URL [tenant-header] -> exit 0 when the URL answers, non-zero otherwise.
# Uses Python instead of curl: MSYS curl is unreliable inside background scripts.
probe() {
  "$PY" - "$1" "${2:-}" <<'PYEOF' >/dev/null 2>&1
import sys, urllib.request
url, tenant = sys.argv[1], sys.argv[2]
h = {"X-Tenant": tenant, "X-User": "alpha.manager"} if tenant else {}
try:
    urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=5).read()
except Exception:
    sys.exit(1)
PYEOF
}

wait_for() { # url tenant label seconds
  local url="$1" tenant="${2:-}" label="$3" tries="${4:-60}"
  printf "  waiting for %s " "$label"
  for _ in $(seq 1 "$tries"); do
    if probe "$url" "$tenant"; then echo "- UP"; return 0; fi
    printf "."
    sleep 1
  done
  echo " - TIMED OUT"
  return 1
}

echo "DecisionOS starting..."
echo "  API dir : $API_DIR"
echo "  data dir: $DECISIONOS_DATA_DIR"

cd "$API_DIR" || exit 1
"$PY" -m uvicorn decisionos_analytics.serve:app --host 127.0.0.1 --port "$API_PORT" &
API_PID=$!

wait_for "http://127.0.0.1:$API_PORT/v1/pilots" "tenant_alpha" "API :$API_PORT" 90 || {
  echo "ERROR: analytics API failed to start (see output above)"; exit 1; }

# First run: seed the demo through the public HTTP contract (never direct DB
# writes). Safe to re-run — seed_demo.py only creates what is missing.
if [ "${SEED:-1}" != "0" ]; then
  dataset_count=$("$PY" - "$API_PORT" <<'PYEOF'
import json, sys, urllib.request
port = sys.argv[1]
req = urllib.request.Request(
    f"http://127.0.0.1:{port}/v1/datasets?limit=1",
    headers={"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"},
)
try:
    print(len(json.loads(urllib.request.urlopen(req, timeout=10).read())))
except Exception:
    print("?")
PYEOF
)
  if [ "$dataset_count" = "0" ]; then
    echo "  no datasets yet - seeding the demo..."
    seed_log="$ROOT/.agents/seed.log"
    mkdir -p "$ROOT/.agents"
    # Native Windows python.exe cannot read MSYS paths (/c/Users/...).
    seed_script="$(cygpath -w "$ROOT/scripts/seed_demo.py" 2>/dev/null || printf '%s' "$ROOT/scripts/seed_demo.py")"
    if "$PY" "$seed_script" --base-url "http://127.0.0.1:$API_PORT/v1" >"$seed_log" 2>&1; then
      sed 's/^/    /' "$seed_log"
      echo "  demo seeded"
    else
      sed 's/^/    /' "$seed_log"
      echo "  WARNING: demo seed failed; the console will show empty states."
    fi
  else
    echo "  datasets present: $dataset_count (skipping seed; SEED=0 to force skip)"
  fi
fi

echo "  starting web console..."
cd "$WEB_DIR" || exit 1
NUXT_PUBLIC_API_BASE="http://127.0.0.1:$API_PORT/v1" \
  npm run dev -- --port "$WEB_PORT" --host 127.0.0.1 &
WEB_PID=$!

wait_for "http://127.0.0.1:$WEB_PORT/" "" "web :$WEB_PORT" 180 || {
  echo "ERROR: Nuxt dev server failed to start (see output above)"; exit 1; }

echo ""
echo "=============================================="
echo "  DecisionOS is running"
echo "    Console : http://localhost:$WEB_PORT"
echo "    API     : http://localhost:$API_PORT/v1"
echo "    API docs: http://localhost:$API_PORT/docs"
echo "  Press Ctrl+C to stop both."
echo "=============================================="

wait
