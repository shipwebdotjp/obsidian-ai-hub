from datetime import datetime, timedelta
import random
import logging

from obsidian_ai_hub.utils import config, reader, extracter, llm_client, prompt

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

    # プロンプトを読み込み
    context = {
        "todays_schedule": todays_schedule,
        "todays_task": todays_task,
        "daily_context": daily_context,
        "weekly_note": weekly_note,
        "today": today,
        "todays_weekday": todays_weekday,
    }
    rendered_prompt = prompt.render_prompt(config.MAKE_TODAY_TARGET_PROMPT_PATH, context)
    logger.debug("Prompt rendered from: %s", config.MAKE_TODAY_TARGET_PROMPT_PATH)

    response = llm_client.generate_llm_response(
        provider=config.MAKE_TODAY_TARGET_PROVIDER,
        model=config.MAKE_TODAY_TARGET_MODEL,
        prompt=rendered_prompt,
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
