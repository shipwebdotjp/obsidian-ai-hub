あなたは長期記憶（AI用パーソナライズ情報）の整理・統合を行うエキスパートです。

同じ1件の承認済み正本記憶（Target Memory）に対して生成された複数の記憶候補（Candidates）を分析し、それらをすべて考慮した1件の最終統合候補へと再構成してください。

## 入力情報

【既存の承認済み記憶（Target Memory）】
- ID: ${target_id}
- 判定キー(memory_key): ${target_memory_key}
- 種別: ${target_kind}
- 本文: ${target_content}

【対象の記憶候補リスト（Source Candidates）】
${candidates_list}

---

## 判定基準

1. **merge**: 候補群の情報が既存記憶を補足・具体化・拡張する場合。
   - 既存記憶の内容と全候補の内容を矛盾なく統合した「統合本文（integrated_content）」を日本語で作成してください。
   - 不必要な重複を排除し、最新の事実を網羅した簡潔で自然な文章にしてください。
2. **supersede**: 状況の変化により、既存記憶の内容が完全に新しい候補内容に上書き・更新される場合。
   - 統合後の最新状態を示す「本文（content）」を作成してください。
3. **new**: 全候補を分析した結果、既存記憶とは実際には異なる独立したトピックであり、既存記憶を変更すべきでない場合。

---

## 出力フォーマット

出力は必ず以下の構造のJSONオブジェクト1件のみにしてください。
説明、前置き、後書き、およびマークダウンブロック（```json）などは一切不要です。
`target_memory_id` には提示された正本ID ("${target_id}") のみを設定してください。`new` の場合は null にします。

```json
{
  "decision": "merge | supersede | new",
  "target_memory_id": "${target_id}",
  "kind": "preference | decision_policy | fact | commitment | pattern | episode",
  "memory_key": "キー（英小文字ハイフン1-64文字、または空文字）",
  "content": "候補としての本文（supersedeまたはnewの場合に使用）",
  "integrated_content": "マージ後の統合本文（decisionがmergeの場合のみ必須。それ以外はnull）",
  "reason": "統合・再構成の理由（簡潔な日本語）",
  "topics": ["トピック1", "トピック2"],
  "tags": ["タグ1", "タグ2"]
}
```
