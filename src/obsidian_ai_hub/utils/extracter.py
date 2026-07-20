from __future__ import annotations
import re
from typing import Any, Optional

import yaml


def get_subheader_view(note: str, subheader: str) -> str:
    """
    Get the content under a specific subheader from a note.
    """
    subheader_pattern = re.compile(
        rf"^{re.escape(subheader)}\n(.*?)(?=\n## |\Z)", re.MULTILINE | re.DOTALL
    )
    match = subheader_pattern.search(note)
    return match.group(1).strip() if match else ""


def append_to_subheader(content: str, subheader: str, new_lines: list[str]) -> str:
    lines = content.splitlines()
    header_pattern = re.compile(r"^#{1,6}\s")

    insert_pos = None
    in_target = False

    for i, line in enumerate(lines):
        if line.strip() == subheader.strip():
            in_target = True
            continue

        if in_target:
            # 次のヘッダーが来たらそこが挿入位置
            if header_pattern.match(line):
                insert_pos = i
                break
    else:
        # ファイル末尾まで次ヘッダーがない場合
        if in_target:
            insert_pos = len(lines)

    if insert_pos is None:
        tail = ["", subheader] + new_lines
        return "\n".join(lines + tail) + "\n"

    # 末尾の空行の手前に挿入（自然な見た目を保つ）
    actual_insert = insert_pos
    while actual_insert > 0 and lines[actual_insert - 1].strip() == "":
        actual_insert -= 1

    for j, new_line in enumerate(new_lines):
        lines.insert(actual_insert + j, new_line)

    return "\n".join(lines) + "\n"


def append_to_subheader_file(
    filepath: str, subheader: str, new_lines: list[str]
) -> None:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    updated = append_to_subheader(content, subheader, new_lines)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(updated)


def _extract_frontmatter_block(text: str) -> Optional[str]:
    """
    Obsidian/Markdownの先頭にあるYAMLフロントマター（--- ... ---）を抽出して返す。
    見つからなければ None。
    """
    lines = text.splitlines()

    if not lines:
        return None

    # UTF-8 BOMなどを雑に吸収（必要ならより厳密に）
    first = lines[0].lstrip("\ufeff")

    if first.strip() != "---":
        return None

    # 2行目以降で閉じの --- を探す
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return None

    return "\n".join(lines[1:end_idx])


def parse_frontmatter(text: str) -> dict[str, Any]:
    """
    フロントマターをdictとして返す。無ければ空dict。
    """
    block = _extract_frontmatter_block(text)
    if block is None:
        return {}

    data = yaml.safe_load(block)
    if data is None:
        return {}

    if not isinstance(data, dict):
        raise ValueError("Frontmatter YAML is not a mapping/dict.")

    return data


def get_frontmatter_value(
    text: str,
    key: str,
    default: Any = None,
    *,
    dotpath: bool = True,
) -> Any:
    """
    keyで指定した値を返す。
    dotpath=Trueなら "a.b.c" のようなネスト指定に対応。
    """
    fm = parse_frontmatter(text)

    if not dotpath or "." not in key:
        return fm.get(key, default)

    cur: Any = fm
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur
