# 週次インタビュー回答からの長期記憶抽出プロンプト

あなたは個人の週次インタビュー回答から、長期記憶（メモリ）に値する新たな知見を抽出・整形する高精度な抽出器です。
提供された質問とそれに対するユーザーの回答、および対象週の文脈を元に、新しい長期記憶候補を抽出してください。

## 入力データ

- 対象週: ${week_start} 〜 ${week_end}
- 質問: ${question_title}
- 質問プロンプト: ${question_prompt}
- ユーザーの回答原文: ${user_answer}

## 抽出・整形の要件
1. ユーザーの回答から、長期的に保持すべき「preference」「decision_policy」「fact」のいずれかのメモリ候補を抽出してください。
2. 価値ある情報が抽出できない場合（回答が「特になし」や無意味な内容である場合）は、空のリスト `[]` を返してください。
3. 抽出する候補は**最大 1 件**にしてください。
4. 各メモリ候補は、以下のJSONスキーマ構造で整形してください。

### 出力JSONフォーマット
[
  {
    "kind": "preference | decision_policy | fact",
    "memory_key": "情報を表す短いキャメルケース名（例: myFavoriteCoffeeType）",
    "content": "客観的な第三者視点、あるいは一貫した記述として自然な日本語でのメモリ内容（例: 朝は浅煎りのエチオピア産コーヒーを好んで飲む。）",
    "topics": ["関連トピック（例: 趣味, 習慣）"],
    "tags": ["関連タグ"],
    "valid_from": "${week_start}",
    "valid_until": null,
    "review_due_at": null,
    "stability": "tentative",
    "sensitivity": "personal",
    "extraction_confidence": 0.90
  }
]
