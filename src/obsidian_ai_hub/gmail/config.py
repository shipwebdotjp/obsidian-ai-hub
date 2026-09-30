from __future__ import annotations

import os
from pathlib import Path
from obsidian_ai_hub.utils import config

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]

def get_client_secret_path() -> Path:
    if config.IS_TEST_ENV:
        return config.TEST_WORKSPACE / "gmail" / "client_secret.json"
    env_path = os.getenv("GMAIL_CLIENT_SECRET_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return Path("~/.config/obsidian-ai-hub/gmail/client_secret.json").expanduser()

def get_token_path() -> Path:
    if config.IS_TEST_ENV:
        return config.TEST_WORKSPACE / "gmail" / "token.json"
    env_path = os.getenv("GMAIL_TOKEN_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return Path("~/.config/obsidian-ai-hub/gmail/token.json").expanduser()
