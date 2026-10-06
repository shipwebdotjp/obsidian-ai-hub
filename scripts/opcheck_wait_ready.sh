#!/usr/bin/env bash
# Wait until the opcheck sandbox (or any local instance) answers /health.
#
# /health is unauthenticated and is served only after the lifespan startup
# (model loading, workers) completes, so a 200 here means the server is
# actually ready -- unlike a bare TCP connect. Do not use fixed `sleep` or
# /dev/tcp (unsupported by zsh) for readiness.
#
# Usage: opcheck_wait_ready.sh [port] [timeout_seconds]
set -euo pipefail

PORT="${1:-${OAIHUB_OPCHECK_PORT:-8767}}"
TIMEOUT="${2:-300}"
DEADLINE=$((SECONDS + TIMEOUT))

while ((SECONDS < DEADLINE)); do
  if curl -sf --max-time 5 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "[opcheck] ready: http://127.0.0.1:${PORT} (after ${SECONDS}s)"
    exit 0
  fi
  sleep 5
done

echo "[opcheck] timed out waiting for http://127.0.0.1:${PORT}/health after ${TIMEOUT}s" >&2
exit 1
