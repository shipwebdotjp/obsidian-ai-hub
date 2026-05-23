import os
from obsidian_ai_hub.utils import config

def get_daily_note_path(date):
    """
    指定された日付のデイリーノートのパスを返す
    """
    year = date.strftime("%Y")
    month = date.strftime("%m")
    day_str = date.strftime("%Y-%m-%d")
    daily_dir = config.DAILY_PATH / year / month
    daily_file = daily_dir / f"{day_str}.md"
    return daily_file
    

def get_daily_note_content(date):
    """
    指定された日付のデイリーノートの内容を返す
    """
    daily_file = get_daily_note_path(date)
    if not os.path.exists(daily_file):
        return config.TEMPLATE_PATH.read_text(encoding="utf-8")
    with open(daily_file, "r") as f:
        return f.read()
    return ""


def get_weekly_note_path(date):
    """
    指定された日付の週次ノートのパスを返す
    """
    iso_year, iso_week, _ = date.isocalendar()
    month = date.strftime("%m")
    weekly_dir = config.DAILY_PATH / str(iso_year) / month
    weekly_file = weekly_dir / f"{iso_year}-W{iso_week:02d}.md"
    return weekly_file


def get_weekly_note_content(date):
    """
    指定された日付の週次ノートの内容を返す
    """
    weekly_file = get_weekly_note_path(date)
    if not os.path.exists(weekly_file):
        return config.WEEKLY_TEMPLATE_PATH.read_text(encoding="utf-8")
    with open(weekly_file, "r") as f:
        return f.read()
    return ""
