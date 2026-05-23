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
あなたは日次ログ要約器です。以下の「今日のデイリーノート」、「セッション要約一覧（JSON）」だけを根拠に、日本語でその日の要約を書いてください。

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
"""


def get_daily_ai_summary(daily_content: str) -> str:
    """
    指定された日付のAIログから metadata を抽出し、LLMで要約を生成。
    結果をファイルに追記。
    """
    logs = load_conversation_logs(config.AI_LOG_PATH)
    
    
    # LLM入力用に、全 metadata を配列として連結した文字列を生成
    # → 個別にLLMかける or 全体をまとめたJSONとして渡す（ここでは全件まとめて）
    metadata_combined = json.dumps(
        logs,
        ensure_ascii=False,
        indent=2
    )

    # PROMPT を更新して実行
    prompt = PROMPT.replace("{SESSION_SUMMARIES}", metadata_combined).replace("{DAILY_NOTE_CONTENT}", daily_content)  # プレースホルダを置換

    # return "エラー発生: LLM呼び出し失敗"  # デバッグのため一旦LLM呼び出しを停止
    try:
        response_text = llm_client.generate_llm_response(
            provider="ollama",
            model="gemma4:e4b",
            prompt=prompt,
            max_tokens=8120,
        ).strip()
        return response_text

    except Exception as e:
        logger.exception("Failed to generate daily AI summary")
        return f"エラー発生: {type(e).__name__}"
    
def load_conversation_logs(log_file_dir: str) -> list[dict]:
    logs = []
    date = datetime.now() - timedelta(days=1)  # 昨日の日付を取得
    date_str = date.strftime('%Y%m%d')
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
    content_to_add = get_daily_ai_summary(content_yesterday)
    if content_to_add.startswith("エラー発生"):
        print(content_to_add)
        return

    # print(f"Daily note path: {daily_file}")
    # print(f"Content to add:\n{content_to_add}")
    extracter.append_to_subheader_file(daily_file.as_posix(), "## AIによる要約", [content_to_add])

if __name__ == "__main__":
    main()
