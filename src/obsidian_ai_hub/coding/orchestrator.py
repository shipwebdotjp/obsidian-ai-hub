"""High-level AI Orchestrator mediator for coding workspace."""

from __future__ import annotations

import logging
import re
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from obsidian_ai_hub.utils.llm_client import create_langchain_llm
from obsidian_ai_hub.utils.config import (
    CODING_ORCHESTRATOR_MODEL,
    CODING_ORCHESTRATOR_PROVIDER,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """あなたはGitリポジトリの分析・編集・構築を行う専用コーディングワークスペースの上位AIエージェント（オーケストレーター）です。
ユーザーからの要求を理解し、必要に応じて裏で控えるコーディングCLIワーカー（Codex/OpenCode）に作業を指示し、結果をまとめてユーザーへ回答します。

【対話方針】
- コードの調査、ファイルの変更・作成・削除、テストの実行、リポジトリの操作が必要な場合は、ワーカーへ作業を依頼してください。
- ワーカーへ作業を依頼する場合は、応答の最後に次の形式で具体的な作業指示を含めてください:
<cli_request>
ワーカー（Codex/OpenCode CLI）への具体的なプロンプト・作業指示
</cli_request>
- 単純な疑問の解消、補足説明、直前の実行結果に対する意見交換など、ワーカーによるコード操作が不要な場合は <cli_request> タグを含めず直接回答してください。
- ユーザーに分かりやすく丁寧な日本語で回答してください。
"""


def parse_cli_request(text: str) -> Tuple[str, Optional[str]]:
    """Parse orchestrator text to extract any <cli_request> tag.

    Returns (clean_text, cli_prompt_or_none).
    """
    pattern = r"<cli_request>\s*(.*?)\s*</cli_request>"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return text.strip(), None

    cli_prompt = match.group(1).strip()
    # Strip tag from visible orchestrator text
    clean_text = re.sub(pattern, "", text, flags=re.DOTALL)
    clean_text = re.sub(r"\n\s*\n\s*\n", "\n\n", clean_text).strip()
    return clean_text, cli_prompt


class CodingOrchestrator:
    """Orchestrator that mediates between user and coding CLI backend."""

    def __init__(
        self,
        provider: str = CODING_ORCHESTRATOR_PROVIDER,
        model: str = CODING_ORCHESTRATOR_MODEL,
    ):
        self.provider = provider
        self.model = model

    def _build_messages(
        self,
        history: List[Dict[str, str]],
        new_user_message: str,
        repo_path: str,
        backend_name: str,
    ) -> List[Any]:
        sys_msg = (
            f"{SYSTEM_PROMPT}\n\n"
            f"【現在の環境情報】\n"
            f"- 対象リポジトリパス: {repo_path}\n"
            f"- 使用CLIバックエンド: {backend_name}\n"
        )
        msgs: List[Any] = [SystemMessage(content=sys_msg)]

        for h in history:
            role = h.get("role")
            content = h.get("content", "")
            if role == "user":
                msgs.append(HumanMessage(content=content))
            elif role == "orchestrator":
                msgs.append(AIMessage(content=content))
            elif role == "worker":
                # Worker response provided as system/context observation
                msgs.append(
                    SystemMessage(content=f"【CLIワーカーの前回実行結果】\n{content}")
                )

        msgs.append(HumanMessage(content=new_user_message))
        return msgs

    async def stream_response(
        self,
        history: List[Dict[str, str]],
        new_user_message: str,
        repo_path: str,
        backend_name: str,
    ) -> AsyncGenerator[str, None]:
        """Stream orchestrator tokens asynchronously."""
        llm = create_langchain_llm(provider=self.provider, model=self.model, temperature=0.7)
        messages = self._build_messages(history, new_user_message, repo_path, backend_name)

        try:
            async for chunk in llm.astream(messages):
                content = getattr(chunk, "content", "")
                if isinstance(content, str) and content:
                    yield content
                elif isinstance(content, list):
                    # Handle multimodal or list chunks if any
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            yield part.get("text", "")
                        elif isinstance(part, str):
                            yield part
        except Exception as exc:
            logger.exception("Orchestrator streaming failed")
            raise exc
