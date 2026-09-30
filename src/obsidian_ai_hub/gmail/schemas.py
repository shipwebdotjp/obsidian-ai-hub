from __future__ import annotations

import uuid
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

class GmailSearchMessagesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        default="",
        description="Gmail 検索クエリ（例: 'from:user@example.com is:unread'）。空文字の場合は直近メッセージを取得。",
    )
    label_ids: Optional[list[str]] = Field(
        default=None,
        description="Gmail ラベルIDフィルター（例: ['INBOX', 'UNREAD']）。",
    )
    page_token: Optional[str] = Field(
        default=None,
        description="次ページ取得用トークン。",
    )
    include_spam_trash: bool = Field(
        default=False,
        description="迷惑メール・ゴミ箱を含めるか。",
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=20,
        strict=True,
        description="取得件数 (1-20)。既定: 10。",
    )


class GmailReadMessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(
        min_length=1,
        description="読み取る Gmail メッセージID（必須）。",
    )


class GmailCreateDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["new", "reply"] = Field(
        description="下書き作成モード: 'new' (新規メール) または 'reply' (返信)。",
    )
    body_text: str = Field(
        min_length=1,
        description="下書きメールの本文プレーンテキスト（必須）。",
    )
    to: Optional[str] = Field(
        default=None,
        description="宛先アドレス (mode='new' の場合必須。コンマ区切り可)。",
    )
    cc: Optional[str] = Field(
        default=None,
        description="Cc 宛先アドレス (任意)。",
    )
    bcc: Optional[str] = Field(
        default=None,
        description="Bcc 宛先アドレス (任意)。",
    )
    subject: Optional[str] = Field(
        default=None,
        description="件名 (mode='new' の場合任意。mode='reply' では省略時に元件名に Re: を付与)。",
    )
    reply_to_message_id: Optional[str] = Field(
        default=None,
        description="返信対象の Gmail メッセージID (mode='reply' の場合必須)。",
    )
    reply_all: bool = Field(
        default=False,
        description="全員に返信するか (mode='reply' の場合)。",
    )
