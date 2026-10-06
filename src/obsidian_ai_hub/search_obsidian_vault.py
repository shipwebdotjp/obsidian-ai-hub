import json
import sys

from obsidian_ai_hub.web.services import vault as vault_service


def main(
    query: str,
    k: int = 10,
    search_mode: str = "hybrid",
    json_output: bool = False,
    vault_ids: list[str] | None = None,
):
    """
    CLI wrapper for searching the Obsidian vaults (human actor, all Vaults by default).
    """
    try:
        result = vault_service.search_vault(
            q=query, k=int(k), mode=search_mode, vault_ids=vault_ids, actor="human"
        )
    except (ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    results = result["items"]

    if json_output:
        print(json.dumps(results, ensure_ascii=False))
        return

    if not results:
        print("No results found.")
        return

    for i, hit in enumerate(results, 1):
        score = hit.get("score", 0.0)
        content = hit.get("content", "")
        metadata = hit.get("metadata", {})
        vault_id = metadata.get("vault_id", "?")
        path = metadata.get("file_path", metadata.get("relative_path", "Unknown path"))

        print(f"{i}. [{score:.4f}] [{vault_id}] {path}")
        print("-" * 40)
        print(content)
        print("-" * 40)
        print()
