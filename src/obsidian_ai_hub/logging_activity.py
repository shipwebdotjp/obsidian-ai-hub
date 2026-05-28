import json
import logging
from datetime import datetime
from pathlib import Path
from AppKit import NSScreen

from obsidian_ai_hub.take_screenshot import capture_screen, get_unique_path
from obsidian_ai_hub.utils import accessibility, config, img2text, llm_client

logger = logging.getLogger(__name__)

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

def main():
    # 1. 前面アプリ情報の取得
    try:
        window_info = accessibility.get_active_window_info()
    except Exception as e:
        logger.error(f"Failed to get active window info: {e}")
        window_info = {"app_name": "Unknown", "window_title": "Unknown"}

    app_name = window_info.get("app_name", "Unknown")
    window_title = window_info.get("window_title", "Unknown")

    # 2. 各ディスプレイのスクリーンショット保存
    now = datetime.now()
    # YYYY/MM/DD
    date_path = now.strftime("%Y/%m/%d")
    screenshot_base_dir = config.SCREENSHOT_DIR
    if not screenshot_base_dir:
        screenshot_base_dir = config.VAULT_PATH / "screenshots"

    save_dir = screenshot_base_dir / date_path
    save_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = now.strftime("%Y-%m-%d_%H-%M-%S")

    screens = NSScreen.screens()
    all_ocr_text = []
    screenshot_paths = []

    for i, screen in enumerate(screens):
        display_num = i + 1
        # YYYY-MM-DD_HH-MM-SS_{DisplayNumber}_{連番}.png
        # 既存の get_unique_path を使うためにまずベースのファイル名を決める
        filename = f"{timestamp_str}_{display_num}_1.png"
        target_path = get_unique_path(save_dir, filename)

        try:
            capture_screen(target_path, display=display_num)
            screenshot_paths.append(str(target_path))

            # 3. OCR実行
            ocr_results = img2text.image_to_text(str(target_path))
            normalized_text = normalize_ocr_results(ocr_results)
            all_ocr_text.extend(normalized_text)
        except Exception as e:
            logger.error(f"Failed to process display {display_num}: {e}")
            # 他のディスプレイの処理を止めない

    # OCR結果の重複排除（複数ディスプレイ間）
    unique_ocr_text = list(dict.fromkeys(all_ocr_text))
    ocr_text_combined = "\n".join(unique_ocr_text)

    # 4. LLM要約
    # 「その時点で何をしていたか」を日本語で短く要約
    prompt = f"""以下の情報に基づき、ユーザーがその時点で何をしていたか、日本語で1文程度で短く要約してください。
前面アプリ: {app_name}
ウィンドウタイトル: {window_title}
画面内のテキスト(OCR):
{ocr_text_combined}
"""

    summary = "No activity detected."
    if ocr_text_combined or app_name != "Unknown":
        try:
            summary = llm_client.generate_llm_response(
                provider=config.MAKE_TODAY_TARGET_PROVIDER,
                model=config.MAKE_TODAY_TARGET_MODEL,
                prompt=prompt,
                max_tokens=100
            )
        except Exception as e:
            logger.error(f"LLM summarization failed: {e}")
            summary = f"Activity in {app_name} (Summarization failed)"

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
