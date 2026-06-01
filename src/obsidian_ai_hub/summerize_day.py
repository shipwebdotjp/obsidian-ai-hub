import json
import logging
from datetime import datetime, timedelta
from obsidian_ai_hub.utils import config, reader, extracter, llm_client
from pathlib import Path

logger = logging.getLogger(__name__)

TOPIC_ENUM = [
    "LLM・AI活用", "AI・機械学習", "ソフトウェア開発", "開発環境・DevOps",
    "データ・分析", "クラウド・インフラ", "ツール・自動化（生産性）",
    "リサーチ手法・情報整理（PKM）", "ガジェット・デバイス", "金融・投資",
    "マーケティング・発信", "ライティング・コンテンツ制作", "コミュニケーション・対人関係",
    "思考法・判断力", "学習・教育", "自己改善（習慣・時間管理）", "メンタル・心理",
    "健康・医療", "生活・暮らし", "信仰・聖書", "その他"
]

INTENT_ENUM = [
    "理解・質問応答", "要約・整理", "調査・比較", "意思決定支援", "設計・構成検討",
    "計画・タスク化", "文章生成・編集", "コード作成・レビュー", "問題解決・トラブル対応",
    "翻訳・ローカライズ", "メタ検討", "その他"
]

PROMPT = """
あなたは日次ログ要約器です。以下の「今日のデイリーノート」、「セッション要約一覧（JSON）」、「アクティビティログ(JSONL)」だけを根拠に、日本語でその日の要約を書いてください。

要約:
-  500文字以内
-  ユーザー視点で「今日やったこと/考えたこと」と「分かったこと（学び/整理）」を含める
-  topics を踏まえ、その日の関心の軸を1フレーズで示す（例：「関心は主に〜に寄っていた」）
-  根拠は metadata.summary を最優先し、topics/intent/title/keywords は補助に使う
-  入力にない事実（具体策・数値・固有名詞・出来事）を推測で補わない。不明な点は「〜の可能性」「〜かもしれない」と書く

今日のデイリーノート:
{DAILY_NOTE_CONTENT}

セッション要約一覧:
{SESSION_SUMMARIES}

アクティビティログ(JSONL):
{ACTIVITY_LOGS}
"""


def get_daily_ai_summary(target_date: datetime, daily_content: str) -> str:
    """
    指定された日付のAIログから metadata を抽出し、LLMで要約を生成。
    結果をファイルに追記。
    """
    logs = load_conversation_logs(config.AI_LOG_PATH, target_date)
    activity_logs = load_activity_logs(target_date)

    # LLM入力用に、全 metadata を配列として連結した文字列を生成
    # → 個別にLLMかける or 全体をまとめたJSONとして渡す（ここでは全件まとめて）
    metadata_combined = json.dumps(
        logs,
        ensure_ascii=False,
        indent=2
    )

    activity_combined = json.dumps(
        activity_logs,
        ensure_ascii=False,
        indent=2
    )

    # PROMPT を更新して実行
    prompt = (
        PROMPT.replace("{SESSION_SUMMARIES}", metadata_combined)
        .replace("{ACTIVITY_LOGS}", activity_combined)
        .replace("{DAILY_NOTE_CONTENT}", daily_content)
    )

    # return "エラー発生: LLM呼び出し失敗"  # デバッグのため一旦LLM呼び出しを停止
    try:
        response_text = llm_client.generate_llm_response(
            provider=config.MAKE_TODAY_TARGET_PROVIDER,
            model=config.MAKE_TODAY_TARGET_MODEL,
            prompt=prompt,
            max_tokens=8120,
        ).strip()
        return response_text

    except Exception as e:
        logger.exception("Failed to generate daily AI summary")
        return f"エラー発生: {type(e).__name__}"


STRUCTURED_PROMPT = """
あなたは日次ログ構造化器です。以下の「今日のデイリーノート」、「セッション要約一覧（JSON）」、「アクティビティログ(JSONL)」を元に、その日の活動を構造化されたJSON形式で出力してください。

# 項目定義
- summary: その日の短い全体像（1文）
- topics: 関心領域のまとまり（文字列の配列）
- activities: 主な作業内容（文字列の配列）
- learnings: 学び・整理できたこと（文字列の配列）
- reflections: 反省点・気づき（文字列の配列）
- gratitude: 感謝したこと（文字列の配列）
- people: 人物メモ。 `{"name": "...", "note": "..."}` の配列。見つからなければ空配列
- questions: 未解決の問い（文字列の配列）
- keywords: 後で検索しやすい語（文字列の配列）
- next_actions: 翌日以降の具体的な次手（文字列の配列）

# 出力形式
必ず以下のJSON形式のみを出力してください。余計な解説は不要です。
{
  "summary": "...",
  "topics": [],
  "activities": [],
  "learnings": [],
  "reflections": [],
  "gratitude": [],
  "people": [{"name": "...", "note": "..."}],
  "questions": [],
  "keywords": [],
  "next_actions": []
}

今日のデイリーノート:
{DAILY_NOTE_CONTENT}

セッション要約一覧:
{SESSION_SUMMARIES}

アクティビティログ(JSONL):
{ACTIVITY_LOGS}
"""


def get_daily_structured_record(
    target_date: datetime,
    daily_content: str,
    logs: list[dict],
    activity_logs: list[dict]
) -> dict:
    """
    指定された日付の情報を構造化データとして生成。
    """
    date_str = target_date.strftime("%Y-%m-%d")
    generated_at = datetime.now().isoformat()

    # source_stats 計算
    daily_file = reader.get_daily_note_path(target_date)
    source_stats = {
        "activity_count": len(activity_logs),
        "llm_session_count": len(logs),
        "has_daily_note": daily_file.exists()
    }

    # frontmatter から mood/sleep 取得
    mood = extracter.get_frontmatter_value(daily_content, "mood", default=None)
    sleep = extracter.get_frontmatter_value(daily_content, "sleep", default=None)

    prompt = (
        STRUCTURED_PROMPT.replace("{SESSION_SUMMARIES}", json.dumps(logs, ensure_ascii=False, indent=2))
        .replace("{ACTIVITY_LOGS}", json.dumps(activity_logs, ensure_ascii=False, indent=2))
        .replace("{DAILY_NOTE_CONTENT}", daily_content)
    )

    # 最小レコード（フォールバック用）
    record = {
        "schema_version": 1,
        "date": date_str,
        "generated_at": generated_at,
        "summary": "",
        "topics": [],
        "activities": [],
        "learnings": [],
        "reflections": [],
        "gratitude": [],
        "people": [],
        "questions": [],
        "keywords": [],
        "next_actions": [],
        "mood": mood,
        "sleep": sleep,
        "source_stats": source_stats
    }

    try:
        response = llm_client.generate_llm_response(
            provider=config.MAKE_TODAY_TARGET_PROVIDER,
            model=config.MAKE_TODAY_TARGET_MODEL,
            prompt=prompt,
            max_tokens=8120,
        )

        # JSONパース
        cleaned_response = response.strip()
        if cleaned_response.startswith("```"):
            lines = cleaned_response.splitlines()
            if len(lines) >= 2:
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    cleaned_response = "\n".join(lines[1:-1])

        data = json.loads(cleaned_response)

        # 抽出したデータを record にマージ
        for key in [
            "summary", "topics", "activities", "learnings", "reflections",
            "gratitude", "people", "questions", "keywords", "next_actions"
        ]:
            if key in data:
                val = data[key]
                # 文字列未確定項目は空配列またはnull
                if val is None:
                    continue

                # people の正規化
                if key == "people" and isinstance(val, list):
                    normalized_people = []
                    for p in val:
                        if isinstance(p, dict) and "name" in p:
                            normalized_people.append({
                                "name": str(p.get("name", "")),
                                "note": str(p.get("note", ""))
                            })
                    record["people"] = normalized_people
                elif isinstance(val, (str, list)):
                    record[key] = val

    except Exception as e:
        logger.error(f"Failed to generate or parse structured daily record: {e}")

    return record


def upsert_monthly_record(target_date: datetime, record: dict):
    """
    月次JSONLにレコードをupsertする。
    """
    monthly_log_dir = Path(config.ACTIVITY_PATH) / target_date.strftime("%Y/%m")
    monthly_log_dir.mkdir(parents=True, exist_ok=True)
    log_file = monthly_log_dir / target_date.strftime("%Y-%m.jsonl")

    records = {}
    if log_file.exists():
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if "date" in data:
                        records[data["date"]] = data
                except json.JSONDecodeError:
                    continue

    # upsert
    records[record["date"]] = record

    # 保存（date昇順）
    sorted_dates = sorted(records.keys())
    try:
        with open(log_file, "w", encoding="utf-8") as f:
            for d in sorted_dates:
                f.write(json.dumps(records[d], ensure_ascii=False) + "\n")
        logger.info(f"Monthly record upserted to {log_file}")
    except Exception as e:
        logger.error(f"Failed to write monthly record: {e}")


def load_activity_logs(target_date: datetime) -> list[dict]:
    activity_log_file = Path(config.ACTIVITY_PATH) / target_date.strftime("%Y/%m") / target_date.strftime("%Y-%m-%d.jsonl")
    logs = []
    if not activity_log_file.exists():
        return logs

    with open(activity_log_file, "r", encoding="utf-8") as f:
        for line in f:
            try:
                data = json.loads(line)
                # Coalesce None to defaults
                category = data.get("category")
                if category is None:
                    category = "その他"

                keywords = data.get("keywords")
                if keywords is None:
                    keywords = []

                logs.append({
                    "timestamp": data.get("timestamp"),
                    "app_name": data.get("app_name"),
                    "window_title": data.get("window_title"),
                    "summary": data.get("summary"),
                    "category": category,
                    "keywords": keywords
                })
            except json.JSONDecodeError:
                logger.error("Error decoding JSON from activity log file")
    return logs


def load_conversation_logs(log_file_dir: str, target_date: datetime) -> list[dict]:
    logs = []
    date_str = target_date.strftime('%Y%m%d')
    log_dir = Path(log_file_dir)
    for file in log_dir.glob(f'*@{date_str}*.json'):
        with open(file, "r", encoding="utf-8") as f:
            try:
                log = json.load(f)
                logs.append(log)
            except json.JSONDecodeError:
                logger.error("Error decoding JSON from log file")

    return logs


def main():
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    logger.info("Summarizing day: %s", yesterday.date())

    daily_file = reader.get_daily_note_path(yesterday)
    content_yesterday = reader.get_daily_note_content(yesterday)

    # 1. 人間用要約の生成と追記
    content_to_add = get_daily_ai_summary(yesterday, content_yesterday)
    if not content_to_add.startswith("エラー発生"):
        extracter.append_to_subheader_file(daily_file.as_posix(), "## AIによる要約", [content_to_add])
    else:
        logger.error(f"Failed to generate human summary: {content_to_add}")

    # 2. 構造化レコードの生成と月次JSONLへのupsert
    logs = load_conversation_logs(config.AI_LOG_PATH, yesterday)
    activity_logs = load_activity_logs(yesterday)
    structured_record = get_daily_structured_record(yesterday, content_yesterday, logs, activity_logs)
    upsert_monthly_record(yesterday, structured_record)


if __name__ == "__main__":
    main()
