import re
from collections import Counter
from typing import Any


def normalize_text_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
    else:
        normalized = str(value).strip()
    return normalized or None


def extract_numeric_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


def calculate_most_common_value(records: list[dict | None], key: str) -> str | None:
    counts = Counter()
    first_seen: dict[str, int] = {}

    for idx, record in enumerate(records):
        if not record:
            continue
        value = normalize_text_value(record.get(key))
        if not value:
            continue

        counts[value] += 1
        first_seen.setdefault(value, idx)

    if not counts:
        return None

    highest_count = max(counts.values())
    candidates = [value for value, count in counts.items() if count == highest_count]
    return min(candidates, key=lambda value: first_seen[value])


def calculate_average_numeric_value(records: list[dict | None], key: str) -> str | None:
    values = []

    for record in records:
        if not record:
            continue
        value = extract_numeric_value(record.get(key))
        if value is not None:
            values.append(value)

    if not values:
        return None

    average = sum(values) / len(values)
    return f"{average:.1f}"
