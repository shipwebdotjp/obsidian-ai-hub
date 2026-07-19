import unicodedata
import logging

logger = logging.getLogger(__name__)

TOPIC_ENUM = [
    "LLM・AI活用", "AI・機械学習", "ソフトウェア開発", "開発環境・DevOps",
    "データ・分析", "クラウド・インフラ", "ツール・自動化（生産性）",
    "リサーチ手法・情報整理（PKM）", "ガジェット・デバイス", "金融・投資",
    "マーケティング・発信", "ライティング・コンテンツ制作", "コミュニケーション・対人関係",
    "思考法・判断力", "学習・教育", "自己改善（習慣・時間管理）", "メンタル・心理",
    "健康・医療", "生活・暮らし", "信仰・聖書", "その他"
]

def normalize_topics(topics: list[str] | None, limit: int = 5) -> list[str]:
    """
    Normalizes topics:
    - Performs NFKC normalization and strips leading/trailing whitespace.
    - Removes duplicates while maintaining order.
    - Replaces non-empty strings not in the candidate list with 'その他'.
    - Limits to maximum `limit` elements (default 5).
    - If `topics` is None or empty, returns an empty list.
    """
    if not topics:
        return []

    normalized = []
    seen = set()

    for topic in topics:
        if topic is None:
            continue
        # NFKC normalization and strip
        normalized_str = unicodedata.normalize('NFKC', str(topic)).strip()
        if not normalized_str:
            continue

        # Check if in candidate list, otherwise replace with 'その他'
        if normalized_str not in TOPIC_ENUM:
            logger.warning(f"Topic '{normalized_str}' is not in candidate list. Replaced with 'その他'.")
            normalized_str = "その他"

        if normalized_str not in seen:
            seen.add(normalized_str)
            normalized.append(normalized_str)

    return normalized[:limit]


def normalize_keywords(keywords: list[object] | None, limit: int = 10) -> list[str]:
    """Trim, deduplicate, and limit LLM-generated keywords."""
    if not isinstance(keywords, list):
        return []

    normalized = []
    seen = set()
    for keyword in keywords:
        if not isinstance(keyword, str):
            continue
        normalized_keyword = keyword.strip()
        if not normalized_keyword or normalized_keyword in seen:
            continue
        seen.add(normalized_keyword)
        normalized.append(normalized_keyword)

    return normalized[:limit]
