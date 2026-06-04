# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

This is an Obsidian Daily Note Automation Tool (`obsidian-ai-hub`) that automates daily note management for Obsidian vaults on macOS. It handles inbox merging, daily target generation, weekly reviews, and calendar event notifications.

## Key Commands

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest tests/

# Run CLI commands
uv run python -m obsidian_ai_hub --merge-inbox
uv run python -m obsidian_ai_hub --make-target
uv run python -m obsidian_ai_hub --notify-calendar-event
uv run python -m obsidian_ai_hub --summerize-week
uv run python -m obsidian_ai_hub --backup

# Run scheduled tasks
./batch/scheduler.sh
```

## Architecture

### Core Modules

| File | Purpose |
|------|---------|
| `main.py` | CLI entry point with argparse - orchestrates all operations |
| `task_runner.py` | Cron-like scheduler that reads `tasks/tasks.yml` and tracks execution in `tasks/last_run.json` |

### Utility Package (`src/obsidian_ai_hub/utils/`)

| File | Purpose |
|------|---------|
| `config.py` | Centralized path and API key configuration |
| `llm_client.py` | Multi-provider LLM client (OpenAI, Gemini, Ollama, llama-cpp-python) |
| `reader.py` | Helper functions for reading daily/weekly notes |
| `extracter.py` | Extract content from notes (YAML frontmatter, subheaders) |

### Configuration

- **Environment variables** (`.env`): `OPENAI_API_KEY`, `VAULT_PATH`, ...
- **YAML Config** `config/config.yml`
- **Task scheduling**: `tasks/tasks.local.yml` defines cron-like tasks (hourly, daily, weekly, monthly)

### macOS Native Integration

- Calendar access via **EventKit** (PyObjC)
- Reminders via **osascript**
- Audio transcription via **Whisper**

## Testing Guidelines
- This is a personal project; avoid writing detailed test codes for implementation details.
- Tests for frequently changing parts, such as string matching or the structure of output markdown, are not required.
- Write only the minimum necessary test code to check for critical errors or crashes.
