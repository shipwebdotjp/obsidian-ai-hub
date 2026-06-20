import json
import logging
import re
from pathlib import Path
from obsidian_ai_hub import take_screenshot
from obsidian_ai_hub.utils import accessibility, config, img2text, llm_client, prompt

logger = logging.getLogger(__name__)

def parse_json_response(response_text: str) -> dict:
    """
    LLM のレスポンスから JSON 部分を抽出してパースする。
    Markdown コードブロックの除去などを試みる。
    """
    # Remove markdown code blocks if present
    cleaned = re.sub(r"```(?:json)?\s*(.*?)\s*```", r"\1", response_text, flags=re.DOTALL).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}. Original text: {response_text}")
        # Try to find something that looks like a JSON object
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Invalid JSON response from LLM: {response_text}")

def scan_line_inbox():
    """
    LINE ウィンドウを検出し、スクリーンショットを撮り、LLM で解析する。
    """
    provider = config.LINE_INBOX_SCAN_PROVIDER
    model = config.LINE_INBOX_SCAN_MODEL

    if provider == "local":
        raise RuntimeError("Provider 'local' does not support multimodal (image) input.")

    # 1. LINE ウィンドウ検出
    line_window = accessibility.get_line_window()
    # アクセシビリティAPIから取得できた生の情報をデバッグ出力
    if not line_window:
        logger.warning("LINE window not found.")
        return {
            "window_id": None,
            "window_title": None,
            "screenshot_path": None,
            "candidates": [],
            "error": "LINE window not found"
        }

    window_id = line_window["window_id"]
    window_title = line_window.get("window_title")

    # 2. キャプチャ
    # 一時的なパスに保存するか、inboxに保存するか。take_screenshot.main は inbox に保存する。
    screenshot_path_str = take_screenshot.main(window_id=window_id)
    screenshot_path = Path(screenshot_path_str)

    # 3. OCR実行
    ocr_results = img2text.image_to_text(str(screenshot_path))
    ocr_text_combined = json.dumps(ocr_results, ensure_ascii=False, indent=2)
    rendered_prompt = prompt.render_prompt(
        config.LINE_INBOX_SCAN_PROMPT_PATH,
        {"OCR_TEXT": ocr_text_combined}
    )

    # 3. LLM 呼び出し
    logger.info(f"Calling LLM ({provider}/{model}) to scan LINE inbox...")
    response_text = llm_client.generate_llm_response(
        provider=provider,
        model=model,
        prompt=rendered_prompt,
        files=[screenshot_path],
        max_tokens=8192,
        temperature=0.0
    )

    # 4. パース
    try:
        data = parse_json_response(response_text)
    except ValueError as e:
        logger.error(f"Error parsing LLM response: {e}")
        return {
            "window_id": window_id,
            "window_title": window_title,
            "screenshot_path": str(screenshot_path),
            "candidates": [],
            "error": "Failed to parse LLM response"
        }

    result = {
        "window_id": window_id,
        "window_title": window_title,
        "screenshot_path": str(screenshot_path),
        "candidates": data.get("candidates", [])
    }
    return result

def main():
    try:
        result = scan_line_inbox()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    except Exception as e:
        error_result = {"error": str(e)}
        print(json.dumps(error_result, ensure_ascii=False, indent=2))
        return error_result

if __name__ == "__main__":
    main()
