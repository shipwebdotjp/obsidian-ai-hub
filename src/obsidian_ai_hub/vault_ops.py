"""Thin CLI wrapper for Vault file writes (``--vault-write``).

Reuses the Web service (same validation and atomic write) so scripts and
agents can seed Vault notes without an HTTP client.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from obsidian_ai_hub.web.services.vault import write_vault_file


def main_vault_write(
    relative_path: str,
    content_file: str | None,
    overwrite: bool,
) -> int:
    """Write UTF-8 content from a file (or stdin with ``-``) to the Vault."""
    try:
        if not isinstance(relative_path, str) or not relative_path.lower().endswith(
            ".md"
        ):
            raise ValueError("--vault-write は .md ファイルのみ指定できます")
        if content_file in (None, "-"):
            content = sys.stdin.read()
        else:
            content = Path(content_file).read_text(encoding="utf-8")
        result = write_vault_file(relative_path, content, overwrite=overwrite)
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {"success": False, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))
    return 0
