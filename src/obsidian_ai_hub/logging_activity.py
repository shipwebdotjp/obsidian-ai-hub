import json
import logging
from datetime import datetime
from AppKit import NSScreen

from obsidian_ai_hub.take_screenshot import capture_screen, get_unique_path
from obsidian_ai_hub.utils import accessibility, config, img2text, llm_client, prompt
from obsidian_ai_hub.activity.categories import ACTIVITY_CATEGORIES
from obsidian_ai_hub.activity.store import add_activity, get_latest_activity_by_date
from obsidian_ai_hub.summary.project_utils import get_active_projects_for_prompt
from obsidian_ai_hub.activity.clipboard import get_sanitized_clipboard_text

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


def should_skip_activity_logging(
    app_name: str | None, window_title: str | None
) -> bool:
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
        logger.error(
            "Invalid active window info payload. Falling back to Unknown values."
        )
        window_info = {}

    app_name = window_info.get("app_name", "Unknown")
    window_title = window_info.get("window_title", "Unknown")

    if should_skip_activity_logging(app_name, window_title):
        logger.debug(
            "Skipping activity logging because active app is unavailable or locked."
        )
        return

    now = datetime.now()

    # 1.5 重複チェック: 直前の記録と同じアプリ・タイトルならスキップ
    try:
        activity_date_str = now.strftime("%Y-%m-%d")
        last_record = get_latest_activity_by_date(activity_date_str)
        if last_record:
            if (
                last_record.get("app_name") == app_name
                and last_record.get("window_title") == window_title
            ):
                logger.info(f"Skipping duplicate activity: {app_name} - {window_title}")
                return
    except Exception as e:
        logger.warning(f"Failed to fetch last activity log for duplication check: {e}")

    # 1.6 クリップボード文脈の取得（重複チェック通過後に1度だけ取得・マスキング処理）
    clipboard_text = get_sanitized_clipboard_text()

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

    for display_number, screen in enumerate(screens, start=1):
        # NSScreenNumber は macOS 内部の display ID だが、screencapture -D は 1 始まりの表示番号を要求する
        description = screen.deviceDescription()
        screen_number = description.objectForKey_("NSScreenNumber")

        # YYYY-MM-DD_HH-MM-SS_{DisplayNumber}_{連番}.png
        # 既存の get_unique_path を使うためにまずベースのファイル名を決める
        filename = f"{timestamp_str}_{display_number}.png"
        target_path = get_unique_path(save_dir, filename)

        try:
            capture_screen(target_path, display=display_number)
            screenshot_paths.append(str(target_path))

            # 3. OCR実行
            ocr_results = img2text.image_to_text(str(target_path))
            normalized_text = normalize_ocr_results(ocr_results)
            all_ocr_text.extend(normalized_text)
        except Exception as e:
            logger.error(
                f"Failed to process display {display_number} (NSScreenNumber={screen_number}): {e}"
            )
            # 他のディスプレイの処理を止めない

    # OCR結果の重複排除（複数ディスプレイ間）
    unique_ocr_text = list(dict.fromkeys(all_ocr_text))
    ocr_text_combined = "\n".join(unique_ocr_text)

    # 4. LLM要約
    # 「その時点で何をしていたか」を日本語で短く要約、およびカテゴリ分類
    categories_str = ", ".join(ACTIVITY_CATEGORIES)

    # Fetch active projects
    try:
        active_projects = get_active_projects_for_prompt()
    except Exception as e:
        logger.error(f"Failed to fetch active projects: {e}")
        active_projects = []

    if active_projects:
        projects_str = json.dumps(active_projects, ensure_ascii=False, indent=2)
    else:
        projects_str = "現在有効なプロジェクトはありません。"

    summary = f"{app_name} での作業を検出しました。"
    category = "その他"
    keywords = []
    project_id = None

    try:
        rendered_prompt = prompt.render_prompt(
            config.ACTIVITY_CLASSIFICATION_PROMPT_PATH,
            {
                "categories_str": categories_str,
                "app_name": app_name,
                "window_title": window_title,
                "ocr_text_combined": ocr_text_combined,
                "clipboard_text": clipboard_text,
                "projects_str": projects_str,
            },
        )
        response = llm_client.generate_llm_response(
            provider=config.MAKE_TODAY_TARGET_PROVIDER,
            model=config.MAKE_TODAY_TARGET_MODEL,
            prompt=rendered_prompt,
            max_tokens=16384,
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
                keywords = [
                    str(k).strip()
                    for k in cand_keywords
                    if k is not None and str(k).strip()
                ]
            else:
                keywords = []

            # Parse and validate project_id
            raw_project_id = data.get("project_id")
            valid_ids = {p["id"] for p in active_projects}
            if isinstance(raw_project_id, bool):
                # Booleans are not numbers
                pass
            elif isinstance(raw_project_id, (int, float)):
                if isinstance(raw_project_id, float) and not raw_project_id.is_integer():
                    pass  # reject non-integer floats
                else:
                    val = int(raw_project_id)
                    if val in valid_ids:
                        project_id = val
            elif isinstance(raw_project_id, str):
                if raw_project_id.strip().isdigit():
                    val = int(raw_project_id.strip())
                    if val in valid_ids:
                        project_id = val

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            # パース失敗時は、response全体をsummaryとして使うか、デフォルト維持
            # ここでは最低限 response が空でなければ summary に入れてみる
            if response and not response.startswith("{"):
                summary = response.strip().split("\n")[0]

    except Exception as e:
        logger.error(f"LLM summarization failed: {e}")
        summary = f"{app_name} での作業を検出しました（要約に失敗しました）。"

    # 5. SQLite 追記
    try:
        activity_date_str = now.strftime("%Y-%m-%d")
        occurred_at_str = now.isoformat()
        add_activity(
            activity_date=activity_date_str,
            occurred_at=occurred_at_str,
            app_name=app_name,
            window_title=window_title,
            summary=summary,
            category=category,
            keywords=keywords,
            screenshots=screenshot_paths,
            project_id=project_id,
        )
        logger.info("Activity logged to SQLite")
    except Exception as e:
        logger.error(f"Failed to write activity log to SQLite: {e}")
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
