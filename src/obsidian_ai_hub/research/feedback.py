"""Canonical HITL feedback reason definitions.

Single source of truth for the rejection reason keys, their Japanese labels,
and the structured action choices shown in the HITL confirmation. Consumers
derive their own constants from these so the reason set, labels, and choices
cannot drift apart.
"""

FEEDBACK_REASONS = (
    ("not_interested", "関心外", "この分野・目的に関心がない。"),
    ("low_utility", "実用性不足", "成果が実用的でないと感じる。"),
    ("vague", "抽象的・不明確", "テーマが抽象的で、調査内容が不明確。"),
    ("duplicate", "既知・重複", "すでに知っている・既存テーマと重複する。"),
    ("not_now", "今は優先外", "今は優先度が低い。30日間は同系統を抑制します。"),
    ("other", "その他", "その他の理由。"),
)

ALLOWED_FEEDBACK_REASONS = frozenset(key for key, _, _ in FEEDBACK_REASONS)

FEEDBACK_REASON_LABELS = {key: label for key, label, _ in FEEDBACK_REASONS}

FEEDBACK_ACTION_CHOICES = [
    {
        "value": f"reject:{key}",
        "label": f"却下: {label}",
        "description": description,
    }
    for key, label, description in FEEDBACK_REASONS
]
