#!/usr/bin/env bash
# Isolated operational-check server.
#
# Runs a second obsidian-ai-hub instance against a sandbox DB / Vault / index
# on 127.0.0.1:${OAIHUB_OPCHECK_PORT:-8767} with background workers enabled.
# Real LLM credentials are read from .env (load_dotenv does not override the
# variables exported here). The sandbox redirects the writable application
# paths (DB, Vault, index, logs, healthcare, scheduler jobs state, model
# cache); repository configuration under config/ and plugins/ stays read-only.
#
# Follow-up CLI processes read config directly (no HTTP hop), so source the
# generated env file before running them:
#   source .opcheck/env.sh
#   uv run -m obsidian_ai_hub --workflow-run wrev_xxx --workflow-execute
#
# Never point this at the production memory.sqlite3.
set -euo pipefail

# The generated env.sh contains a live API token; keep sandbox files private.
umask 077

cd "$(dirname "$0")/.."

SANDBOX_DIR="${OAIHUB_OPCHECK_DIR:-.opcheck}"
PORT="${OAIHUB_OPCHECK_PORT:-8767}"
TOKEN="${OAIHUB_OPCHECK_TOKEN:-$(openssl rand -hex 16)}"

mkdir -p "$SANDBOX_DIR"
SANDBOX_ABS="$(cd "$SANDBOX_DIR" && pwd -P)"

# Fail closed when the sandbox resolves to (or into) the production data dir.
# Derive production from the resolved DB path when the caller configured one.
PROD_DB="${MEMORY_SQLITE_PATH:-$HOME/.config/obsidian-ai-hub/memory.sqlite3}"
PROD_DIR="$(cd "$(dirname "$PROD_DB")" 2>/dev/null && pwd -P || true)"
if [ -n "$PROD_DIR" ]; then
  if [ "$SANDBOX_ABS" = "$PROD_DIR" ]; then
    echo "[opcheck] refusing to start: sandbox dir equals production data dir ($PROD_DIR)" >&2
    exit 1
  fi
  case "$SANDBOX_ABS" in
    "$PROD_DIR"/*)
      echo "[opcheck] refusing to start: sandbox dir is inside production data dir ($PROD_DIR)" >&2
      exit 1
      ;;
  esac
fi

export MEMORY_SQLITE_PATH="$SANDBOX_ABS/memory.sqlite3"
export VAULT_PATH="$SANDBOX_ABS/vault"
export VAULT_INDEX_SQLITE_PATH="$SANDBOX_ABS/vault-index/search.sqlite"
export VAULT_INDEX_CHROMA_PATH="$SANDBOX_ABS/vault-index/chroma"
export HEALTHCARE_SQLITE_PATH="$SANDBOX_ABS/healthcare.sqlite3"
export HEALTHCARE_EXPORT_DIR="$SANDBOX_ABS/healthcare-export"
export HEALTHCARE_IMPORT_STAGING_DIR="$SANDBOX_ABS/healthcare-staging"
export AI_LOG_PATH="$SANDBOX_ABS/ai-log"
export SCREENSHOT_DIR="$SANDBOX_ABS/screenshots"
export OBSIDIAN_AI_HUB_JOBS_DIR="$SANDBOX_ABS/jobs"
export LOCAL_MODEL_DIR="$SANDBOX_ABS/local-models"
export SENTENCE_TRANSFORMERS_HOME="$SANDBOX_ABS/model-cache"
export IMAGE_GENERATION_OUTPUT_DIR="$SANDBOX_ABS/media"
export OBSIDIAN_AI_HUB_HOST="127.0.0.1"
export OBSIDIAN_AI_HUB_PORT="$PORT"
export OBSIDIAN_AI_HUB_WEB_URL="http://127.0.0.1:$PORT"
export OBSIDIAN_AI_HUB_API_TOKEN="$TOKEN"

mkdir -p \
  "$VAULT_PATH" \
  "$AI_LOG_PATH" \
  "$SCREENSHOT_DIR" \
  "$OBSIDIAN_AI_HUB_JOBS_DIR" \
  "$LOCAL_MODEL_DIR" \
  "$SENTENCE_TRANSFORMERS_HOME" \
  "$IMAGE_GENERATION_OUTPUT_DIR"

# Reusable env for follow-up CLI clients (they read config directly).
SANDBOX_ENV_FILE="$SANDBOX_ABS/env.sh"
{
  printf 'export %s=%q\n' MEMORY_SQLITE_PATH "$MEMORY_SQLITE_PATH"
  printf 'export %s=%q\n' VAULT_PATH "$VAULT_PATH"
  printf 'export %s=%q\n' VAULT_INDEX_SQLITE_PATH "$VAULT_INDEX_SQLITE_PATH"
  printf 'export %s=%q\n' VAULT_INDEX_CHROMA_PATH "$VAULT_INDEX_CHROMA_PATH"
  printf 'export %s=%q\n' HEALTHCARE_SQLITE_PATH "$HEALTHCARE_SQLITE_PATH"
  printf 'export %s=%q\n' HEALTHCARE_EXPORT_DIR "$HEALTHCARE_EXPORT_DIR"
  printf 'export %s=%q\n' HEALTHCARE_IMPORT_STAGING_DIR "$HEALTHCARE_IMPORT_STAGING_DIR"
  printf 'export %s=%q\n' AI_LOG_PATH "$AI_LOG_PATH"
  printf 'export %s=%q\n' SCREENSHOT_DIR "$SCREENSHOT_DIR"
  printf 'export %s=%q\n' OBSIDIAN_AI_HUB_JOBS_DIR "$OBSIDIAN_AI_HUB_JOBS_DIR"
  printf 'export %s=%q\n' LOCAL_MODEL_DIR "$LOCAL_MODEL_DIR"
  printf 'export %s=%q\n' SENTENCE_TRANSFORMERS_HOME "$SENTENCE_TRANSFORMERS_HOME"
  printf 'export %s=%q\n' IMAGE_GENERATION_OUTPUT_DIR "$IMAGE_GENERATION_OUTPUT_DIR"
  printf 'export %s=%q\n' OBSIDIAN_AI_HUB_WEB_URL "$OBSIDIAN_AI_HUB_WEB_URL"
  printf 'export %s=%q\n' OBSIDIAN_AI_HUB_API_TOKEN "$OBSIDIAN_AI_HUB_API_TOKEN"
} > "$SANDBOX_ENV_FILE"
chmod 600 "$SANDBOX_ENV_FILE"

cat <<EOF
[opcheck] sandbox : $SANDBOX_ABS
[opcheck] url     : http://127.0.0.1:$PORT
[opcheck] token   : $TOKEN
[opcheck] database: $MEMORY_SQLITE_PATH
[opcheck] vault   : $VAULT_PATH
[opcheck] cli env : source $SANDBOX_ENV_FILE
EOF

exec uv run -m obsidian_ai_hub --serve --serve-port "$PORT"
