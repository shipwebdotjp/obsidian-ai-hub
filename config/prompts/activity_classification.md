以下の情報に基づき、ユーザーがその時点で何をしていたかを分析し、JSON形式で出力してください。

# 項目
- summary: 日本語で1文程度で短く要約
- category: 以下の候補から最も適切なものを1つだけ選択
  候補: ${categories_str}
- keywords: 関連するキーワードのリスト（文字列の配列）

# 出力形式
{
  "summary": "...",
  "category": "...",
  "keywords": ["...", "..."]
}

# 情報
前面アプリ: ${app_name}
ウィンドウタイトル: ${window_title}
画面内のテキスト(OCR):
${ocr_text_combined}
