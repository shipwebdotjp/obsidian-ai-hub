#!/usr/bin/env bash
# Stop the opcheck sandbox started by opcheck_start.sh.
#
# The PID file is verified against the live command line before signalling,
# so a recycled PID is never killed. Waits for the port to close, then
# removes the PID file.
#
# Usage: bash ./scripts/opcheck_stop.sh
set -euo pipefail

cd "$(dirname "$0")/.."

SANDBOX_DIR="${OAIHUB_OPCHECK_DIR:-.opcheck}"
PORT="${OAIHUB_OPCHECK_PORT:-8767}"
PID_FILE="$SANDBOX_DIR/server.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "[opcheck] no pid file ($PID_FILE); nothing to stop" >&2
  exit 1
fi

PID="$(cat "$PID_FILE")"
if [[ -z "$PID" ]] || ! kill -0 "$PID" 2>/dev/null; then
  echo "[opcheck] pid ${PID:-<empty>} is not running; removing stale pid file"
  rm -f "$PID_FILE"
  exit 1
fi

# Refuse to signal a process that is no longer the sandbox server
# (protects against PID reuse after an unclean shutdown). Note: opcheck_serve.sh
# ends in `exec uv run ...`, so the recorded PID's command line is the `uv run`
# invocation, not opcheck_serve itself.
if ! ps -p "$PID" -o command= | grep -q -- "--serve-port $PORT"; then
  echo "[opcheck] pid $PID is not the sandbox server on port $PORT; leaving it alone" >&2
  echo "[opcheck] inspect manually, then remove $PID_FILE" >&2
  exit 1
fi

kill "$PID"
for _ in $(seq 1 6); do
  if ! kill -0 "$PID" 2>/dev/null; then
    break
  fi
  sleep 5
done

if kill -0 "$PID" 2>/dev/null; then
  echo "[opcheck] pid $PID did not exit; escalating to kill -KILL" >&2
  kill -KILL "$PID" || true
  sleep 2
fi

rm -f "$PID_FILE"
if curl -sf --max-time 3 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  echo "[opcheck] warning: something still answers on port $PORT" >&2
  exit 1
fi
echo "[opcheck] stopped (pid $PID)"
