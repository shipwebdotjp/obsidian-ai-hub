---
sidebar_position: 13
title: 長期目標コーチ
---

# 長期目標コーチ (Long-term Coach)

**長期目標コーチ** 画面（`/coach`）は、数か月〜年単位の大きな目標（Goal）を見失わず、今週の焦点（Focus）と週次 Reflection（振り返り）を通じて継続的に前進を支援する機能です。

Phase 1 では、手動の構造化フォームによる週次 Reflection に特化し、ユーザー自身の入力を正本として扱います。

---

## 主な概念

| 概念 | 説明 |
| --- | --- |
| **Goal (長期目標)** | ユーザーが選ぶ望ましい方向・到達像 (`statement`) とその理由 (`reason`)。状態は `active` / `paused` / `ended`。 |
| **Focus (焦点)** | Goal に結びつく数週間単位の具体的な取り組み。Goal ごとに現在扱う Focus は `active` 最大1つ。 |
| **Weekly Reflection** | ISO週月曜日ごとの振り返り。取り組み、難しさ、気づき、次週の範囲、決定種別 (`decision_type`) を記録。 |
| **Coach Thread** | Goal/Focus の作成・選択・休止・改称・Reflection を時系列で保持する不変の経緯ログ。本文は最新の内容が表示され、決定・選択は記録時点のまま残る。 |

---

## 使い方

### 1. Goal (長期目標) の作成

1. `/coach` 画面の **「新しい Goal を作成」** ボタンを押します。
2. **目標・到達像 (statement)** と **理由・動機 (reason)** を入力します。
3. 最初の Focus 候補を1つ以上入力します（1つ目の候補が自動的に `active` になります）。

### 2. Focus の管理と切替

Goal 詳細画面 (`/coach/goals/:goalId`) では、Focus 候補の追加・編集・アクティブ化・休止を行えます。

- **候補を追加**: 新しい Focus 候補をいつでも追加できます。
- **手動選択 (Active)**: 別の Focus を選択すると、それまで `active` だった Focus は自動的に `candidate` に戻り、新しい Focus が `active` になります。

### 3. 週次 Reflection (振り返り) の記録

1. Goal 詳細画面の **「週次 Reflection を記録」** ボタンを押します。
2. **対象 Focus** を選択します。現在のアクティブ Focus だけでなく、過去に扱った Focus（候補・休止中を含む）についても記録でき、未記録の過去週を後から追記できます。
3. 対象週（ISO週の月曜日日付）を選択します（過去週から今週まで選択可能。未来週は選択・登録不可）。
4. 振り返り項目を入力し、次週の決定種別 (`decision_type`) を選択します：
   - **継続 (continue)**: 現在の Focus をそのまま継続。
   - **小さくする (narrow)**: Focus を維持し、「次週の範囲 (`next_week_scope`)」を必須入力として小さく絞る。
   - **切替 (change)**: 同一 Goal の別 Focus 候補を選択し、アクティブ Focus を切り替える。
   - **休止 (pause)**: 現在の Focus を休止状態 (`paused`) にする。

:::note[切替・休止の反映条件]
切替・休止による Focus の状態変更は、その Goal で**最新の週**を記録するときに反映されます。過去週の追記は履歴として保存され、現在のアクティブ Focus は変わりません。
:::

:::note[Reflection の編集]
登録済みの Reflection の本文（出来事、難しさ、気づき、次週の範囲）は後から自由に編集できます。Coach Thread には最新の本文が表示されます。ただし、選択した週・Focus・決定種別・切替先 Focus は変更できず、Coach Thread の履歴として保持されます。
:::

---

## 非対象事項（Phase 1 で扱わないこと）

- LLM による自動生成・回答提案・自動サマリ作成は行いません。
- カレンダー、リマインダー、外部通知、LINE 送信、自動 Scheduler は接続しません。
- 既存の Project、Task、Vault ノート、活動ログ、ヘルスケアデータは参照・書込みしません。
- 達成率採点、連続記録 (`streak`)、未達の催促などプレッシャーを与える仕組みは導入しません。

---

## 次に読む

- [プロジェクト管理](projects.md)
- [Task Agent](task-agent.md)
