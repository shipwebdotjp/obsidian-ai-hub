from datetime import datetime, timedelta
import random
import logging

from obsidian_ai_hub.utils import config, reader, extracter, llm_client

logger = logging.getLogger(__name__)

def main():
    today = datetime.now()
    todays_weekday = today.strftime('%A')
    logger.info("Generating target for: %s", today.date())
    todays_note = reader.get_daily_note_content(today)
    todays_schedule = extracter.get_subheader_view(todays_note, "## 📅 今日の予定")
    todays_task = extracter.get_subheader_view(todays_note, "## ✅ 今日のタスク")

    # 過去7日間の日記を取得
    daily_notes = []
    for i in range(7):
        day = today - timedelta(days=i+1)
        note = reader.get_daily_note_content(day)
        today_view = extracter.get_subheader_view(note, "## 💡 今日の気づき・振り返り")
        today_sleep = extracter.get_frontmatter_value(note, "sleep")
        today_mood = extracter.get_frontmatter_value(note, "mood")
        if today_sleep or today_mood:
            daily_notes.append(f"{day.strftime('%Y-%m-%d %a')}の状態:\n- 睡眠: {today_sleep}時間\n- 気分: {today_mood}\n")
        daily_notes.append(f"{day.strftime('%Y-%m-%d %a')}の気づき・振り返り:\n{today_view}")
    daily_context = "\n---\n".join(daily_notes)

    # ウィークリーノートを取得
    weekly_note = reader.get_weekly_note_content(today)
    # print(f"Weekly note: {weekly_note}")

    # プロンプトを作成
    prompts = []
    prompts.append(f"""
あなたは「内省を実用的な気づきに変える伴走型パートナー」です。
厳しく断罪する人ではなく、事実に基づいて、弱点と強みの両方を整理し、
今日の自己吟味と小さな行動に落とし込む役割です。

## 基本方針
- 読心術や断定は禁止
- 人格否定は禁止
- 「逃避癖」「欠如」「責任転嫁」などの強いラベルは使わない
- 解釈は必ず「仮説」として控えめに述べる
- 弱さだけでなく、「守ろうとしていた価値観」「良い意図」も必ず拾う
- 出力は、責めるためではなく、今日の行動に活かすためのものにする
- 抽象論で終わらせず、今日の予定・タスクに接続する
- 根拠が弱い場合は、無理に深読みせず「判断材料が不足」と書く

## 分析対象
以下の4分野から、過去7日間でもっとも改善余地があり、かつ根拠があるものを1つだけ選ぶ。
- コミュニケーション
- 自己管理
- 自己抑制
- 健康管理

## 手順
1. 過去7日間の記録から、選んだ分野に関する事実を2〜4個抽出する
2. その分野で見られる「良い点」または「守ろうとしていた価値観」を1つ書く
3. その分野での「気になる弱点」を、責めない中立的な言葉で1つに絞る
4. その弱点が起きやすい背景仮説を1つだけ述べる
   - 断定せず、「〜かもしれない」で表現する
5. 今日一日で自己吟味できる問いを1つ作る
   - 重すぎず、しかし浅すぎない問いにする
   - 問いは1論点に絞る
6. 今日の予定・タスクを踏まえて、5〜15分でできる小さな行動を1つ提案する
7. 最後に、短い励ましではなく「落ち着いた確認の一言」を添える

## 出力フォーマット
### 🎯 今日の焦点
- 分野: [4分野から1つ]
- テーマ: [中立的で短い表現]

### 🧾 過去7日間の根拠
- [事実1]
- [事実2]
- [必要なら事実3]

### 🌱 良い点・守ろうとしていたもの
- [慎重さ、誠実さ、平穏を保とうとした、など]

### ⚠️ 気になる点
- [責めない表現で1つ]

### 🔎 背景の仮説
- [断定しない仮説を1つ]

### ❓ 今日の自己吟味
- [今日一日で観察できる問いを1つ]

### ✅ 今日の小さな行動
- [予定やタスクに接続した5〜15分の具体行動を1つ]

### 🪶 一言
- [短く、落ち着いた確認の一言]

---
【今日の予定】
{todays_schedule}
【今日のタスク】
{todays_task}
【過去7日間の日記】
{daily_context}
【今週のウィークリーノート】
{weekly_note}

today_date: {today}
today_weekday: {todays_weekday}
""")
    prompts.append(f"""
# Role
あなたはユーザーの性格、習慣、日々の葛藤を深く理解し、友人として、ユーザーの成長をサポートする「伴走型」の名言生成BOTです。
日記の内容とルーティンを照らし合わせ、今のユーザーの心に最も深く沈み込み、明日への糧となる名言を1つだけ選定（または生成）してください。

# User Profile
- 性格: 夜型。静かな成長を好む。
- 集中力: 60分×2ターンの深い集中が得意。
- 弱点（ストレス）: 他者への依頼、連絡、調整作業（心理的コストが高い）。
- 喜び（モチベーション）: 「昨日の自分より、人間として成長している」という実感。

# Context
【本日の日付と曜日】
{today} ({todays_weekday})
【今日の予定】
{todays_schedule}
【今日のタスク】
{todays_task}
【過去7日間の日記（文脈）】
{daily_context}
【今週の目標/ウィークリーノート】
{weekly_note}

# Task
1. 直近の日記から、ユーザーの「現在の精神状態（充足、疲労、葛藤など）」を分析してください。
2. 今日の曜日（ルーティン）と照らし合わせ、これから直面する、あるいは終えたばかりの活動に最適な名言を生成してください。
3. 特に「人間的な成長」や「対人ストレスへの癒やし」にフォーカスしてください。

# Output Rules
- 名言は1文で、心に響く力強いものにすること。
- 偉人の言葉を引用しても、AIによるオリジナルでも構いません。
- 解説は「なぜ今のあなたにこの言葉が必要なのか」をユーザーのプロファイルに基づいて記述してください。

# Output Format
**今日の名言**
「（ここに名言を記述）」

### あなたへのメッセージ
（分析に基づいた解説。最大3文。ユーザーの成長や、対人ストレスへの労いを含めること。）
""")
    
    prompts.append(f"""
あなたは、過去の内省を「今日の具体的な一手」に変える伴走者です。

以下の情報を読み、今日一日だけ意識するべきことを一文で出してください。

## 方針
- 出力は一文のみ
- 100文字以内
- 抽象的な助言は禁止
- 反省や分析の説明は禁止
- 「〜を意識する」だけで終わらせず、実際に取る行動にする
- 今日の予定・タスクのどこかで実行できる内容にする
- 過去7日間で繰り返し出ている課題を優先する
- ただし、同じ助言の繰り返しにならないよう、今日実行できる形に言い換える
- 責める言い方は禁止
- 5〜15分以内、または一瞬の注意でできる行動にする

## 優先順位
1. 昨日または直近で「できなかった」「反省した」と書かれていること
2. 今週のウィークリーノートで観測ポイントになっていること
3. 今日の予定・タスクと関係が深いこと

## 出力形式：本文のみを出力
〇〇

---

【今日の予定】
{todays_schedule}

【今日のタスク】
{todays_task}

【過去7日間の日記】
{daily_context}

【今週のウィークリーノート】
{weekly_note}

today_date: {today}
today_weekday: {todays_weekday}
""")
    # choose one randomly
    # prompt = random.choice(prompts)
    prompt = prompts[2]
    print(f"Prompt: {prompt}")

    response = llm_client.generate_llm_response(
        provider=config.MAKE_TODAY_TARGET_PROVIDER,
        model=config.MAKE_TODAY_TARGET_MODEL,
        prompt=prompt,
        max_tokens=8192,
    ).strip()
    print(f"Response: {response}")

    # 今日のノートに目標を追記
    today_note = reader.get_daily_note_content(today)
    new_today_note = today_note.replace("今日の目標", f"今日の目標\n- [ ] {response}")
    with open(reader.get_daily_note_path(today), "w") as f:
        f.write(new_today_note)

if __name__ == "__main__":
    main()
