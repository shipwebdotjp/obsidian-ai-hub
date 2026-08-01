import json
import logging
import threading
from pathlib import Path

from obsidian_ai_hub.handler import obsidian_vault_retriever

logger = logging.getLogger(__name__)


# --- Vault Search services ---

_vault_search_lock = threading.Lock()


def search_vault(q: str, k: int = 10, mode: str = "hybrid") -> dict:
    with _vault_search_lock:
        result_json = obsidian_vault_retriever.search_obsidian_vault.func(
            query=q, k=k, search_mode=mode
        )
    try:
        results = json.loads(result_json)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse vault search JSON output: %s", e)
        raise ValueError("vault search returned invalid JSON") from e
    if isinstance(results, dict) and "error" in results:
        raise ValueError(results["error"])
    from obsidian_ai_hub.utils import config

    vault_name = Path(config.VAULT_PATH).name
    for hit in results:
        if not isinstance(hit.get("metadata"), dict):
            hit["metadata"] = {}
        hit["metadata"]["vault_name"] = vault_name
    return {"items": results, "total": len(results)}


def get_vault_file(relative_path: str) -> dict:
    from obsidian_ai_hub.utils import config

    vault_dir = Path(config.VAULT_PATH).resolve()

    p = Path(relative_path)
    if p.is_absolute():
        raise ValueError("Absolute paths are not allowed")

    if ".." in p.parts:
        raise ValueError("Path traversal components (..) are not allowed")

    if p.suffix.lower() != ".md":
        raise ValueError("Only Markdown (.md) files are allowed")

    # Resolve resolved path (to handle symlinks properly)
    try:
        resolved_path = (vault_dir / p).resolve(strict=True)
    except FileNotFoundError:
        # Check traversal on non-existing path
        resolved_path = (vault_dir / p).resolve(strict=False)
        try:
            resolved_path.relative_to(vault_dir)
        except ValueError:
            raise ValueError("Path is outside the Vault")
        raise FileNotFoundError("File not found")

    # Verify containment for existing file
    try:
        resolved_path.relative_to(vault_dir)
    except ValueError:
        raise ValueError("Path is outside the Vault")

    if not resolved_path.is_file():
        raise FileNotFoundError("File is not a file")

    with open(resolved_path, "r", encoding="utf-8") as f:
        content = f.read()

    return {
        "content": content,
        "relative_path": relative_path,
    }
