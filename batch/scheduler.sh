#!/bin/bash
cd "$(dirname "$0")/.."
# source .venv/bin/activate
.venv/bin/python3 -m obsidian_ai_hub.task_runner
