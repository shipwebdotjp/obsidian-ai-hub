import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from langchain.tools import tool

from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

VECTORSEARCH_PYTHON = config.RESEARCH_VECTORSEARCH_PYTHON
VECTORSEARCH_SCRIPT = config.RESEARCH_VECTORSEARCH_SCRIPT
DEFAULT_COLLECTION = "documents"

async def _search_obsidian_vault_core(
    query: str, 
    k: int = 10, 
    search_mode: str = "hybrid"
) -> str:
    command = [
        VECTORSEARCH_PYTHON,
        VECTORSEARCH_SCRIPT,
        query,
        "-k", str(k),
        "-c", DEFAULT_COLLECTION,
        "--search-mode", search_mode,
        "--json",
    ]

    try:
        # 非同期サブプロセス実行
        process = await asyncio.create_subprocess_exec(
            *command, 
            stdout=asyncio.subprocess.PIPE, 
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error("Search command failed")
            return json.dumps({"error": "Search command failed"}, ensure_ascii=False)

        # 検索結果をそのまま文字列（JSON形式）として返す
        return stdout.decode()

    except Exception as e:
        logger.exception("Unexpected error during obsidian search")
        return json.dumps({"error": f"Unexpected error: {type(e).__name__}"}, ensure_ascii=False)

@tool
async def search_obsidian_vault(
    query: str, 
    k: int = 10, 
    search_mode: str = "hybrid"
) -> str:
    """
    ユーザーのObsidian Vault（個人ノート）からセマンティック検索およびキーワード検索を行います。
    過去の記憶、知識、メモ、価値観などに関する質問に対して、関連するノートの内容を検索して返します。

    :param query: 検索クエリ（例: "ライフスタイル 価値観"）
    :param k: 取得する結果の件数 (デフォルト: 10)
    :param search_mode: 検索モード ('similarity', 'keyword', 'hybrid' のいずれか。デフォルトは 'hybrid')
    """
    return await _search_obsidian_vault_core(query=query, k=k, search_mode=search_mode)

# 同期的に呼び出したい場合（LangChainの同期Agent用）
@tool
def search_obsidian_vault_sync(
    query: str, 
    k: int = 10, 
    search_mode: str = "hybrid"
) -> str:
    """
    (同期版) ユーザーのObsidian Vaultから検索を行います。
    """
    # asyncio.run() 等でラップして実行
    return asyncio.run(_search_obsidian_vault_core(query=query, k=k, search_mode=search_mode))
