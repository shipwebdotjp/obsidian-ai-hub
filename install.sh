#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_PLIST="$SCRIPT_DIR/jp.shipweb.obsidian-ai-hub.plist"
DEST_DIR="$HOME/Library/LaunchAgents"
DEST_PLIST="$DEST_DIR/jp.shipweb.obsidian-ai-hub.plist"
CURRENT_DIR="$(pwd)"

mkdir -p "$DEST_DIR"

python3 - "$SOURCE_PLIST" "$DEST_PLIST" "$CURRENT_DIR" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
current_dir = sys.argv[3]

content = source.read_text(encoding="utf-8")
content = content.replace("{{PWD}}", current_dir)
destination.write_text(content, encoding="utf-8")
PY

echo "Installed $DEST_PLIST"
