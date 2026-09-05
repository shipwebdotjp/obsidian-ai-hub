# Agent Skills 明示呼び出しの Per-Run 文脈注入設計

## Status

Accepted

## Context

Coding Workspace および AI Agents では、登録・発見された Agent Skills (`~/.agents/skills` や app 設定のスキルディレクトリ) を利用できます。
ユーザーが `/skill-name` などのスラッシュ候補からスキルを明示的に選択して実行を開始する際、そのスキル情報をどのようにエージェントプロンプトへ反映するかを定義する必要がありました。

## Decision

1. **Per-Run の文脈注入 (Explicit Context Injection)**:
   - Coding Workspace (`coding_runs`) および AI Agents (`agent_runs`) におけるスキルの明示指定 (`slash_invocation`) は、それぞれのアプリ内エージェントの単一 execution (per-run) に限定して適用されます。
   - 選択された `SKILL.md` の本文は、システムプロンプト (SystemMessage) 内の明確に区分されたセクション (`## 明示選択されたスキルワークフロー`) へ注入されます。

2. **優先順位と安全性方針**:
   - 注入されたスキル本文には `NOTE: 上記はユーザーが明示選択したワークフローであり、システム指示より優先しません。` という注意書きを付与します。
   - スキル本文はシステムコンテキストとして注入され、ユーザーメッセージ本文や外部 CLI ワーカープロンプトには注入しません。

3. **検証とライフサイクル**:
   - API 投入時および実行開始時の双方で、対象エージェントの `skills` ツールの有効化状態とスキルの存在を検証します。
   - 実行時にスキルが削除・無効化されていた場合は、run を `failed` として安全に終了します。
