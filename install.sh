#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR="$HOME/Library/LaunchAgents"
CURRENT_DIR="$(pwd)"

BASE="jp.shipweb.obsidian-ai-hub"
HITL="jp.shipweb.obsidian-ai-hub.hitl-worker"

args=("${@:-$BASE}")

names=()
for arg in "${args[@]}"; do
  case "$arg" in
    "$BASE"|base)
      names+=("$BASE") ;;
    "$HITL"|hitl-worker|hitl)
      names+=("$HITL") ;;
    all)
      names+=("$BASE" "$HITL") ;;
    *)
      echo "Unknown service: $arg" >&2
      echo "Usage: $0 [base|hitl-worker|all]" >&2
      exit 1 ;;
  esac
done

mkdir -p "$DEST_DIR"

for name in "${names[@]}"; do
  source="$SCRIPT_DIR/$name.plist"
  dest="$DEST_DIR/$name.plist"

  python3 - "$source" "$dest" "$CURRENT_DIR" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
current_dir = sys.argv[3]

content = source.read_text(encoding="utf-8")
content = content.replace("{{PWD}}", current_dir)
destination.write_text(content, encoding="utf-8")
PY

  echo "Installed $dest"
done