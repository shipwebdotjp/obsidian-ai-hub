import json
import logging
from datetime import datetime
from pathlib import Path
from AppKit import NSScreen

from obsidian_ai_hub.take_screenshot import capture_screen, get_unique_path
from obsidian_ai_hub.utils import accessibility, config, img2text, llm_client

logger = logging.getLogger(__name__)

ACTIVITY_CATEGORIES = [
    "開発",
    "調査・リサーチ",
    "事務・記録",
    "コミュニケーション",
    "インプット・読書",
    "創作・執筆",
    "学習",
    "趣味・休憩",
    "その他"
]

def normalize_ocr_results(ocr_results):
    """
    OCR結果のリストを受け取り、正規化する。
    - 空行を除去
    - 短すぎる断片（1文字以下）を除去
    - 完全重複を除去
    """
    normalized = []
    seen = set()
    for text, confidence in ocr_results:
        text = text.strip()
        if not text:
            continue
        if len(text) <= 1:
            continue
        if text in seen:
            continue

        normalized.append(text)
        seen.add(text)
    return normalized


def should_skip_activity_logging(app_name: str | None, window_title: str | None) -> bool:
    if app_name is None:
        return True

    normalized_app_name = str(app_name).strip()
    normalized_window_title = str(window_title).strip() if window_title else ""
    return (
        normalized_app_name == ""
        or normalized_app_name == "Unknown"
        or normalized_app_name.lower() == "loginwindow"
        or "プライベート" in normalized_window_title
    )


def main():
    # 1. 前面アプリ情報の取得
    try:
        window_info = accessibility.get_active_window_info()
    except Exception as e:
        logger.error(f"Failed to get active window info: {e}")
        window_info = {"app_name": "Unknown", "window_title": "Unknown"}

    if not isinstance(window_info, dict):
        logger.error("Invalid active window info payload. Falling back to Unknown values.")
        window_info = {}

    app_name = window_info.get("app_name", "Unknown")
    window_title = window_info.get("window_title", "Unknown")

    if should_skip_activity_logging(app_name, window_title):
        logger.debug("Skipping activity logging because active app is unavailable or locked.")
        return

    now = datetime.now()

    # 1.5 重複チェック: 直前の記録と同じアプリ・タイトルならスキップ
    activity_log_dir = config.ACTIVITY_PATH / now.strftime("%Y/%m")
    log_file = activity_log_dir / now.strftime("%Y-%m-%d.jsonl")
    if log_file.exists():
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                # 効率のため末尾から読み込む
                f.seek(0, 2)
                pos = f.tell()
                if pos > 0:
                    last_line = ""
                    # 改行を遡って一行分取得
                    buffer_size = 1024
                    while pos > 0 and not last_line.strip():
                        seek_pos = max(0, pos - buffer_size)
                        f.seek(seek_pos)
                        chunk = f.read(pos - seek_pos)
                        if "\n" in chunk:
                            last_line = chunk.rsplit("\n", 2)[-2] if chunk.endswith("\n") else chunk.rsplit("\n", 1)[-1]
                        else:
                            last_line = chunk
                        pos = seek_pos

                    if last_line.strip():
                        last_record = json.loads(last_line)
                        if (last_record.get("app_name") == app_name and
                            last_record.get("window_title") == window_title):
                            logger.info(f"Skipping duplicate activity: {app_name} - {window_title}")
                            return
        except Exception as e:
            logger.warning(f"Failed to read last activity log for duplication check: {e}")

    # 2. 各ディスプレイのスクリーンショット保存
    # YYYY/MM/DD
    date_path = now.strftime("%Y/%m/%d")
    screenshot_base_dir = config.SCREENSHOT_PATH

    save_dir = screenshot_base_dir / date_path
    save_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = now.strftime("%Y-%m-%d_%H-%M-%S")

    screens = NSScreen.screens()
    all_ocr_text = []
    screenshot_paths = []

    for i, screen in enumerate(screens):
        # macOS screencapture -D requires the CGDirectDisplayID
        description = screen.deviceDescription()
        display_id = description.objectForKey_("NSScreenNumber")

        # YYYY-MM-DD_HH-MM-SS_{DisplayID}_{連番}.png
        # 既存の get_unique_path を使うためにまずベースのファイル名を決める
        filename = f"{timestamp_str}_{display_id}.png"
        target_path = get_unique_path(save_dir, filename)

        try:
            capture_screen(target_path, display=display_id)
            screenshot_paths.append(str(target_path))

            # 3. OCR実行
            ocr_results = img2text.image_to_text(str(target_path))
            normalized_text = normalize_ocr_results(ocr_results)
            all_ocr_text.extend(normalized_text)
        except Exception as e:
            logger.error(f"Failed to process display {display_id}: {e}")
            # 他のディスプレイの処理を止めない

    # OCR結果の重複排除（複数ディスプレイ間）
    unique_ocr_text = list(dict.fromkeys(all_ocr_text))
    ocr_text_combined = "\n".join(unique_ocr_text)

    # 4. LLM要約
    # 「その時点で何をしていたか」を日本語で短く要約、およびカテゴリ分類
    categories_str = ", ".join(ACTIVITY_CATEGORIES)
    prompt = f"""以下の情報に基づき、ユーザーがその時点で何をしていたかを分析し、JSON形式で出力してください。

# 項目
- summary: 日本語で1文程度で短く要約
- category: 以下の候補から最も適切なものを1つだけ選択
  候補: {categories_str}
- keywords: 関連するキーワードのリスト（文字列の配列）

# 出力形式
{{
  "summary": "...",
  "category": "...",
  "keywords": ["...", "..."]
}}

# 情報
前面アプリ: {app_name}
ウィンドウタイトル: {window_title}
画面内のテキスト(OCR):
{ocr_text_combined}
"""

    summary = f"{app_name} での作業を検出しました。"
    category = "その他"
    keywords = []

    try:
        response = llm_client.generate_llm_response(
            provider=config.MAKE_TODAY_TARGET_PROVIDER,
            model=config.MAKE_TODAY_TARGET_MODEL,
            prompt=prompt,
            max_tokens=8192
        )
        # JSONパースの試行
        try:
            # Markdownのコードブロックを除去
            cleaned_response = response.strip()
            if cleaned_response.startswith("```"):
                lines = cleaned_response.splitlines()
                if lines[0].startswith("```json"):
                    cleaned_response = "\n".join(lines[1:-1])
                elif lines[0].startswith("```"):
                    cleaned_response = "\n".join(lines[1:-1])

            data = json.loads(cleaned_response)

            cand_summary = data.get("summary")
            if isinstance(cand_summary, str) and cand_summary.strip():
                summary = cand_summary.strip()

            cand_category = data.get("category")
            if cand_category in ACTIVITY_CATEGORIES:
                category = cand_category
            else:
                logger.warning(f"Invalid category from LLM: {cand_category}")

            cand_keywords = data.get("keywords")
            if isinstance(cand_keywords, list):
                keywords = [str(k).strip() for k in cand_keywords if k is not None and str(k).strip()]
            else:
                keywords = []

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            # パース失敗時は、response全体をsummaryとして使うか、デフォルト維持
            # ここでは最低限 response が空でなければ summary に入れてみる
            if response and not response.startswith("{"):
                summary = response.strip().split("\n")[0]

    except Exception as e:
        logger.error(f"LLM summarization failed: {e}")
        summary = f"{app_name} での作業を検出しました（要約に失敗しました）。"

    # 5. JSONL 追記
    # vault.activity/YYYY/MM/YYYY-MM-DD.jsonl
    activity_log_dir = config.ACTIVITY_PATH / now.strftime("%Y/%m")
    activity_log_dir.mkdir(parents=True, exist_ok=True)
    log_file = activity_log_dir / now.strftime("%Y-%m-%d.jsonl")

    record = {
        "timestamp": now.isoformat(),
        "app_name": app_name,
        "window_title": window_title,
        "summary": summary,
        "category": category,
        "keywords": keywords,
        "screenshots": screenshot_paths
    }

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info(f"Activity logged to {log_file}")
    except Exception as e:
        logger.error(f"Failed to write activity log: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
