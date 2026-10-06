#!/usr/bin/env bash
# Start the opcheck sandbox in the background for agent-driven checks.
#
# Unlike `make opcheck-serve` (foreground, for human terminals), this script
# backgrounds the server, records its PID in .opcheck/server.pid, and waits
# for readiness via opcheck_wait_ready.sh. Stop with opcheck_stop.sh.
#
# The token comes from OAIHUB_OPCHECK_TOKEN when set; otherwise
# opcheck_serve.sh generates one and this script reports it from
# .opcheck/env.sh.
#
# Usage: [OAIHUB_OPCHECK_TOKEN=...] bash ./scripts/opcheck_start.sh
set -euo pipefail

# The generated env.sh and server.pid contain a live API token / PID;
# keep sandbox files private.
umask 077

cd "$(dirname "$0")/.."

SANDBOX_DIR="${OAIHUB_OPCHECK_DIR:-.opcheck}"
PORT="${OAIHUB_OPCHECK_PORT:-8767}"
PID_FILE="$SANDBOX_DIR/server.pid"

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE")"
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "[opcheck] already running (pid $OLD_PID). Stop it first: bash ./scripts/opcheck_stop.sh" >&2
    exit 1
  fi
  rm -f "$PID_FILE"
fi

nohup bash ./scripts/opcheck_serve.sh > /tmp/opcheck_serve.log 2>&1 &
SERVER_PID=$!
printf '%s\n' "$SERVER_PID" > "$PID_FILE"
chmod 600 "$PID_FILE"
echo "[opcheck] started pid $SERVER_PID (log: /tmp/opcheck_serve.log)"

if ! bash ./scripts/opcheck_wait_ready.sh "$PORT"; then
  echo "[opcheck] server did not become ready; see /tmp/opcheck_serve.log" >&2
  bash ./scripts/opcheck_stop.sh || true
  exit 1
fi

# opcheck_serve.sh writes the effective token (generated when
# OAIHUB_OPCHECK_TOKEN is unset) to .opcheck/env.sh.
# shellcheck disable=SC1091
source .opcheck/env.sh
cat <<EOF
[opcheck] sandbox : $SANDBOX_DIR
[opcheck] url     : http://127.0.0.1:$PORT
[opcheck] token   : $OBSIDIAN_AI_HUB_API_TOKEN
EOF
