"""Canonical rejection reason definitions for AI planner proposals.

Single source of truth for the reason keys and their Japanese labels shown in
the Planner reject UI. Consumers (store validation, web schemas, prompt context)
derive their constants from these so the reason set cannot drift apart.

Reasons are grouped by how the generator should react to them:

- ``duplicate`` / ``done`` / ``not_needed``: the content itself is unwanted, so
  the same content must not be proposed again.
- ``not_now``: temporarily deprioritized; suppress the same line for a window.
- ``bad_time`` / ``wrong_kind`` / ``vague``: the content may be valid but the
  proposal shape is wrong; do not suppress, fix the shape.
- ``other``: free comment only.
"""

REJECTION_REASONS = (
    ("duplicate", "既知・重複", "すでに予定・リマインダーに登録されている。"),
    ("done", "完了済み", "すでに完了している。"),
    ("not_needed", "不要", "この内容は必要ない。"),
    ("not_now", "今は優先外", "今は優先度が低い。30日間は同系統を抑制します。"),
    ("bad_time", "日時が不適切", "日時・期限が実際と合わない。"),
    ("wrong_kind", "種別違い", "予定とリマインダーの種別が合わない。"),
    ("vague", "内容が曖昧", "内容が抽象的で具体性がない。"),
    ("other", "その他", "その他の理由。"),
)

ALLOWED_REJECTION_REASONS = frozenset(key for key, _, _ in REJECTION_REASONS)

REJECTION_REASON_LABELS = {key: label for key, label, _ in REJECTION_REASONS}

# Content itself is unwanted; the same content must not be proposed again.
SUPPRESS_REJECTION_REASONS = frozenset({"duplicate", "done", "not_needed"})

# Temporarily deprioritized; suppress the same line for a window.
DEFER_REJECTION_REASONS = frozenset({"not_now"})

# Shape is wrong; do not suppress, re-propose with a corrected shape.
MODIFY_REJECTION_REASONS = frozenset({"bad_time", "wrong_kind", "vague"})


def is_valid_rejection_reason(key: str) -> bool:
    return key in ALLOWED_REJECTION_REASONS


def rejection_reason_label(key: str) -> str:
    return REJECTION_REASON_LABELS.get(key, key)
