import json
import logging
from concurrent.futures import ThreadPoolExecutor

from langchain_core.tools import tool

from obsidian_ai_hub.sync_valut import build_vault_search_index

logger = logging.getLogger(__name__)

_vault_index = None

# md-hybrid-search opens its SQLite connection with sqlite3's default
# check_same_thread=True, so a SearchIndex may only be touched from the thread
# that created it. FastAPI runs sync routes in a threadpool where each request
# can land on a different thread, so a lazily-built process-wide singleton
# breaks with "SQLite objects created in a thread can only be used in that
# same thread". All index access therefore goes through this single-worker
# executor; it also serializes concurrent searches.
_vault_executor = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="vault-index"
)


def _get_vault_index():
    global _vault_index
    if _vault_index is None:
        _vault_index = build_vault_search_index()
    return _vault_index


def _do_search(query: str, k: int, search_mode: str) -> str:
    # Runs only on the dedicated vault-index worker thread (see _vault_executor).
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


def _search_obsidian_vault_core_sync(
    query: str,
    k: int = 10,
    search_mode: str = "hybrid",
) -> str:
    return _vault_executor.submit(_do_search, query, k, search_mode).result()


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
