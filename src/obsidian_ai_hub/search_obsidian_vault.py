import json
import sys

from obsidian_ai_hub.handler.obsidian_vault_retriever import search_obsidian_vault


def main(query: str, k: int = 10, search_mode: str = "hybrid", json_output: bool = False):
    """
    CLI wrapper for searching the Obsidian vault.
    """
    result_json = search_obsidian_vault.invoke({
        "query": query,
        "k": int(k),
        "search_mode": search_mode
    })

    if json_output:
        # result_json is already a JSON string from the retriever
        print(result_json)
        return

    try:
        results = json.loads(result_json)
    except json.JSONDecodeError:
        print(f"Error: Failed to parse search results. Raw output: {result_json}", file=sys.stderr)
        sys.exit(1)

    if isinstance(results, dict) and "error" in results:
        print(f"Error: {results['error']}", file=sys.stderr)
        sys.exit(1)

    if not results:
        print("No results found.")
        return

    for i, hit in enumerate(results, 1):
        score = hit.get("score", 0.0)
        content = hit.get("content", "")
        metadata = hit.get("metadata", {})
        path = metadata.get("file_path", "Unknown path")

        print(f"{i}. [{score:.4f}] {path}")
        print("-" * 40)
        print(content)
        print("-" * 40)
        print()
