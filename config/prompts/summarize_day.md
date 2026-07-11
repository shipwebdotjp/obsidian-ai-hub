あなたは日次ログ構造化器です。以下の「今日のデイリーノート」、「セッション要約一覧（JSON）」、「アクティビティログ(JSONL)」を元に、その日の活動を構造化されたJSON形式で出力してください。

# 項目定義
- summary: その日の短い全体像（1文）
- topics: 関心領域のまとまり（文字列の配列）。必ず以下の候補リストからのみ選択してください。最大5件まで、重複なく選んでください。独自のラベルや表記ゆれは禁止します。該当なしは空配列（[]）にしてください。
  【候補リスト】
  ${TOPIC_CANDIDATES}
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
${DAILY_NOTE_CONTENT}

セッション要約一覧:
${SESSION_SUMMARIES}

アクティビティログ(JSONL):
${ACTIVITY_LOGS}
