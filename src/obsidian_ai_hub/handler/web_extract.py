from __future__ import annotations

import argparse
import json
import logging

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from langchain_tavily import TavilyExtract

from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)


def _get_web_extract_tool() -> TavilyExtract:
    if not config.TAVILY_API_KEY:
        logger.error("TAVILY_API_KEY is not set in environment variables")
        raise RuntimeError("TAVILY_API_KEY is not set")

    # TavilyExtractの初期化
    return TavilyExtract(
        # 必要に応じて "advanced" も設定可能（LinkedInやYouTubeなどの読み込みに強い）
        extract_depth="basic",
        include_images=False,
    )

class WebExtractInput(BaseModel):
    """Input for web extraction."""
    urls: list[str] = Field(description="A list of URL strings to extract content from. Maximum 20 URLs at once.")


@tool(args_schema=WebExtractInput)
def web_extract(urls: list[str]) -> str:
    """
    Extract the main content from specific web pages.

    Use this when you already have one or more relevant URLs and need the actual page content rather than search snippets.
    Examples: reading official docs, confirming numbers or dates, checking requirements or limitations, verifying claims, or summarizing a specific page.

    Usually use web_search first to discover candidate pages, then use web_extract only for the most relevant URLs.
    Do not use this tool for broad web discovery.
    
    Args:
        urls: A list of URL strings to extract content from. Maximum 20 URLs at once.
    """
    try:
        tavily_extract = _get_web_extract_tool()
        
        # langchain_tavilyのTavilyExtractは引数にurlsリストを取る
        results = tavily_extract.invoke({"urls": urls})
        
        # そのままJSON文字列として返す
        return json.dumps(results, ensure_ascii=False)
        
    except Exception as exc:
        logger.exception("Web extract failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def main(url: str | None = None) -> str:
    if url is None:
        parser = argparse.ArgumentParser(description="Run a Tavily Extract")
        parser.add_argument("url", help="抽出したいURL (1件)")
        args = parser.parse_args()
        url = args.url

    # テスト用の呼び出し (リスト形式で渡す)
    return web_extract.invoke({"urls": [url]})


if __name__ == "__main__":
    main()