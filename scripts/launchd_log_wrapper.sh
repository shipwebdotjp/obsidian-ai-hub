#!/usr/bin/env bash
# launchd_log_wrapper.sh — rotates stdout/stderr for a short-lived launchd job
# (e.g. a periodic task_runner that starts every N seconds and exits).
#
# Usage: launchd_log_wrapper.sh <label> <command...>
#
# The wrapped command's stdout is appended to ${LOG_DIR}/${LABEL}.log and its
# stderr to ${LOG_DIR}/${LABEL}.err. Before starting the command, each current
# log file is checked against MAX_SIZE (default 1 MiB); if it is at or above
# the limit, the file is rotated keeping GENERATIONS (default 7) generations.
# This is a startup-time rotation: it is correct for short/periodic jobs. A
# long-running KeepAlive job would need interval-based rotation instead.
#
# launchd itself should be pointed at /dev/null for StandardOutPath /
# StandardErrorPath since this wrapper owns the log destinations.
set -euo pipefail

LABEL="${1:?usage: launchd_log_wrapper.sh <label> <command...>}"
shift
# Sanitize the label so it can only be a safe filename component.
LABEL="${LABEL//[^A-Za-z0-9._-]/_}"

LOG_DIR="${LOG_DIR:-/tmp}"
mkdir -p "$LOG_DIR"
MAX_SIZE=$((1024 * 1024)) # 1 MiB
GENERATIONS=7

rotate_if_needed() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  local size
  # If the size cannot be determined, default to rotating so a log can never
  # grow unboundedly because of a silent stat failure.
  size=$(/usr/bin/stat -f%z "$file" 2>/dev/null || echo "$MAX_SIZE")
  if ((size < MAX_SIZE)); then
    return 0
  fi

  # Drop the oldest generation, shift the rest up, move current to .1
  rm -f "${file}.${GENERATIONS}"
  local i
  for ((i = GENERATIONS - 1; i >= 1; i--)); do
    [[ -f "${file}.${i}" ]] && mv "${file}.${i}" "${file}.$((i + 1))"
  done
  mv "$file" "${file}.1"
}

rotate_if_needed "${LOG_DIR}/${LABEL}.log"
rotate_if_needed "${LOG_DIR}/${LABEL}.err"

# Replace the shell with the wrapped command, appending output to the logs.
exec "$@" >>"${LOG_DIR}/${LABEL}.log" 2>>"${LOG_DIR}/${LABEL}.err"