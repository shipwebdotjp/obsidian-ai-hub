from dotenv import load_dotenv
load_dotenv()

import os
import yaml
from pathlib import Path

# プロジェクトルートディレクトリを取得
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_YML_PATH = BASE_DIR / "config" / "config.yml"


def _load_yaml_config() -> dict:
    if not CONFIG_YML_PATH.exists():
        return {}

    with open(CONFIG_YML_PATH, "r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}

    if not isinstance(loaded, dict):
        return {}

    return loaded


yaml_config = _load_yaml_config()


def _config_value(*keys, default=None):
    current = yaml_config
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return default if current is None else current


def _env_or_config(env_name: str, *config_keys, default=None):
    value = os.getenv(env_name)
    if value not in (None, ""):
        return value
    return _config_value(*config_keys, default=default)


def _required_path(env_name: str, *config_keys) -> Path:
    value = _env_or_config(env_name, *config_keys)
    if value in (None, ""):
        joined = ".".join(config_keys) if config_keys else env_name
        raise RuntimeError(f"Missing required configuration: {env_name} or {joined}")
    return Path(str(value)).expanduser()


def _optional_path(env_name: str, *config_keys):
    value = _env_or_config(env_name, *config_keys)
    if value in (None, ""):
        return None
    return Path(str(value)).expanduser()


OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')
OPENCODE_API_KEY = os.getenv('OPENCODE_API_KEY')

# Use os.getenv with a fallback for testing environments
_vault_path_raw = os.getenv('VAULT_PATH')
if _vault_path_raw:
    VAULT_PATH = Path(_vault_path_raw).expanduser()
else:
    # If not set, we default to current directory but warn if not in a test context
    if os.getenv('PYTEST_CURRENT_TEST') is None:
        # Not in a test, this might be a real issue but we want to avoid crashing at import
        VAULT_PATH = Path(".").expanduser()
    else:
        VAULT_PATH = Path(".").expanduser()

INBOX_DIR_NAME = str(_config_value("vault", "inbox", default="inbox"))
DAILY_DIR_NAME = str(_config_value("vault", "daily", default="daily"))
DASHBOARD_DIR_NAME = str(_config_value("vault", "dashboard", default="dashboard"))
TEMPLATE_DIR_NAME = str(_config_value("vault", "template", default="template"))
KNOWLEDGE_DIR_NAME = str(_config_value("vault", "knowledge", default="copilot/knowledge"))
RESEARCH_DIR_NAME = str(_config_value("vault", "research", default="research"))

DAILY_TEMPLATE_FILENAME = str(_config_value("files", "daily_note", default="daily.md"))
WEEKLY_TEMPLATE_FILENAME = str(_config_value("files", "weekly_template", default="Weekly Template.md"))
MONTHLY_TEMPLATE_FILENAME = str(_config_value("files", "monthly_template", default="Monthly Template.md"))
RESEARCH_CANDIDATE_THEME_LIST_FILENAME = str(
    _config_value("files", "research_candidate_theme_list", default="リサーチ候補テーマリスト.md")
)

INBOX_PATH = VAULT_PATH / INBOX_DIR_NAME
DAILY_PATH = VAULT_PATH / DAILY_DIR_NAME
TEMPLATE_PATH = VAULT_PATH / TEMPLATE_DIR_NAME / DAILY_TEMPLATE_FILENAME

SCREENSHOT_DIR = _optional_path("SCREENSHOT_DIR")
SCREENSHOT_PATH = SCREENSHOT_DIR if SCREENSHOT_DIR is not None else (VAULT_PATH / "screenshots")
ACTIVITY_PATH = VAULT_PATH / "activity"
DASHBOARD_PATH = VAULT_PATH / DASHBOARD_DIR_NAME

# Template for weekly notes
WEEKLY_TEMPLATE_PATH = DAILY_PATH / TEMPLATE_DIR_NAME / WEEKLY_TEMPLATE_FILENAME
# Template for monthly notes
MONTHLY_TEMPLATE_PATH = DAILY_PATH / TEMPLATE_DIR_NAME / MONTHLY_TEMPLATE_FILENAME
LOCAL_MODEL_DIR = _optional_path('LOCAL_MODEL_DIR')
LINE_TARGET_ID = os.getenv('LINE_TARGET_ID', '')
LINE_MESSAGING_TOKEN = os.getenv('LINE_MESSAGING_TOKEN', '')
GOG_CALENDAR_ID = os.getenv('GOG_CALENDAR_ID', '')

# Open Web UI Knowledge Base Sync
OPEN_WEB_UI_BASE_URL = os.getenv('OPEN_WEB_UI_BASE_URL', 'http://localhost:8080')
OPEN_WEB_UI_API_KEY = os.getenv('OPEN_WEB_UI_API_KEY', '')
KNOWLEDGE_SYNC_FOLDER = VAULT_PATH / KNOWLEDGE_DIR_NAME

# Vault Index Sync
VAULT_INDEX_COLLECTION_NAME = str(_config_value("vault_index", "collection_name", default="documents"))
VAULT_INDEX_SQLITE_PATH = _optional_path("VAULT_INDEX_SQLITE_PATH", "vault_index", "sqlite_path")
if VAULT_INDEX_SQLITE_PATH is None:
    VAULT_INDEX_SQLITE_PATH = BASE_DIR / "data" / "vault-index" / "search.sqlite"

VAULT_INDEX_CHROMA_PATH = _optional_path("VAULT_INDEX_CHROMA_PATH", "vault_index", "chroma_path")
if VAULT_INDEX_CHROMA_PATH is None:
    VAULT_INDEX_CHROMA_PATH = BASE_DIR / "data" / "vault-index" / "chroma"

VAULT_INDEX_EMBEDDER_MODEL = str(
    _config_value("vault_index", "embedder_model", default="cl-nagoya/ruri-v3-310m")
)
VAULT_INDEX_ALLOW_NETWORK_FALLBACK = _env_or_config(
    "VAULT_INDEX_ALLOW_NETWORK_FALLBACK", "vault_index", "allow_network_fallback", default=False
)
if isinstance(VAULT_INDEX_ALLOW_NETWORK_FALLBACK, str):
    VAULT_INDEX_ALLOW_NETWORK_FALLBACK = VAULT_INDEX_ALLOW_NETWORK_FALLBACK.lower() in ("true", "1", "yes", "on")

# Research Agent
RESEARCH_OUTPUT_DIR = VAULT_PATH / RESEARCH_DIR_NAME
RESEARCH_CANDIDATE_THEME_LIST_PATH = RESEARCH_OUTPUT_DIR / RESEARCH_CANDIDATE_THEME_LIST_FILENAME
RESEARCH_ROUTER_MODEL = os.getenv("RESEARCH_ROUTER_MODEL", "gpt-5.4")
RESEARCH_ROUTER_TEMPERATURE = float(os.getenv("RESEARCH_ROUTER_TEMPERATURE", "0.0"))
RESEARCH_ROUTER_MAX_TOKENS = int(os.getenv("RESEARCH_ROUTER_MAX_TOKENS", "16"))
RESEARCH_PROMPT_MODEL = os.getenv("RESEARCH_PROMPT_MODEL", "gpt-5.4")
RESEARCH_PROMPT_TEMPERATURE = float(os.getenv("RESEARCH_PROMPT_TEMPERATURE", "0.2"))
RESEARCH_PROMPT_MAX_TOKENS = int(os.getenv("RESEARCH_PROMPT_MAX_TOKENS", "8000"))
RESEARCH_SMART_MODEL = os.getenv("RESEARCH_SMART_MODEL", "gpt-5.4")
RESEARCH_VECTORSEARCH_DIR = str(_config_value("research", "vectorsearch_dir", default=""))
RESEARCH_VECTORSEARCH_PYTHON = str(_config_value("research", "vectorsearch_python", default=""))
RESEARCH_VECTORSEARCH_SCRIPT = str(_config_value("research", "vectorsearch_script", default=""))
RESEARCH_DEFAULT_OUTPUT_STYLE = os.getenv("RESEARCH_DEFAULT_OUTPUT_STYLE", "long")
RESEARCH_CONTEXT_LOOKBACK_DAYS = int(os.getenv("RESEARCH_CONTEXT_LOOKBACK_DAYS", "7"))
RESEARCH_CONTEXT_MAX_NOTES = int(os.getenv("RESEARCH_CONTEXT_MAX_NOTES", "3"))

MAKE_TODAY_TARGET_PROVIDER = str(_config_value("llm", "make_today_target", "provider", default="ollama"))
MAKE_TODAY_TARGET_MODEL = str(_config_value("llm", "make_today_target", "model", default="gemma4:e4b"))
MAKE_TODAY_TARGET_PROMPT_PATH = _optional_path("MAKE_TODAY_TARGET_PROMPT_PATH", "llm", "make_today_target", "prompt_path")
if MAKE_TODAY_TARGET_PROMPT_PATH is None:
    MAKE_TODAY_TARGET_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "make_today_target.md"

SUMMARIZE_DAY_PROMPT_PATH = _optional_path("SUMMARIZE_DAY_PROMPT_PATH", "llm", "summarize_day", "prompt_path")
if SUMMARIZE_DAY_PROMPT_PATH is None:
    SUMMARIZE_DAY_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "summarize_day.md"

SUMMARIZE_WEEK_PROMPT_PATH = _optional_path("SUMMARIZE_WEEK_PROMPT_PATH", "llm", "summarize_week", "prompt_path")
if SUMMARIZE_WEEK_PROMPT_PATH is None:
    SUMMARIZE_WEEK_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "summarize_week.md"

SUMMARIZE_MONTH_PROMPT_PATH = _optional_path("SUMMARIZE_MONTH_PROMPT_PATH", "llm", "summarize_month", "prompt_path")
if SUMMARIZE_MONTH_PROMPT_PATH is None:
    SUMMARIZE_MONTH_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "summarize_month.md"

ACTIVITY_CLASSIFICATION_PROMPT_PATH = _optional_path("ACTIVITY_CLASSIFICATION_PROMPT_PATH", "llm", "activity_classification", "prompt_path")
if ACTIVITY_CLASSIFICATION_PROMPT_PATH is None:
    ACTIVITY_CLASSIFICATION_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "activity_classification.md"

INBOX_AUDIO_CORRECTION_PROVIDER = str(_config_value("llm", "inbox_audio_correction", "provider", default="ollama"))
INBOX_AUDIO_CORRECTION_MODEL = str(_config_value("llm", "inbox_audio_correction", "model", default="gpt-oss:120b-cloud"))

LINE_INBOX_SCAN_PROVIDER = str(_config_value("llm", "line_inbox_scan", "provider", default=MAKE_TODAY_TARGET_PROVIDER))
LINE_INBOX_SCAN_MODEL = str(_config_value("llm", "line_inbox_scan", "model", default=MAKE_TODAY_TARGET_MODEL))
LINE_INBOX_SCAN_PROMPT_PATH = _optional_path("LINE_INBOX_SCAN_PROMPT_PATH", "llm", "line_inbox_scan", "prompt_path")
if LINE_INBOX_SCAN_PROMPT_PATH is None:
    LINE_INBOX_SCAN_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "line_scan.md"

INBOX_WEB_SUMMARY_PROMPT_PATH = _optional_path("INBOX_WEB_SUMMARY_PROMPT_PATH", "llm", "inbox_web_summary", "prompt_path")
if INBOX_WEB_SUMMARY_PROMPT_PATH is None:
    INBOX_WEB_SUMMARY_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "inbox_web_summary.md"

INBOX_CLASSIFICATION_PROMPT_PATH = _optional_path("INBOX_CLASSIFICATION_PROMPT_PATH", "llm", "inbox_classification", "prompt_path")
if INBOX_CLASSIFICATION_PROMPT_PATH is None:
    INBOX_CLASSIFICATION_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "inbox_classification.md"

INBOX_TRANSCRIPT_CORRECTION_PROMPT_PATH = _optional_path("INBOX_TRANSCRIPT_CORRECTION_PROMPT_PATH", "llm", "inbox_transcript_correction", "prompt_path")
if INBOX_TRANSCRIPT_CORRECTION_PROMPT_PATH is None:
    INBOX_TRANSCRIPT_CORRECTION_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "inbox_transcript_correction.md"

RESEARCH_THEME_GENERATION_PROMPT_PATH = _optional_path("RESEARCH_THEME_GENERATION_PROMPT_PATH", "llm", "research", "theme_generation", "prompt_path")
if RESEARCH_THEME_GENERATION_PROMPT_PATH is None:
    RESEARCH_THEME_GENERATION_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "research_theme_generation.md"

RESEARCH_ROUTER_PROMPT_PATH = _optional_path("RESEARCH_ROUTER_PROMPT_PATH", "llm", "research", "router", "prompt_path")
if RESEARCH_ROUTER_PROMPT_PATH is None:
    RESEARCH_ROUTER_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "research_router.md"

RESEARCH_INTERNAL_PROMPT_PATH = _optional_path("RESEARCH_INTERNAL_PROMPT_PATH", "llm", "research", "internal", "prompt_path")
if RESEARCH_INTERNAL_PROMPT_PATH is None:
    RESEARCH_INTERNAL_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "research_internal.md"

RESEARCH_WEB_PROMPT_PATH = _optional_path("RESEARCH_WEB_PROMPT_PATH", "llm", "research", "web", "prompt_path")
if RESEARCH_WEB_PROMPT_PATH is None:
    RESEARCH_WEB_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "research_web.md"

RESEARCH_DEEP_PROMPT_PATH = _optional_path("RESEARCH_DEEP_PROMPT_PATH", "llm", "research", "deep", "prompt_path")
if RESEARCH_DEEP_PROMPT_PATH is None:
    RESEARCH_DEEP_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "research_deep.md"

RESEARCH_TITLE_PROMPT_PATH = _optional_path("RESEARCH_TITLE_PROMPT_PATH", "llm", "research", "title", "prompt_path")
if RESEARCH_TITLE_PROMPT_PATH is None:
    RESEARCH_TITLE_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "research_title.md"

RESEARCH_QUERY_GENERATION_PROMPT_PATH = _optional_path("RESEARCH_QUERY_GENERATION_PROMPT_PATH", "llm", "research", "query_generation", "prompt_path")
if RESEARCH_QUERY_GENERATION_PROMPT_PATH is None:
    RESEARCH_QUERY_GENERATION_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "research_query_generation.md"

# Use _env_or_config with a fallback for AI_LOG_PATH
_ai_log_path_raw = _env_or_config("AI_LOG_PATH", "ai_log_path")
if _ai_log_path_raw:
    AI_LOG_PATH = Path(str(_ai_log_path_raw)).expanduser()
else:
    AI_LOG_PATH = Path(".").expanduser()

BACKUP_SYNC_FOLDERS = _config_value("backup", "sync_folders", default=[])
if not isinstance(BACKUP_SYNC_FOLDERS, list):
    BACKUP_SYNC_FOLDERS = []

LOCATION_MAP = _config_value("location_map", default={})
if not isinstance(LOCATION_MAP, dict):
    LOCATION_MAP = {}

REGULARLY_WEEKDAY_EVENTS = _config_value("regularly_weekday_events", default=[])
if not isinstance(REGULARLY_WEEKDAY_EVENTS, list):
    REGULARLY_WEEKDAY_EVENTS = []

REGULARLY_DATE_EVENTS = _config_value("regularly_date_events", default=[])
if not isinstance(REGULARLY_DATE_EVENTS, list):
    REGULARLY_DATE_EVENTS = []
