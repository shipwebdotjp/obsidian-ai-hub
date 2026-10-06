import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from langchain_core.tools import tool

from obsidian_ai_hub.sync_valut import build_vault_search_index
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

# md-hybrid-search opens its SQLite connection with sqlite3's default
# check_same_thread=True, so a SearchIndex may only be touched from the thread
# that created it. FastAPI runs sync routes in a threadpool where each request
# can land on a different thread, so a lazily-built process-wide singleton
# breaks with "SQLite objects created in a thread can only be used in that
# same thread". Each Vault therefore owns a dedicated single-worker executor;
# all index access for that Vault goes through its executor, which also
# serializes concurrent searches for the Vault.
_vault_indexes: dict[str, object] = {}
_vault_executors: dict[str, ThreadPoolExecutor] = {}
_vault_lock = threading.Lock()


def _get_vault_executor(vault_id: str) -> ThreadPoolExecutor:
    with _vault_lock:
        executor = _vault_executors.get(vault_id)
        if executor is None:
            executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix=f"vault-index-{vault_id}"
            )
            _vault_executors[vault_id] = executor
        return executor


def _get_vault_index(vault_id: str):
    # Called only on the Vault's dedicated worker thread.
    index = _vault_indexes.get(vault_id)
    if index is None:
        index = build_vault_search_index(vault_id)
        _vault_indexes[vault_id] = index
    return index


def _do_search(query: str, k: int, search_mode: str, vault_id: str) -> str:
    # Runs only on the dedicated worker thread for *vault_id*.
    try:
        index = _get_vault_index(vault_id)

        results = index.search(
            query=query,
            limit=k,
            mode=search_mode,
        )

        formatted_results = []
        for hit in results:
            metadata = dict(hit.metadata) if isinstance(hit.metadata, dict) else {}
            metadata.setdefault("vault_id", vault_id)
            formatted_results.append(
                {
                    "content": hit.content,
                    "metadata": metadata,
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
    vault_id: str | None = None,
) -> str:
    vid = config.resolve_vault_descriptor(vault_id).vault_id
    executor = _get_vault_executor(vid)
    return executor.submit(_do_search, query, k, search_mode, vid).result()


def search_single_vault(
    query: str,
    k: int = 10,
    search_mode: str = "hybrid",
    vault_id: str | None = None,
) -> str:
    """Search one Vault index (service-layer entry point, Vault ID aware)."""
    return _search_obsidian_vault_core_sync(
        query=query, k=k, search_mode=search_mode, vault_id=vault_id
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
