from __future__ import annotations

import os
import json
import tempfile
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from obsidian_ai_hub.gmail.config import SCOPES, get_client_secret_path, get_token_path


class GmailAuthError(Exception):
    """Raised when Gmail authorization is missing, expired, revoked, or invalid."""
    pass


def ensure_owner_only_dir(dir_path: Path) -> None:
    """Ensure directory exists with 0700 permissions."""
    dir_path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(dir_path, 0o700)
    except OSError:
        pass


def save_token_atomically(token_data: str, token_path: Path) -> None:
    """Save token JSON string atomically with 0600 file permissions."""
    ensure_owner_only_dir(token_path.parent)
    temp_fd, temp_path_str = tempfile.mkstemp(
        dir=str(token_path.parent), prefix=".token_", suffix=".tmp"
    )
    temp_path = Path(temp_path_str)
    try:
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            f.write(token_data)
        temp_path.replace(token_path)
        try:
            os.chmod(token_path, 0o600)
        except OSError:
            pass
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def load_credentials() -> Credentials:
    """Load valid credentials from token file or refresh if expired.

    Raises GmailAuthError if missing, revoked, expired-without-refresh, or scope-inadequate.
    Runtime tools MUST NEVER trigger interactive browser flow.
    """
    token_path = get_token_path()
    if not token_path.exists():
        raise GmailAuthError(
            f"Gmail token file not found at '{token_path}'. "
            "Please run CLI '--gmail-authorize' to authorize your Gmail account."
        )

    try:
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    except Exception as exc:
        raise GmailAuthError(
            f"Failed to parse Gmail token file at '{token_path}': {exc}. "
            "Please run CLI '--gmail-authorize' to re-authorize."
        ) from exc

    if not creds:
        raise GmailAuthError(
            f"Invalid Gmail credentials in '{token_path}'. "
            "Please run CLI '--gmail-authorize' to re-authorize."
        )

    # Check scopes
    if creds.scopes:
        missing_scopes = set(SCOPES) - set(creds.scopes)
        if missing_scopes:
            raise GmailAuthError(
                f"Gmail token is missing required scope(s): {sorted(missing_scopes)}. "
                "Please run CLI '--gmail-authorize' to grant required scopes."
            )

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                save_token_atomically(creds.to_json(), token_path)
            except Exception as exc:
                raise GmailAuthError(
                    f"Failed to refresh Gmail access token: {exc}. "
                    "Token may be revoked or expired. Please run CLI '--gmail-authorize' to re-authorize."
                ) from exc
        else:
            raise GmailAuthError(
                "Gmail credentials are invalid or expired without a refresh token. "
                "Please run CLI '--gmail-authorize' to re-authorize."
            )

    return creds


def authorize_interactive() -> dict[str, Any]:
    """Execute interactive OAuth authorization flow via CLI (--gmail-authorize).

    Runs InstalledAppFlow.run_local_server on 127.0.0.1, verifies profile via getProfile,
    saves token atomically, and returns non-secret summary information.
    """
    secret_path = get_client_secret_path()
    if not secret_path.exists():
        raise GmailAuthError(
            f"Gmail OAuth client secret file not found at '{secret_path}'. "
            "Please place your Desktop OAuth credentials JSON from Google Cloud Console at that path "
            "or set GMAIL_CLIENT_SECRET_PATH."
        )

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
    except Exception as exc:
        raise GmailAuthError(
            f"Failed to load Gmail client secrets from '{secret_path}': {exc}"
        ) from exc

    try:
        creds = flow.run_local_server(
            host="127.0.0.1",
            port=0,
            authorization_prompt_message="Open this link in your browser to authorize Gmail integration:\n{url}",
            success_message="Gmail authorization complete! You may close this window.",
            access_type="offline",
            prompt="consent",
        )
    except Exception as exc:
        raise GmailAuthError(f"OAuth local server flow failed or was cancelled: {exc}") from exc

    if not creds or not creds.valid:
        raise GmailAuthError("OAuth flow completed but failed to obtain valid credentials.")

    # Confirm selected mailbox using users().getProfile
    try:
        service = build("gmail", "v1", credentials=creds)
        profile = service.users().getProfile(userId="me").execute()
        email_address = profile.get("emailAddress", "unknown")
    except HttpError as exc:
        raise GmailAuthError(f"Failed to verify Gmail account profile: {exc}") from exc

    token_path = get_token_path()
    save_token_atomically(creds.to_json(), token_path)

    return {
        "email_address": email_address,
        "token_path": str(token_path),
        "scopes": SCOPES,
    }
