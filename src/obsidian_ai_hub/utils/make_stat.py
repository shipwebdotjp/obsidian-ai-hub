from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
import unicodedata
import re

COMPLEXITY_PRIORITY = {"上級": 3, "中級": 2, "初級": 1}


def parse_ts(ts: str) -> float:
    # "2026-02-27T13:43:58.366200" を想定
    try:
        return datetime.fromisoformat(ts).timestamp()
    except Exception:
        return 0.0


def is_blank(x: Any) -> bool:
    if x is None:
        return True
    if x == "":
        return True
    if isinstance(x, (list, tuple, set, dict)) and len(x) == 0:
        return True
    return False


def should_skip_session(md: dict) -> bool:
    topics = md.get("topics")
    if topics == ["example_topic"]:
        return True

    # 情報がほぼ無いsessionを除外（必要なら項目は調整）
    keys = [
        "topics",
        "intent",
        "sentiment",
        "complexity",
        "value",
        "confidence",
        "keywords",
        "summary",
    ]
    non_blank = sum(0 if is_blank(md.get(k)) else 1 for k in keys)
    return non_blank == 0


def as_list(x: Any) -> list:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def normalize_keyword(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    # 英字だけcasefoldしたい場合もあるが、雑にcasefoldでも日本語はほぼ影響なし
    s = s.casefold()
    return s


@dataclass
class Stat:
    count: int = 0
    conf_sum: float = 0.0
    latest_ts: float = 0.0


def add_stat(stats: dict[str, Stat], label: str, conf: float, ts: float):
    st = stats.get(label)
    if st is None:
        st = Stat()
        stats[label] = st
    st.count += 1
    st.conf_sum += conf
    if ts > st.latest_ts:
        st.latest_ts = ts


def top_k(stats: dict[str, Stat], k: int) -> list[str]:
    items = list(stats.items())
    items.sort(
        key=lambda kv: (kv[1].count, kv[1].conf_sum, kv[1].latest_ts), reverse=True
    )
    return [label for label, _ in items[:k]]


def pick_majority(
    stats: dict[str, Stat], default: str, *, is_complexity: bool = False
) -> str:
    if not stats:
        return default
    items = list(stats.items())
    # 多数決 + タイブレーク
    items.sort(
        key=lambda kv: (kv[1].count, kv[1].conf_sum, kv[1].latest_ts), reverse=True
    )

    # 先頭と同率グループを抽出
    best = items[0][1]
    tied = [
        kv
        for kv in items
        if (kv[1].count, kv[1].conf_sum, kv[1].latest_ts)
        == (best.count, best.conf_sum, best.latest_ts)
    ]
    if len(tied) == 1 or not is_complexity:
        return items[0][0]

    # complexityだけ最後の同率処理：上級 > 中級 > 初級
    tied.sort(key=lambda kv: COMPLEXITY_PRIORITY.get(kv[0], 0), reverse=True)
    return tied[0][0]


def mean_or_none(vals: list[float]) -> Optional[float]:
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def aggregate_daily(ai_logs_metadata_only: dict) -> dict:
    topic_stats: dict[str, Stat] = {}
    intent_stats: dict[str, Stat] = {}
    sentiment_stats: dict[str, Stat] = {}
    complexity_stats: dict[str, Stat] = {}

    value_vals: list[float] = []
    conf_vals: list[float] = []

    # keywordは「正規化キー → (表示ラベル, Stat)」
    kw_map: dict[str, tuple[str, Stat]] = {}

    for _sid, entry in ai_logs_metadata_only.items():
        md = entry.get("metadata", {}) or {}
        ts = parse_ts(entry.get("timestamp", "") or "")
        if should_skip_session(md):
            continue

        conf = md.get("confidence")
        conf = float(conf) if isinstance(conf, (int, float)) else 0.0

        # topics
        for t in as_list(md.get("topics")):
            if isinstance(t, str) and t and t != "example_topic":
                add_stat(topic_stats, t, conf, ts)

        # intent
        for it in as_list(md.get("intent")):
            if isinstance(it, str) and it:
                add_stat(intent_stats, it, conf, ts)

        # sentiment / complexity
        s = md.get("sentiment")
        if isinstance(s, str) and s:
            add_stat(sentiment_stats, s, conf, ts)

        cx = md.get("complexity")
        if isinstance(cx, str) and cx:
            add_stat(complexity_stats, cx, conf, ts)

        # value / confidence 平均
        v = md.get("value")
        if isinstance(v, (int, float)):
            value_vals.append(float(v))

        c = md.get("confidence")
        if isinstance(c, (int, float)):
            conf_vals.append(float(c))

        # keywords
        for kw in as_list(md.get("keywords")):
            if not isinstance(kw, str):
                continue
            kw_disp = kw.strip()
            if not kw_disp:
                continue
            key = normalize_keyword(kw_disp)
            if not key:
                continue

            if key not in kw_map:
                kw_map[key] = (kw_disp, Stat())
            disp, st = kw_map[key]
            # 表示ラベルを「より情報量が多い方」に寄せたいなら、例えば長い方を採用
            if len(kw_disp) > len(disp):
                disp = kw_disp

            st.count += 1
            st.conf_sum += conf
            if ts > st.latest_ts:
                st.latest_ts = ts
            kw_map[key] = (disp, st)

    # 最終出力
    topics = top_k(topic_stats, 3)
    intent = top_k(intent_stats, 3)

    sentiment = pick_majority(sentiment_stats, default="ニュートラル")
    complexity = pick_majority(complexity_stats, default="初級", is_complexity=True)

    value = mean_or_none(value_vals)
    confidence = mean_or_none(conf_vals)

    # keywords上位12
    kw_items = list(kw_map.items())  # (norm_key, (disp, Stat))
    kw_items.sort(
        key=lambda x: (x[1][1].count, x[1][1].conf_sum, x[1][1].latest_ts), reverse=True
    )
    keywords = [disp for _k, (disp, _st) in kw_items[:12]]

    return {
        "topics": topics,
        "intent": intent,
        "sentiment": sentiment,
        "complexity": complexity,
        "value": value,
        "confidence": confidence,
        "keywords": keywords,
    }
