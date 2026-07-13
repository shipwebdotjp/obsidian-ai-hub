from datetime import datetime, timedelta
import random
import logging
import string

from obsidian_ai_hub.utils import config, reader, extracter, llm_client, prompt

logger = logging.getLogger(__name__)

def build_system_prompt() -> str | None:
    from pathlib import Path
    copilot_dir = Path(config.VAULT_PATH) / "copilot"
    files_to_check = [
        copilot_dir / "AI_README.md",
        copilot_dir / "core" / "values.md",
        copilot_dir / "core" / "response_style.md",
        copilot_dir / "core" / "decision_policy.md",
        copilot_dir / "core" / "risk_tolerance.md",
        copilot_dir / "core" / "memory_rules.md",
    ]

    def get_substantial_lines(content: str) -> list[str]:
        lines = content.splitlines()
        in_frontmatter = False
        content_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped == "---":
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter:
                continue
            if stripped.startswith("#"):
                continue
            if stripped.startswith("<!--") or stripped.endswith("-->"):
                continue
            content_lines.append(line)
        return content_lines

    sections = []
    for f_path in files_to_check:
        if f_path.exists():
            try:
                with open(f_path, "r", encoding="utf-8") as f:
                    content = f.read()
                sub_lines = get_substantial_lines(content)
                if sub_lines:
                    sections.append(f"[{f_path.name}]\n" + "\n".join(sub_lines))
            except Exception as e:
                logger.warning(f"Error reading core guideline {f_path.name}: {e}")

    if not sections:
        return None

    return (
        "You must strictly adhere to the following system instructions, guidelines and policies:\n\n"
        + "\n\n".join(sections)
    )


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

    # Long-term memories compilation with fallback
    long_term_memories = ""
    try:
        from obsidian_ai_hub import memory
        context_pack = memory.compile_context("make-target")
        long_term_memories = context_pack.get("context", "")
    except Exception as e:
        logger.warning(f"Failed to compile memory context: {e}. Continuing without long-term memories.")

    # System prompt from Core rules
    system_prompt = None
    try:
        system_prompt = build_system_prompt()
    except Exception as e:
        logger.warning(f"Failed to build system prompt: {e}")

    # プロンプトを読み込み
    context = {
        "todays_schedule": todays_schedule,
        "todays_task": todays_task,
        "daily_context": daily_context,
        "weekly_note": weekly_note,
        "today": today,
        "todays_weekday": todays_weekday,
        "long_term_memories": long_term_memories,
    }

    # Unified prompt template rendering with long-term memories injection
    try:
        with open(config.MAKE_TODAY_TARGET_PROMPT_PATH, "r", encoding="utf-8") as f:
            template_text = f.read()
    except Exception as e:
        logger.warning(f"Failed to read prompt template file: {e}")
        template_text = ""

    if "${long_term_memories}" not in template_text:
        template_text += "\n\n【根拠付き参考情報（長期記憶）】\n${long_term_memories}\n"

    template = string.Template(template_text)
    rendered_prompt = template.substitute(context)

    logger.debug("Prompt rendered from: %s", config.MAKE_TODAY_TARGET_PROMPT_PATH)

    response = llm_client.generate_llm_response(
        provider=config.MAKE_TODAY_TARGET_PROVIDER,
        model=config.MAKE_TODAY_TARGET_MODEL,
        prompt=rendered_prompt,
        max_tokens=8192,
        system_prompt=system_prompt,
    ).strip()
    print(f"Response: {response}")

    # 今日のノートに目標を追記
    today_note = reader.get_daily_note_content(today)
    new_today_note = today_note.replace("今日の目標", f"今日の目標\n- [ ] {response}")
    with open(reader.get_daily_note_path(today), "w") as f:
        f.write(new_today_note)

if __name__ == "__main__":
    main()
