# obsidian-ai-hub

obsidian-ai-hub is an automation toolkit for Obsidian daily-note workflows.

It helps with:
- organizing inbox items into a daily note
- generating daily and weekly summaries
- notifying you about today’s schedule and tasks
- collecting and organizing research topics
- connecting an Obsidian vault with external services

## Highlights

- Merge inbox content into a daily note
- Create daily targets and reminders
- Notify upcoming calendar events
- Back up vault data and related artifacts
- Keep secrets and public configuration separate

## Installation

1. Clone the repository.
2. Create your local configuration files:
   - `cp config/config.example.yml config/config.yml`
   - `cp .env.example .env`
3. Edit `config/config.yml` to match your vault paths and backup settings.
4. Edit `.env` to set API keys, tokens, and machine-specific paths.
5. Run the test suite:
   - `pytest tests/`

### install to LaunchAgent
1. chmod +x install.sh
2. make install
3. make enable

## Configuration

Use the following split to keep the project OSS-friendly:

`.env`
- secrets
- API keys and tokens
- personal absolute paths
- environment-specific values
- `LOCAL_MODEL_DIR` is used as the base download cache for local embedder models

`config/config.yml`
- non-sensitive application settings
- relative paths and filenames inside the vault
- backup targets
- default feature values
- vault index storage paths and embedder model name

## Usage

```bash
python -m obsidian_ai_hub --merge-inbox
python -m obsidian_ai_hub --make-target
python -m obsidian_ai_hub --notify-calendar-event
python -m obsidian_ai_hub --summerize-week
python -m obsidian_ai_hub --backup
python -m obsidian_ai_hub --sync-vault
python -m obsidian_ai_hub --screenshot
```

The vault sync command indexes the full `VAULT_PATH` tree into `md-hybrid-search` and stores its SQLite/Chroma data outside the vault by default.

## Project Structure

- `src/obsidian_ai_hub/` — application code
- `config/` — configuration templates
- `tests/` — automated tests

## License

This project is licensed under the MIT License.

See the `LICENSE` file for details.
