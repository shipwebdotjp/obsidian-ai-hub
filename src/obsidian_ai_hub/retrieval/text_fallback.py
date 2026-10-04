"""Lightweight token-match fallback for retrieval searches.

Used when the vector index is unavailable: not yet built, embedding model
changed, embedder missing, or a search failure occurred. Scores memories
against the query across content, memory_key, topics, and tags.
"""

from __future__ import annotations

import re
import unicodedata


def normalize_for_search(text: str) -> str:
    """NFKC + lower for search comparison; keeps spaces for tokenization."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    return text


def tokenize(text: str) -> list[str]:
    """Tokenize for fallback scoring.

    Splits on whitespace and punctuation, keeps Japanese word characters.
    Returns unique tokens (lower, NFKC) preserving order, filtered min length 1.
    """
    norm = normalize_for_search(text)
    # Replace common Japanese delimiters with space before extracting tokens.
    # The middle dot "・" (U+30FB) is within 0x30A0-0x30FF but is a separator, not a word char.
    norm = norm.replace("・", " ").replace("、", " ").replace("。", " ")
    norm = norm.replace(",", " ").replace("，", " ")
    # Use explicit ranges that exclude separators like "・", "、", "。"
    # Hiragana: 3040-309F, Katakana (without middle dot): 30A0-30FA + 30FC-30FF, Kanji: 4E00-9FFF
    tokens = re.findall(r"[a-zA-Z0-9_\u3040-\u309F\u30A0-\u30FA\u30FC-\u30FF\u4E00-\u9FFF]+", norm)
    seen: set[str] = set()
    out: list[str] = []
    for tok in tokens:
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    # If no tokens (e.g. only symbols), fallback to whole normalized string
    if not out and norm.strip():
        out = [norm.strip()]
    return out


def fallback_score(query: str, memory: dict) -> float:
    """Compute token-match score across content, memory_key, topics, tags.

    Scoring weights (higher = more relevant):
      - content substring (normalized query in normalized content): +3.0
      - content token overlap: +1.0 per matched token
      - memory_key token/ substring: +2.0 per matched token / +2.5 if exact substring
      - topics exact token match: +2.0 per topic
      - tags exact/partial match: +1.5 per tag
    """
    q_norm = normalize_for_search(query)
    q_tokens = tokenize(query)
    if not q_norm or not q_tokens:
        return 0.0

    score = 0.0

    content = memory.get("content") or ""
    c_norm = normalize_for_search(content)
    c_tokens = set(tokenize(content))

    # Content substring
    if q_norm.strip() and q_norm.strip() in c_norm:
        score += 3.0

    # Content token overlap
    for tok in q_tokens:
        if tok in c_tokens:
            score += 1.0
        elif tok in c_norm:
            # partial substring in content even if token boundary differs
            score += 0.5

    # memory_key
    mkey = (memory.get("memory_key") or "")
    mk_norm = normalize_for_search(mkey)
    mk_tokens = set(tokenize(mkey))
    if q_norm.strip() and q_norm.strip() in mk_norm and mk_norm:
        score += 2.5
    for tok in q_tokens:
        if tok in mk_tokens:
            score += 2.0
        elif tok in mk_norm and mk_norm:
            score += 0.8

    # topics
    topics = memory.get("topics") or []
    topics_norm = [normalize_for_search(t) for t in topics]
    topics_tokens = set()
    for t in topics_norm:
        topics_tokens.update(tokenize(t))
        # also consider whole normalized topic as token
        if t:
            topics_tokens.add(t)
    for tok in q_tokens:
        if tok in topics_tokens:
            score += 2.0

    # tags
    tags = memory.get("tags") or []
    tags_norm = [normalize_for_search(t) for t in tags]
    tags_tokens = set()
    for t in tags_norm:
        tags_tokens.update(tokenize(t))
        if t:
            tags_tokens.add(t)
    for tok in q_tokens:
        if tok in tags_tokens:
            score += 1.5
        elif any(tok in tn for tn in tags_norm if tn):
            score += 0.5

    return score
