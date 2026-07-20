from __future__ import annotations

import argparse
import json
import logging

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from langchain_tavily import TavilySearch

from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)


def _get_web_search_tool(k: int = 5) -> TavilySearch:
    if not config.TAVILY_API_KEY:
        logger.error("TAVILY_API_KEY is not set in environment variables")
        raise RuntimeError("TAVILY_API_KEY is not set")

    return TavilySearch(
        max_results=k,
        api_key=config.TAVILY_API_KEY,
        include_answer=True,
        include_raw_content=False,
        include_usage=True,
    )


class WebSearchInput(BaseModel):
    """Input for web search."""

    query: str = Field(description="Search query to look up on the web.")
    k: int = Field(default=5, description="Number of search results to return.")


@tool(args_schema=WebSearchInput)
def web_search(query: str, k: int = 5) -> str:
    config.ensure_external_allowed("Web search (Tavily)")

    """
    Search the public web and return relevant results with titles, URLs, and snippets.

    Use this when you need up-to-date or external information, or when you need to find which page to read next.
    Examples: recent news, fact checking, official documentation, technical specs, product comparisons, pricing, release notes, policies, or other time-sensitive information.

    Use this tool first when the target URL is not yet known.
    If you already have a specific URL and need the page content, use web_extract instead.

    Prefer a small number of results unless broader coverage is necessary.
    """
    try:
        tavily = _get_web_search_tool(k=k)
        results = tavily.invoke(query)
        return json.dumps(results, ensure_ascii=False)
    except Exception as exc:
        logger.exception("Web search failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def main(query: str | None = None) -> str:
    if query is None:
        parser = argparse.ArgumentParser(description="Run a Tavily search")
        parser.add_argument("query", help="検索クエリ")
        args = parser.parse_args()
        query = args.query

    return web_search.invoke({"query": query, "k": 5})


if __name__ == "__main__":
    main()
