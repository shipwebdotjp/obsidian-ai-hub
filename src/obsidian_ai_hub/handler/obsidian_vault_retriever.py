import json
import logging

from langchain.tools import tool

from obsidian_ai_hub.sync_valut import build_vault_search_index

logger = logging.getLogger(__name__)

_vault_index = None


def _get_vault_index():
    global _vault_index
    if _vault_index is None:
        _vault_index = build_vault_search_index()
    return _vault_index


def _search_obsidian_vault_core_sync(
    query: str,
    k: int = 10,
    search_mode: str = "hybrid",
) -> str:
    try:
        index = _get_vault_index()

        results = index.search(
            query=query,
            limit=k,
            mode=search_mode,
        )

        formatted_results = []
        for hit in results:
            formatted_results.append(
                {
                    "content": hit.content,
                    "metadata": hit.metadata,
                    "score": hit.score,
                }
            )

        return json.dumps(formatted_results, ensure_ascii=False)

    except Exception as e:
        logger.exception("Unexpected error during obsidian search")
        return json.dumps(
            {"error": f"Unexpected error: {type(e).__name__}: {e}"},
            ensure_ascii=False,
        )


@tool
def search_obsidian_vault(
    query: str,
    k: int = 10,
    search_mode: str = "hybrid",
) -> str:
    """
    (同期版) ユーザーのObsidian Vaultから検索を行います。
    """
    return _search_obsidian_vault_core_sync(
        query=query,
        k=k,
        search_mode=search_mode,
    )
