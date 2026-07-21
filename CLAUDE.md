# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an Obsidian Daily Note Automation Tool (`obsidian-ai-hub`) that automates daily note management for Obsidian vaults on macOS. It handles inbox merging, daily target generation, weekly reviews, and calendar event notifications.

## Key Commands

```bash
# Install dependencies
pip install -e .

# Run tests
pytest tests/

# Run CLI commands
python -m obsidian_ai_hub --merge-inbox
python -m obsidian_ai_hub --make-target
python -m obsidian_ai_hub --write-today-schedule
python -m obsidian_ai_hub --summerize-week
python -m obsidian_ai_hub --backup

# Run scheduled tasks
./batch/scheduler.sh
```

## Architecture

### Core Modules

| File | Purpose |
|------|---------|
| `main.py` | CLI entry point with argparse - orchestrates all operations |
| `task_runner.py` | Cron-like scheduler that reads `tasks/tasks.yml` and tracks execution in `tasks/last_run.json` |
| `obsidian_inbox_merge.py` | Merges inbox files (markdown/audio) into daily notes; supports Whisper transcription |
| `make_today_target.py` | Generates daily targets using LLM analysis of journal history |
| `write_today_schedule.py` | Fetches Apple Calendar/Reminders events and writes them into today's daily note |
| `summerize_week.py` | Generates weekly review summaries via LLM |
| `do_backup.py` | Rsync-based backup utility |
| `sync_knowledge.py` | Synchronizes Obsidian Vault files with Open Web UI knowledge base |

### Utility Package (`src/obsidian_ai_hub/utils/`)

| File | Purpose |
|------|---------|
| `config.py` | Centralized path and API key configuration |
| `llm_client.py` | Multi-provider LLM client (OpenAI, Gemini, Ollama, llama-cpp-python) |
| `reader.py` | Helper functions for reading daily/weekly notes |
| `extracter.py` | Extract content from notes (YAML frontmatter, subheaders) |
| `web_ui_client.py` | Open Web UI API client for knowledge base operations |

### Configuration

- **Environment variables** (`.env`): `OPENAI_API_KEY`, `GEMINI_API_KEY`, `VAULT_PATH`, `LINE_MESSAGING_TOKEN`, `LINE_TARGET_ID`, `GOG_CALENDAR_ID`, `OPEN_WEB_UI_BASE_URL`, `OPEN_WEB_UI_API_KEY`, `OPEN_WEB_UI_KNOWLEDGE_ID`
- **Task scheduling**: `tasks/tasks.yml` defines cron-like tasks (hourly, daily, weekly, monthly)
- **Vault structure**: `daily/YYYY/MM/`, `inbox/`, `template/daily.md`, `copilot/knowledge/`
- **Sync state**: `tasks/knowledge_sync_state.json` tracks file sync status

### LLM Providers

The system supports multiple LLM providers via `generate_llm_response()`:
- `openai` - OpenAI Chat Completions API
- `gemini` - Google Gemini API
- `ollama` - Local Ollama server
- `local` - llama-cpp-python with GGUF models

###macOS Native Integration

- Calendar access via **EventKit** (PyObjC)
- Reminders via **osascript**
- Audio transcription via **Whisper**
