import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from langchain.tools import tool

from obsidian_ai_hub.sync_valut import build_vault_search_index
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

_vault_index = None

def _get_vault_index():
    global _vault_index
    if _vault_index is None:
        _vault_index = build_vault_search_index()
    return _vault_index

async def _search_obsidian_vault_core(
    query: str, 
    k: int = 10, 
    search_mode: str = "hybrid"
) -> str:
    try:
        index = _get_vault_index()
        # 同期的な検索処理を別スレッドで実行
        results = await asyncio.to_thread(
            index.search,
            query=query,
            limit=k,
            mode=search_mode
        )

        # 検索結果をJSON形式のリストに変換
        formatted_results = []
        for hit in results:
            formatted_results.append({
                "content": hit.content,
                "metadata": hit.metadata,
                "score": hit.score
            })

        return json.dumps(formatted_results, ensure_ascii=False)

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
