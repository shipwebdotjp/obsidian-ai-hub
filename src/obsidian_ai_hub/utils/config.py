import os
import atexit
import tempfile
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
IS_TEST_ENV = os.environ.get("ENV", "").lower() == "test"

_APP_ENV_VARS = [
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "TAVILY_API_KEY",
    "OPENCODE_API_KEY",
    "OPENCODE_SESSION_ID",
    "LINE_MESSAGING_TOKEN",
    "LINE_TARGET_ID",
    "LINE_TOKEN",
    "LINE_TARGET",
    "APPLE_CALENDAR_NAME",
    "OBSIDIAN_AI_HUB_API_TOKEN",
    "OBSIDIAN_AI_HUB_HOST",
    "OBSIDIAN_AI_HUB_PORT",
    "OBSIDIAN_AI_HUB_WEB_URL",
    "OBSIDIAN_AI_HUB_CORS_ORIGINS",
    "OPEN_WEB_UI_API_KEY",
    "OPEN_WEB_UI_BASE_URL",
    "VAULT_PATH",
    "AI_LOG_PATH",
    "MEMORY_SQLITE_PATH",
    "SCREENSHOT_DIR",
    "LOCAL_MODEL_DIR",
    "VAULT_INDEX_SQLITE_PATH",
    "VAULT_INDEX_CHROMA_PATH",
    "VAULT_INDEX_ALLOW_NETWORK_FALLBACK",
    "HUGGINGFACE_API_KEY",
    "SENTENCE_TRANSFORMERS_HOME",
    "MAKE_TODAY_TARGET_PROMPT_PATH",
    "REVIEW_DRAFT_PROMPT_PATH",
    "SUMMARIZE_DAY_PROMPT_PATH",
    "SUMMARIZE_WEEK_PROMPT_PATH",
    "SUMMARIZE_MONTH_PROMPT_PATH",
    "ACTIVITY_CLASSIFICATION_PROMPT_PATH",
    "LINE_INBOX_SCAN_PROMPT_PATH",
    "MEMORY_EXTRACTOR_PROMPT_PATH",
    "PERSON_MEMORY_EXTRACTOR_PROMPT_PATH",
    "MEMORY_AGENT_CONVERSATION_PROMPT_PATH",
    "MEMORY_AGENT_CONVERSATION_ENABLED",
    "MEMORY_RENDERER_PROMPT_PATH",
    "INBOX_TRANSCRIPT_CORRECTION_PROMPT_PATH",
    "INBOX_WEB_SUMMARY_PROMPT_PATH",
    "INBOX_CLASSIFICATION_PROMPT_PATH",
    "AI_PLANNER_PROMPT_PATH",
    "YOUTUBE_CHUNK_SUMMARY_PROMPT_PATH",
    "ALLOW_EXTERNAL_IN_TEST",
    "AGENT_PROVIDER",
    "AGENT_MODEL",
    "OBSIDIAN_AI_HUB_PLUGINS_DIR",
    "OBSIDIAN_AI_HUB_SKILLS_DIR",
    "HEALTHCARE_SQLITE_PATH",
    "HEALTHCARE_EXPORT_DIR",
    "HEALTHCARE_IMPORT_STAGING_DIR",
    "CODING_ORCHESTRATOR_PROVIDER",
    "CODING_ORCHESTRATOR_MODEL",
    "CODING_OPENCODE_CLI_PATH",
    "CODING_OPENCODE_MODEL",
    "CODING_OPENCODE_MODELS",
    "IMAGE_GENERATION_OUTPUT_DIR",
    "IMAGE_GENERATION_INPUT_DIR",
    "IMAGE_GENERATION_MODEL",
    "IMAGE_GENERATION_DEFAULT_SIZE",
    "IMAGE_GENERATION_DEFAULT_QUALITY",
    "IMAGE_GENERATION_MAX_COUNT",
    "IMAGE_GENERATION_MAX_INPUT_BYTES",
]

if IS_TEST_ENV:
    for key in _APP_ENV_VARS:
        os.environ.pop(key, None)

    if not os.environ.get("OAIHUB_SKIP_DOTENV"):
        test_dotenv = BASE_DIR / ".env.test"
        if test_dotenv.exists():
            from dotenv import load_dotenv

            load_dotenv(str(test_dotenv), override=True)

    ALLOW_EXTERNAL_IN_TEST = os.environ.get("ALLOW_EXTERNAL_IN_TEST", "0").lower() in (
        "1",
        "true",
        "yes",
    )

    _test_workspace = tempfile.TemporaryDirectory(prefix="obsidian-ai-hub-test-")
    TEST_WORKSPACE = Path(_test_workspace.name)
    atexit.register(_test_workspace.cleanup)

    CONFIG_YML_PATH = BASE_DIR / "config" / "config.test.yml"
else:
    from dotenv import load_dotenv

    load_dotenv()
    ALLOW_EXTERNAL_IN_TEST = True
    CONFIG_YML_PATH = BASE_DIR / "config" / "config.yml"


def ensure_external_allowed(context: str = ""):
    if IS_TEST_ENV and not ALLOW_EXTERNAL_IN_TEST:
        raise RuntimeError(
            f"External access blocked in test mode{': ' + context if context else ''}. "
            "Set ALLOW_EXTERNAL_IN_TEST=1 in .env.test to allow."
        )


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


def _config_optional_path(*config_keys):
    """Read a non-secret path from config.yml without an environment fallback."""
    value = _config_value(*config_keys)
    if value in (None, ""):
        return None
    return Path(str(value)).expanduser()


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
OPENCODE_API_KEY = os.getenv("OPENCODE_API_KEY")
# OpenCode Go へ送るデフォルトのセッション識別子（会話 session_id 未指定時のフォールバック）。
# APIキー・個人情報・プロンプトは含めない。
# 環境変数 OPENCODE_SESSION_ID または config.yml の opencode_go.session_id で上書き可能。
OPENCODE_SESSION_ID = str(
    _env_or_config(
        "OPENCODE_SESSION_ID", "opencode_go", "session_id", default="obsidian-ai-hub"
    )
).strip() or "obsidian-ai-hub"

if IS_TEST_ENV:
    VAULT_PATH = TEST_WORKSPACE / "vault"
else:
    _vault_path_raw = os.getenv("VAULT_PATH")
    if _vault_path_raw:
        VAULT_PATH = Path(_vault_path_raw).expanduser()
    else:
        VAULT_PATH = Path(".").expanduser()

INBOX_DIR_NAME = str(_config_value("vault", "inbox", default="inbox"))
DAILY_DIR_NAME = str(_config_value("vault", "daily", default="daily"))
TEMPLATE_DIR_NAME = str(_config_value("vault", "template", default="template"))
KNOWLEDGE_DIR_NAME = str(
    _config_value("vault", "knowledge", default="copilot/knowledge")
)
RESEARCH_DIR_NAME = str(_config_value("vault", "research", default="research"))
WEBCLIP_DIR_NAME = str(_config_value("vault", "webclip", default="webclip"))
PEOPLE_DIR_NAME = str(_config_value("vault", "people", default="people"))

DAILY_TEMPLATE_FILENAME = str(_config_value("files", "daily_note", default="daily.md"))
WEEKLY_TEMPLATE_FILENAME = str(
    _config_value("files", "weekly_template", default="Weekly Template.md")
)
MONTHLY_TEMPLATE_FILENAME = str(
    _config_value("files", "monthly_template", default="Monthly Template.md")
)
RESEARCH_CANDIDATE_THEME_LIST_FILENAME = str(
    _config_value(
        "files", "research_candidate_theme_list", default="リサーチ候補テーマリスト.md"
    )
)

INBOX_PATH = VAULT_PATH / INBOX_DIR_NAME
DAILY_PATH = VAULT_PATH / DAILY_DIR_NAME
TEMPLATE_PATH = VAULT_PATH / TEMPLATE_DIR_NAME / DAILY_TEMPLATE_FILENAME
WEBCLIP_PATH = VAULT_PATH / WEBCLIP_DIR_NAME
PEOPLE_PATH = VAULT_PATH / PEOPLE_DIR_NAME
DASHBOARD_DIR_NAME = str(_config_value("vault", "dashboard", default="dashboard"))
DASHBOARD_PATH = VAULT_PATH / DASHBOARD_DIR_NAME

SCREENSHOT_DIR = _optional_path("SCREENSHOT_DIR")
SCREENSHOT_PATH = (
    SCREENSHOT_DIR if SCREENSHOT_DIR is not None else (VAULT_PATH / "screenshots")
)
ACTIVITY_PATH = VAULT_PATH / "activity"

# Template for weekly notes
WEEKLY_TEMPLATE_PATH = DAILY_PATH / TEMPLATE_DIR_NAME / WEEKLY_TEMPLATE_FILENAME
# Template for monthly notes
MONTHLY_TEMPLATE_PATH = DAILY_PATH / TEMPLATE_DIR_NAME / MONTHLY_TEMPLATE_FILENAME
LOCAL_MODEL_DIR = _optional_path("LOCAL_MODEL_DIR")
LINE_TARGET_ID = os.getenv("LINE_TARGET_ID", "")
LINE_MESSAGING_TOKEN = os.getenv("LINE_MESSAGING_TOKEN", "")
APPLE_CALENDAR_NAME = os.getenv("APPLE_CALENDAR_NAME", "")

# Public base URL for the Web UI / API, used as the base for LINE notification
# deep links (e.g. Tailscale Serve https://aihub.tail744355.ts.net). Never
# contains secrets such as the API token.
OBSIDIAN_AI_HUB_WEB_URL = os.getenv("OBSIDIAN_AI_HUB_WEB_URL", "").rstrip("/")

# Open Web UI Knowledge Base Sync
OPEN_WEB_UI_BASE_URL = os.getenv("OPEN_WEB_UI_BASE_URL", "http://localhost:8080")
OPEN_WEB_UI_API_KEY = os.getenv("OPEN_WEB_UI_API_KEY", "")
KNOWLEDGE_SYNC_FOLDER = VAULT_PATH / KNOWLEDGE_DIR_NAME

# Vault Index Sync
VAULT_INDEX_COLLECTION_NAME = str(
    _config_value("vault_index", "collection_name", default="documents")
)
VAULT_INDEX_SQLITE_PATH = _optional_path(
    "VAULT_INDEX_SQLITE_PATH", "vault_index", "sqlite_path"
)
if VAULT_INDEX_SQLITE_PATH is None:
    VAULT_INDEX_SQLITE_PATH = BASE_DIR / "data" / "vault-index" / "search.sqlite"

VAULT_INDEX_CHROMA_PATH = _optional_path(
    "VAULT_INDEX_CHROMA_PATH", "vault_index", "chroma_path"
)
if VAULT_INDEX_CHROMA_PATH is None:
    VAULT_INDEX_CHROMA_PATH = BASE_DIR / "data" / "vault-index" / "chroma"

VAULT_INDEX_EMBEDDER_MODEL = str(
    _config_value("vault_index", "embedder_model", default="cl-nagoya/ruri-v3-310m")
)
VAULT_INDEX_ALLOW_NETWORK_FALLBACK = _env_or_config(
    "VAULT_INDEX_ALLOW_NETWORK_FALLBACK",
    "vault_index",
    "allow_network_fallback",
    default=False,
)
if isinstance(VAULT_INDEX_ALLOW_NETWORK_FALLBACK, str):
    VAULT_INDEX_ALLOW_NETWORK_FALLBACK = VAULT_INDEX_ALLOW_NETWORK_FALLBACK.lower() in (
        "true",
        "1",
        "yes",
        "on",
    )

# Research Agent
RESEARCH_OUTPUT_DIR = VAULT_PATH / RESEARCH_DIR_NAME
RESEARCH_CANDIDATE_THEME_LIST_PATH = (
    RESEARCH_OUTPUT_DIR / RESEARCH_CANDIDATE_THEME_LIST_FILENAME
)
RESEARCH_VECTORSEARCH_DIR = str(
    _config_value("research", "vectorsearch_dir", default="")
)
RESEARCH_VECTORSEARCH_PYTHON = str(
    _config_value("research", "vectorsearch_python", default="")
)
RESEARCH_VECTORSEARCH_SCRIPT = str(
    _config_value("research", "vectorsearch_script", default="")
)
RESEARCH_DEFAULT_OUTPUT_STYLE = str(
    _config_value("research", "default_output_style", default="long")
)
RESEARCH_CONTEXT_LOOKBACK_DAYS = int(
    _config_value("research", "context", "lookback_days", default=7)
)
RESEARCH_CONTEXT_MAX_NOTES = int(
    _config_value("research", "context", "max_notes", default=3)
)
RESEARCH_GPT_RESEARCHER_RETRIEVER = str(
    _config_value(
        "research", "deep", "gpt_researcher", "retriever", default="tavily,mcp"
    )
)
RESEARCH_GPT_RESEARCHER_FAST_LLM = str(
    _config_value(
        "research", "deep", "gpt_researcher", "fast_llm", default="openai:gpt-5.6-terra"
    )
)
RESEARCH_GPT_RESEARCHER_SMART_LLM = str(
    _config_value(
        "research",
        "deep",
        "gpt_researcher",
        "smart_llm",
        default="openai:gpt-5.6-terra",
    )
)
RESEARCH_GPT_RESEARCHER_STRATEGIC_LLM = str(
    _config_value(
        "research",
        "deep",
        "gpt_researcher",
        "strategic_llm",
        default="openai:gpt-5.6-terra",
    )
)
RESEARCH_GPT_RESEARCHER_EMBEDDING = str(
    _config_value(
        "research",
        "deep",
        "gpt_researcher",
        "embedding",
        default="huggingface:cl-nagoya/ruri-v3-70m",
    )
)
RESEARCH_GPT_RESEARCHER_SMART_TOKEN_LIMIT = str(
    _config_value(
        "research", "deep", "gpt_researcher", "smart_token_limit", default=16000
    )
)
RESEARCH_GPT_RESEARCHER_BROWSE_CHUNK_MAX_LENGTH = str(
    _config_value(
        "research", "deep", "gpt_researcher", "browse_chunk_max_length", default=8192
    )
)
RESEARCH_GPT_RESEARCHER_LANGUAGE = str(
    _config_value("research", "deep", "gpt_researcher", "language", default="japanese")
)

MAKE_TODAY_TARGET_PROVIDER = str(
    _config_value("llm", "make_today_target", "provider", default="ollama")
)
MAKE_TODAY_TARGET_MODEL = str(
    _config_value("llm", "make_today_target", "model", default="gemma4:e4b")
)
MAKE_TODAY_TARGET_PROMPT_PATH = _optional_path(
    "MAKE_TODAY_TARGET_PROMPT_PATH", "llm", "make_today_target", "prompt_path"
)
if MAKE_TODAY_TARGET_PROMPT_PATH is None:
    MAKE_TODAY_TARGET_PROMPT_PATH = (
        BASE_DIR / "config" / "prompts" / "make_today_target.md"
    )

# Weekly review drafts use the same LLM as the existing daily/weekly summaries
# unless explicitly overridden.
REVIEW_DRAFT_PROVIDER = str(
    _config_value("llm", "review_draft", "provider", default=MAKE_TODAY_TARGET_PROVIDER)
)
REVIEW_DRAFT_MODEL = str(
    _config_value("llm", "review_draft", "model", default=MAKE_TODAY_TARGET_MODEL)
)
REVIEW_DRAFT_PROMPT_PATH = _optional_path(
    "REVIEW_DRAFT_PROMPT_PATH", "llm", "review_draft", "prompt_path"
)
if REVIEW_DRAFT_PROMPT_PATH is None:
    REVIEW_DRAFT_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "review_draft.md"

SUMMARIZE_DAY_PROMPT_PATH = _optional_path(
    "SUMMARIZE_DAY_PROMPT_PATH", "llm", "summarize_day", "prompt_path"
)
if SUMMARIZE_DAY_PROMPT_PATH is None:
    SUMMARIZE_DAY_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "summarize_day.md"

SUMMARIZE_WEEK_PROMPT_PATH = _optional_path(
    "SUMMARIZE_WEEK_PROMPT_PATH", "llm", "summarize_week", "prompt_path"
)
if SUMMARIZE_WEEK_PROMPT_PATH is None:
    SUMMARIZE_WEEK_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "summarize_week.md"

SUMMARIZE_MONTH_PROMPT_PATH = _optional_path(
    "SUMMARIZE_MONTH_PROMPT_PATH", "llm", "summarize_month", "prompt_path"
)
if SUMMARIZE_MONTH_PROMPT_PATH is None:
    SUMMARIZE_MONTH_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "summarize_month.md"

ACTIVITY_CLASSIFICATION_PROMPT_PATH = _optional_path(
    "ACTIVITY_CLASSIFICATION_PROMPT_PATH",
    "llm",
    "activity_classification",
    "prompt_path",
)
if ACTIVITY_CLASSIFICATION_PROMPT_PATH is None:
    ACTIVITY_CLASSIFICATION_PROMPT_PATH = (
        BASE_DIR / "config" / "prompts" / "activity_classification.md"
    )

INBOX_AUDIO_CORRECTION_PROVIDER = str(
    _config_value("llm", "inbox_audio_correction", "provider", default="ollama")
)
INBOX_AUDIO_CORRECTION_MODEL = str(
    _config_value(
        "llm", "inbox_audio_correction", "model", default="gpt-oss:120b-cloud"
    )
)

LINE_INBOX_SCAN_PROVIDER = str(
    _config_value(
        "llm", "line_inbox_scan", "provider", default=MAKE_TODAY_TARGET_PROVIDER
    )
)
LINE_INBOX_SCAN_MODEL = str(
    _config_value("llm", "line_inbox_scan", "model", default=MAKE_TODAY_TARGET_MODEL)
)
LINE_INBOX_SCAN_PROMPT_PATH = _optional_path(
    "LINE_INBOX_SCAN_PROMPT_PATH", "llm", "line_inbox_scan", "prompt_path"
)
if LINE_INBOX_SCAN_PROMPT_PATH is None:
    LINE_INBOX_SCAN_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "line_scan.md"

INBOX_WEB_SUMMARY_PROVIDER = str(
    _config_value("llm", "inbox_web_summary", "provider", default="openai")
)
INBOX_WEB_SUMMARY_MODEL = str(
    _config_value("llm", "inbox_web_summary", "model", default="gpt-5.4")
)
INBOX_WEB_SUMMARY_PROMPT_PATH = _config_optional_path(
    "llm", "inbox_web_summary", "prompt_path"
)
if INBOX_WEB_SUMMARY_PROMPT_PATH is None:
    INBOX_WEB_SUMMARY_PROMPT_PATH = (
        BASE_DIR / "config" / "prompts" / "inbox_web_summary.md"
    )

YOUTUBE_TRANSCRIPT_LANGUAGES = _config_value(
    "youtube", "transcript_languages", default=["ja", "en"]
)
if not isinstance(YOUTUBE_TRANSCRIPT_LANGUAGES, list):
    YOUTUBE_TRANSCRIPT_LANGUAGES = ["ja", "en"]
YOUTUBE_TRANSCRIPT_LANGUAGES = [
    str(language) for language in YOUTUBE_TRANSCRIPT_LANGUAGES
]
YOUTUBE_WHISPER_MODEL = str(_config_value("youtube", "whisper_model", default="medium"))
YOUTUBE_SUMMARY_CHUNK_CHARS = int(
    _config_value("youtube", "summary_chunk_chars", default=12000)
)
YOUTUBE_CHUNK_SUMMARY_PROMPT_PATH = _config_optional_path(
    "llm", "inbox_youtube_chunk_summary", "prompt_path"
)
if YOUTUBE_CHUNK_SUMMARY_PROMPT_PATH is None:
    YOUTUBE_CHUNK_SUMMARY_PROMPT_PATH = (
        BASE_DIR / "config" / "prompts" / "inbox_youtube_chunk_summary.md"
    )

INBOX_CLASSIFICATION_PROVIDER = str(
    _config_value("llm", "inbox_classification", "provider", default="openai")
)
INBOX_CLASSIFICATION_MODEL = str(
    _config_value("llm", "inbox_classification", "model", default="gpt-5.4")
)
INBOX_CLASSIFICATION_PROMPT_PATH = _config_optional_path(
    "llm", "inbox_classification", "prompt_path"
)
if INBOX_CLASSIFICATION_PROMPT_PATH is None:
    INBOX_CLASSIFICATION_PROMPT_PATH = (
        BASE_DIR / "config" / "prompts" / "inbox_classification.md"
    )

INBOX_TRANSCRIPT_CORRECTION_PROMPT_PATH = _optional_path(
    "INBOX_TRANSCRIPT_CORRECTION_PROMPT_PATH",
    "llm",
    "inbox_transcript_correction",
    "prompt_path",
)
if INBOX_TRANSCRIPT_CORRECTION_PROMPT_PATH is None:
    INBOX_TRANSCRIPT_CORRECTION_PROMPT_PATH = (
        BASE_DIR / "config" / "prompts" / "inbox_transcript_correction.md"
    )

RESEARCH_THEME_GENERATION_PROVIDER = str(
    _config_value("llm", "research", "theme_generation", "provider", default="openai")
)
RESEARCH_THEME_GENERATION_MODEL = str(
    _config_value("llm", "research", "theme_generation", "model", default="gpt-5.4")
)
RESEARCH_THEME_GENERATION_PROMPT_PATH = _config_optional_path(
    "llm", "research", "theme_generation", "prompt_path"
)
if RESEARCH_THEME_GENERATION_PROMPT_PATH is None:
    RESEARCH_THEME_GENERATION_PROMPT_PATH = (
        BASE_DIR / "config" / "prompts" / "research_theme_generation.md"
    )

RESEARCH_ROUTER_PROVIDER = str(
    _config_value("llm", "research", "router", "provider", default="openai")
)
RESEARCH_ROUTER_MODEL = str(
    _config_value("llm", "research", "router", "model", default="gpt-5.4")
)
RESEARCH_ROUTER_PROMPT_PATH = _config_optional_path(
    "llm", "research", "router", "prompt_path"
)
if RESEARCH_ROUTER_PROMPT_PATH is None:
    RESEARCH_ROUTER_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "research_router.md"

RESEARCH_INTERNAL_PROVIDER = str(
    _config_value("llm", "research", "internal", "provider", default="openai")
)
RESEARCH_INTERNAL_MODEL = str(
    _config_value("llm", "research", "internal", "model", default="gpt-5.4")
)
RESEARCH_INTERNAL_PROMPT_PATH = _config_optional_path(
    "llm", "research", "internal", "prompt_path"
)
if RESEARCH_INTERNAL_PROMPT_PATH is None:
    RESEARCH_INTERNAL_PROMPT_PATH = (
        BASE_DIR / "config" / "prompts" / "research_internal.md"
    )

RESEARCH_WEB_PROVIDER = str(
    _config_value("llm", "research", "web", "provider", default="openai")
)
RESEARCH_WEB_MODEL = str(
    _config_value("llm", "research", "web", "model", default="gpt-5.4")
)
RESEARCH_WEB_PROMPT_PATH = _config_optional_path(
    "llm", "research", "web", "prompt_path"
)
if RESEARCH_WEB_PROMPT_PATH is None:
    RESEARCH_WEB_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "research_web.md"

RESEARCH_DEEP_PROMPT_PATH = _config_optional_path(
    "llm", "research", "deep", "prompt_path"
)
if RESEARCH_DEEP_PROMPT_PATH is None:
    RESEARCH_DEEP_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "research_deep.md"

RESEARCH_PROJECT_PROMPT_PATH = _config_optional_path(
    "llm", "research", "project", "prompt_path"
)
if RESEARCH_PROJECT_PROMPT_PATH is None:
    RESEARCH_PROJECT_PROMPT_PATH = (
        BASE_DIR / "config" / "prompts" / "research_project.md"
    )

RESEARCH_TITLE_GENERATION_PROVIDER = str(
    _config_value("llm", "research", "title_generation", "provider", default="openai")
)
RESEARCH_TITLE_GENERATION_MODEL = str(
    _config_value("llm", "research", "title_generation", "model", default="gpt-5.4")
)
RESEARCH_TITLE_PROMPT_PATH = _config_optional_path(
    "llm", "research", "title_generation", "prompt_path"
)
if RESEARCH_TITLE_PROMPT_PATH is None:
    RESEARCH_TITLE_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "research_title.md"

RESEARCH_QUERY_GENERATION_PROVIDER = str(
    _config_value("llm", "research", "query_generation", "provider", default="openai")
)
RESEARCH_QUERY_GENERATION_MODEL = str(
    _config_value("llm", "research", "query_generation", "model", default="gpt-5.4")
)
RESEARCH_QUERY_GENERATION_PROMPT_PATH = _config_optional_path(
    "llm", "research", "query_generation", "prompt_path"
)
if RESEARCH_QUERY_GENERATION_PROMPT_PATH is None:
    RESEARCH_QUERY_GENERATION_PROMPT_PATH = (
        BASE_DIR / "config" / "prompts" / "research_query_generation.md"
    )

AI_PLANNER_PROVIDER = str(
    _config_value("llm", "planner", "provider", default="opencode_go")
)
AI_PLANNER_MODEL = str(
    _config_value("llm", "planner", "model", default="gpt-5.6-luna")
)
AI_PLANNER_PROMPT_PATH = _config_optional_path("llm", "planner", "prompt_path")
if AI_PLANNER_PROMPT_PATH is None:
    AI_PLANNER_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "ai_planner.md"

# AI Agent default provider/model (used when agent has no provider/model set)
AGENT_PROVIDER = str(
    _env_or_config("AGENT_PROVIDER", "llm", "agent", "provider", default="openai")
)
AGENT_MODEL = str(
    _env_or_config("AGENT_MODEL", "llm", "agent", "model", default="gpt-5.6-terra")
)

# AI Agent session title generation LLM config & prompt
AGENT_TITLE_GENERATION_PROVIDER = str(
    _config_value("llm", "agent_title_generation", "provider", default="openai")
)
AGENT_TITLE_GENERATION_MODEL = str(
    _config_value("llm", "agent_title_generation", "model", default="gpt-5.4-mini")
)
AGENT_TITLE_PROMPT_PATH = _config_optional_path(
    "llm", "agent_title_generation", "prompt_path"
)
if AGENT_TITLE_PROMPT_PATH is None:
    AGENT_TITLE_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "agent_title.md"

# Coding Orchestrator & CLI config
CODING_ORCHESTRATOR_PROVIDER = str(
    _env_or_config("CODING_ORCHESTRATOR_PROVIDER", "coding", "orchestrator", "provider", default="openai")
)
CODING_ORCHESTRATOR_MODEL = str(
    _env_or_config("CODING_ORCHESTRATOR_MODEL", "coding", "orchestrator", "model", default="gpt-5.6-terra")
)
CODING_OPENCODE_CLI_PATH = str(
    _env_or_config("CODING_OPENCODE_CLI_PATH", "coding", "cli", "opencode_path", default="opencode")
)
CODING_OPENCODE_MODEL = str(
    _env_or_config(
        "CODING_OPENCODE_MODEL",
        "coding",
        "acp",
        "opencode_model",
        default="opencode-go/muse-spark-1.3-contributor",
    )
)


def _parse_coding_model_list(raw: object) -> list[str]:
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        return []
    seen: list[str] = []
    for item in items:
        name = str(item or "").strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def get_available_coding_models() -> list[str]:
    """Return the config-derived allowlist of OpenCode models.

    Sources: ``CODING_OPENCODE_MODELS`` env (comma-separated) or
    ``coding.acp.opencode_models`` list in config.yml. Falls back to
    ``[CODING_OPENCODE_MODEL]`` so legacy single-model configs keep working.
    Free-form user input is never accepted; callers must validate
    membership in this list.
    """
    env_raw = os.getenv("CODING_OPENCODE_MODELS")
    models = _parse_coding_model_list(env_raw) if env_raw not in (None, "") else []
    if not models:
        models = _parse_coding_model_list(_config_value("coding", "acp", "opencode_models", default=[]))
    if not models:
        models = _parse_coding_model_list(CODING_OPENCODE_MODEL)
    return models


def resolve_coding_model(candidate: object) -> str:
    """Return ``candidate`` if it is in the allowlist, else raise ValueError."""
    name = str(candidate or "").strip()
    if name in get_available_coding_models():
        return name
    raise ValueError(
        f"Unknown coding model '{candidate}'. "
        "Choose one of the models configured in coding.acp.opencode_models."
    )


def resolve_effective_coding_model(session_value: object) -> str:
    """Return the session model when allowlisted, else the default.

    Legacy sessions store NULL/unknown values; they fall back to
    ``CODING_OPENCODE_MODEL`` for backward compatibility.
    """
    name = str(session_value or "").strip()
    if name and name in get_available_coding_models():
        return name
    default = (CODING_OPENCODE_MODEL or "").strip()
    if default:
        return default
    models = get_available_coding_models()
    if not models:
        raise ValueError("No coding models are configured.")
    return models[0]


# Providers accepted by the orchestrator LLM (mirrors create_langchain_llm).
CODING_ORCHESTRATOR_PROVIDERS = ("openai", "gemini", "ollama", "local", "opencode_go")


def get_available_orchestrator_providers() -> list[str]:
    """Return the allowlist of providers selectable for the orchestrator LLM."""
    return list(CODING_ORCHESTRATOR_PROVIDERS)


def resolve_orchestrator_provider(candidate: object) -> str:
    """Return ``candidate`` if it is a supported provider, else raise ValueError."""
    name = str(candidate or "").strip()
    if name in get_available_orchestrator_providers():
        return name
    raise ValueError(
        f"Unknown orchestrator provider '{candidate}'. "
        f"Choose one of: {', '.join(get_available_orchestrator_providers())}."
    )


def resolve_orchestrator_model(candidate: object) -> str:
    """Return the trimmed non-empty orchestrator model name, else raise ValueError.

    Orchestrator models are provider-specific and not allowlisted (unlike the
    OpenCode worker models), so only emptiness is rejected here.
    """
    name = str(candidate or "").strip()
    if not name:
        raise ValueError("Orchestrator model must not be empty.")
    return name


def resolve_effective_coding_orchestrator(
    session_provider: object, session_model: object
) -> tuple[str, str]:
    """Resolve the per-session orchestrator provider/model.

    Each field falls back to the config default independently when the session
    value is unset, so sessions without an override use
    ``CODING_ORCHESTRATOR_PROVIDER`` / ``CODING_ORCHESTRATOR_MODEL``.
    """
    provider = str(session_provider or "").strip() or CODING_ORCHESTRATOR_PROVIDER
    model = str(session_model or "").strip() or CODING_ORCHESTRATOR_MODEL
    return provider, model


# Coding workspace is ACP-only with the OpenCode backend. There is no
# backend selection: keep the constant for callers that still reference it.
CODING_DEFAULT_BACKEND = "opencode"

if IS_TEST_ENV:
    AI_LOG_PATH = TEST_WORKSPACE / "vault" / "ai-log"
else:
    _ai_log_path_raw = _env_or_config("AI_LOG_PATH", "ai_log_path")
    if _ai_log_path_raw:
        AI_LOG_PATH = Path(str(_ai_log_path_raw)).expanduser()
    else:
        AI_LOG_PATH = Path(".").expanduser()

BACKUP_SYNC_FOLDERS = _config_value("backup", "sync_folders", default=[])
if not isinstance(BACKUP_SYNC_FOLDERS, list):
    BACKUP_SYNC_FOLDERS = []

# Optional absolute path to the rsync binary to run. When unset the legacy
# "rsync" lookup on PATH is used. The backup service validates the value and
# runs `<executable> --version` before touching any destination.
BACKUP_RSYNC_EXECUTABLE = _config_value("backup", "rsync_executable")

LOCATION_MAP = _config_value("location_map", default={})
if not isinstance(LOCATION_MAP, dict):
    LOCATION_MAP = {}

REGULARLY_WEEKDAY_EVENTS = _config_value("regularly_weekday_events", default=[])
if not isinstance(REGULARLY_WEEKDAY_EVENTS, list):
    REGULARLY_WEEKDAY_EVENTS = []

REGULARLY_DATE_EVENTS = _config_value("regularly_date_events", default=[])
if not isinstance(REGULARLY_DATE_EVENTS, list):
    REGULARLY_DATE_EVENTS = []

# Memory Configuration
MEMORY_CONTEXT_MAX_TOKENS = int(
    _config_value("memory", "context_max_tokens", default=800)
)

MEMORY_AGENT_CONTEXT_MAX_TOKENS = int(
    _config_value("memory", "agent_context_max_tokens", default=400)
)

# Per-purpose overrides for long-term memory compilation. Keys are purpose
# strings (e.g. "make-target", "summarize-day") mapped to a dict with optional
# "kinds", "budget", "format" ("evidence" | "fenced"), "include_person",
# "person_kinds", and "person_budget".
MEMORY_PURPOSE_OVERRIDES = _config_value("memory", "purposes", default={})
if not isinstance(MEMORY_PURPOSE_OVERRIDES, dict):
    MEMORY_PURPOSE_OVERRIDES = {}

# Memory Interview Configuration
MEMORY_INTERVIEW_PROVIDER = _config_value("memory", "interview", "provider")
MEMORY_INTERVIEW_MODEL = _config_value("memory", "interview", "model")
MEMORY_INTERVIEW_MAX_QUESTIONS = int(_config_value("memory", "interview", "max_questions", default=3))
MEMORY_INTERVIEW_CONTEXT_MAX_TOKENS = int(_config_value("memory", "interview", "context_max_tokens", default=4000))

MEMORY_INTERVIEW_QUESTION_PROMPT_PATH = _optional_path("MEMORY_INTERVIEW_QUESTION_PROMPT_PATH", "memory", "interview", "question_prompt_path")
if MEMORY_INTERVIEW_QUESTION_PROMPT_PATH is None:
    MEMORY_INTERVIEW_QUESTION_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "memory_interview_questions.md"

MEMORY_INTERVIEW_EXTRACTION_PROMPT_PATH = _optional_path("MEMORY_INTERVIEW_EXTRACTION_PROMPT_PATH", "memory", "interview", "extraction_prompt_path")
if MEMORY_INTERVIEW_EXTRACTION_PROMPT_PATH is None:
    MEMORY_INTERVIEW_EXTRACTION_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "memory_interview_extract.md"

if IS_TEST_ENV:
    MEMORY_SQLITE_PATH = TEST_WORKSPACE / "memory.sqlite3"
else:
    MEMORY_SQLITE_PATH_RAW = _env_or_config(
        "MEMORY_SQLITE_PATH", "memory", "sqlite_path"
    )
    if MEMORY_SQLITE_PATH_RAW:
        MEMORY_SQLITE_PATH = Path(str(MEMORY_SQLITE_PATH_RAW)).expanduser()
    else:
        MEMORY_SQLITE_PATH = Path(
            "~/.config/obsidian-ai-hub/memory.sqlite3"
        ).expanduser()

_extractor_provider = _config_value("memory", "extractor", "provider")
MEMORY_EXTRACTOR_PROVIDER = (
    str(_extractor_provider)
    if _extractor_provider is not None
    else MAKE_TODAY_TARGET_PROVIDER
)

_extractor_model = _config_value("memory", "extractor", "model")
MEMORY_EXTRACTOR_MODEL = (
    str(_extractor_model) if _extractor_model is not None else MAKE_TODAY_TARGET_MODEL
)

MEMORY_EXTRACTOR_PROMPT_PATH = _optional_path(
    "MEMORY_EXTRACTOR_PROMPT_PATH", "memory", "extractor", "prompt_path"
)
if MEMORY_EXTRACTOR_PROMPT_PATH is None:
    MEMORY_EXTRACTOR_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "memory_extract.md"

PERSON_MEMORY_EXTRACTOR_PROMPT_PATH = _optional_path(
    "PERSON_MEMORY_EXTRACTOR_PROMPT_PATH", "memory", "person_extractor", "prompt_path"
)
if PERSON_MEMORY_EXTRACTOR_PROMPT_PATH is None:
    PERSON_MEMORY_EXTRACTOR_PROMPT_PATH = (
        BASE_DIR / "config" / "prompts" / "person_memory_extract.md"
    )

_agent_conversation_enabled = _env_or_config(
    "MEMORY_AGENT_CONVERSATION_ENABLED",
    "memory",
    "agent_conversation",
    "enabled",
    default=True,
)
if isinstance(_agent_conversation_enabled, str):
    _agent_conversation_enabled = _agent_conversation_enabled.lower() in (
        "true",
        "1",
        "yes",
        "on",
    )
MEMORY_AGENT_CONVERSATION_ENABLED = bool(_agent_conversation_enabled)

MEMORY_AGENT_CONVERSATION_MAX_MESSAGES = int(
    _config_value("memory", "agent_conversation", "max_messages", default=300)
)
MEMORY_AGENT_CONVERSATION_MAX_TOTAL_CHARS = int(
    _config_value("memory", "agent_conversation", "max_total_chars", default=60000)
)
MEMORY_AGENT_CONVERSATION_MAX_USER_CHARS = int(
    _config_value("memory", "agent_conversation", "max_user_chars", default=4000)
)
MEMORY_AGENT_CONVERSATION_MAX_ASSISTANT_CHARS = int(
    _config_value("memory", "agent_conversation", "max_assistant_chars", default=2000)
)

MEMORY_AGENT_CONVERSATION_PROMPT_PATH = _optional_path(
    "MEMORY_AGENT_CONVERSATION_PROMPT_PATH",
    "memory",
    "agent_conversation",
    "prompt_path",
)
if MEMORY_AGENT_CONVERSATION_PROMPT_PATH is None:
    MEMORY_AGENT_CONVERSATION_PROMPT_PATH = (
        BASE_DIR / "config" / "prompts" / "agent_memory_extract.md"
    )

_renderer_provider = _config_value("memory", "renderer", "provider")
MEMORY_RENDERER_PROVIDER = (
    str(_renderer_provider)
    if _renderer_provider is not None
    else MEMORY_EXTRACTOR_PROVIDER
)

_renderer_model = _config_value("memory", "renderer", "model")
MEMORY_RENDERER_MODEL = (
    str(_renderer_model) if _renderer_model is not None else MEMORY_EXTRACTOR_MODEL
)

MEMORY_RENDERER_PROMPT_PATH = _optional_path(
    "MEMORY_RENDERER_PROMPT_PATH", "memory", "renderer", "prompt_path"
)
if MEMORY_RENDERER_PROMPT_PATH is None:
    MEMORY_RENDERER_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "memory_render.md"

# System maintenance diagnosis (CLI execution logs + LLM call history)
SYSTEM_MAINTENANCE_PROVIDER = str(
    _env_or_config(
        "SYSTEM_MAINTENANCE_PROVIDER", "system_maintenance", "provider", default="openai"
    )
)
SYSTEM_MAINTENANCE_MODEL = str(
    _env_or_config(
        "SYSTEM_MAINTENANCE_MODEL", "system_maintenance", "model", default="gpt-5.6-terra"
    )
)
SYSTEM_MAINTENANCE_PROMPT_PATH = _optional_path(
    "SYSTEM_MAINTENANCE_PROMPT_PATH", "system_maintenance", "prompt_path"
)
if SYSTEM_MAINTENANCE_PROMPT_PATH is None:
    SYSTEM_MAINTENANCE_PROMPT_PATH = (
        BASE_DIR / "config" / "prompts" / "system_maintenance_diagnosis.md"
    )

SYSTEM_MAINTENANCE_WINDOW_HOURS = int(
    _env_or_config(
        "SYSTEM_MAINTENANCE_WINDOW_HOURS", "system_maintenance", "window_hours", default=24
    )
)
SYSTEM_MAINTENANCE_MAX_FINDINGS = int(
    _env_or_config(
        "SYSTEM_MAINTENANCE_MAX_FINDINGS", "system_maintenance", "max_findings", default=10
    )
)
SYSTEM_MAINTENANCE_STALE_RUNNING_HOURS = int(
    _env_or_config(
        "SYSTEM_MAINTENANCE_STALE_RUNNING_HOURS",
        "system_maintenance",
        "stale_running_hours",
        default=6,
    )
)
SYSTEM_MAINTENANCE_RESOLVE_MISSING_RUNS = int(
    _env_or_config(
        "SYSTEM_MAINTENANCE_RESOLVE_MISSING_RUNS",
        "system_maintenance",
        "resolve_missing_runs",
        default=3,
    )
)
SYSTEM_MAINTENANCE_MAX_TRACEBACK_CHARS = int(
    _env_or_config(
        "SYSTEM_MAINTENANCE_MAX_TRACEBACK_CHARS",
        "system_maintenance",
        "max_traceback_chars",
        default=4000,
    )
)
_raw_system_maintenance_project_id = _env_or_config(
    "SYSTEM_MAINTENANCE_PROJECT_ID", "system_maintenance", "project_id"
)
SYSTEM_MAINTENANCE_PROJECT_ID = (
    int(_raw_system_maintenance_project_id)
    if _raw_system_maintenance_project_id not in (None, "")
    else None
)

# Scheduler jobs directory and state files. ``OBSIDIAN_AI_HUB_JOBS_DIR`` lets
# an isolated instance keep recurring job definitions/state inside its sandbox.
_JOBS_DIR_RAW = os.getenv("OBSIDIAN_AI_HUB_JOBS_DIR")
JOBS_DIR = (
    Path(_JOBS_DIR_RAW).expanduser() if _JOBS_DIR_RAW else BASE_DIR / "jobs"
)
JOB_RUN_STATE_PATH = JOBS_DIR / "last_run.json"
KNOWLEDGE_SYNC_STATE_PATH = JOBS_DIR / "knowledge_sync_state.json"

# Healthcare (separate DB, never co-located with memory.sqlite3)
_HEALTHCARE_SQLITE_PATH_RAW = _optional_path(
    "HEALTHCARE_SQLITE_PATH", "healthcare", "sqlite_path"
)
_HEALTHCARE_EXPORT_DIR_RAW = _optional_path(
    "HEALTHCARE_EXPORT_DIR", "healthcare", "export_dir"
)
_HEALTHCARE_IMPORT_STAGING_DIR_RAW = _optional_path(
    "HEALTHCARE_IMPORT_STAGING_DIR", "healthcare", "import_staging_dir"
)
if IS_TEST_ENV:
    HEALTHCARE_SQLITE_PATH = TEST_WORKSPACE / "healthcare.sqlite3"
    HEALTHCARE_EXPORT_DIR = TEST_WORKSPACE / "healthcare_export"
    HEALTHCARE_IMPORT_STAGING_DIR = TEST_WORKSPACE / "healthcare" / "staging"
else:
    if _HEALTHCARE_SQLITE_PATH_RAW is not None:
        HEALTHCARE_SQLITE_PATH = _HEALTHCARE_SQLITE_PATH_RAW
    else:
        HEALTHCARE_SQLITE_PATH = Path(
            "~/.config/obsidian-ai-hub/healthcare.sqlite3"
        ).expanduser()
    if _HEALTHCARE_EXPORT_DIR_RAW is not None:
        HEALTHCARE_EXPORT_DIR = _HEALTHCARE_EXPORT_DIR_RAW
    else:
        HEALTHCARE_EXPORT_DIR = Path(
            "~/.config/obsidian-ai-hub/healthcare/apple_health_export"
        ).expanduser()
    if _HEALTHCARE_IMPORT_STAGING_DIR_RAW is not None:
        HEALTHCARE_IMPORT_STAGING_DIR = _HEALTHCARE_IMPORT_STAGING_DIR_RAW
    else:
        HEALTHCARE_IMPORT_STAGING_DIR = Path(
            "~/.config/obsidian-ai-hub/healthcare/staging"
        ).expanduser()

if IS_TEST_ENV:
    LOCAL_MODEL_DIR = TEST_WORKSPACE / "local-models"
    VAULT_INDEX_SQLITE_PATH = TEST_WORKSPACE / "vault-index" / "search.sqlite"
    VAULT_INDEX_CHROMA_PATH = TEST_WORKSPACE / "vault-index" / "chroma"
    JOBS_DIR = TEST_WORKSPACE / "jobs"
    JOB_RUN_STATE_PATH = JOBS_DIR / "last_run.json"
    KNOWLEDGE_SYNC_STATE_PATH = JOBS_DIR / "knowledge_sync_state.json"
    PLUGINS_TOOLS_DIR = TEST_WORKSPACE / "plugins" / "tools"
    AGENT_SKILLS_PRIMARY_ROOT = TEST_WORKSPACE / "primary_skills"
    AGENT_SKILLS_ROOT = TEST_WORKSPACE / "skills"
else:
    AGENT_SKILLS_PRIMARY_ROOT = Path("~/.agents/skills").expanduser()
    _skills_dir_raw = _env_or_config(
        "OBSIDIAN_AI_HUB_SKILLS_DIR", "agent_skills", "root"
    )
    if _skills_dir_raw:
        AGENT_SKILLS_ROOT = Path(str(_skills_dir_raw)).expanduser()
    else:
        AGENT_SKILLS_ROOT = Path(
            "~/.config/obsidian-ai-hub/skills"
        ).expanduser()
    _plugins_dir_raw = _env_or_config(
        "OBSIDIAN_AI_HUB_PLUGINS_DIR", "plugins", "tools_dir"
    )
    if _plugins_dir_raw:
        PLUGINS_TOOLS_DIR = Path(str(_plugins_dir_raw)).expanduser()
    else:
        PLUGINS_TOOLS_DIR = Path(
            "~/.config/obsidian-ai-hub/plugins/tools"
        ).expanduser()


# Image generation (OpenAI Images API). ``model`` is configurable so a new
# image model can be adopted without a code change. The output directory is
# deliberately outside the Vault by default; pointing it at a Vault subfolder
# makes generated media browsable in Obsidian.
IMAGE_GENERATION_MODEL = (
    str(
        _env_or_config(
            "IMAGE_GENERATION_MODEL",
            "image_generation",
            "model",
            default="gpt-image-2.5-sunburst",
        )
    ).strip()
    or "gpt-image-2.5-sunburst"
)
IMAGE_GENERATION_DEFAULT_SIZE = (
    str(
        _env_or_config(
            "IMAGE_GENERATION_DEFAULT_SIZE",
            "image_generation",
            "default_size",
            default="1024x1024",
        )
    ).strip()
    or "1024x1024"
)
IMAGE_GENERATION_DEFAULT_QUALITY = (
    str(
        _env_or_config(
            "IMAGE_GENERATION_DEFAULT_QUALITY",
            "image_generation",
            "default_quality",
            default="low",
        )
    ).strip()
    or "low"
)


def _positive_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


IMAGE_GENERATION_MAX_COUNT = _positive_int(
    _env_or_config(
        "IMAGE_GENERATION_MAX_COUNT", "image_generation", "max_count", default=4
    ),
    4,
)
IMAGE_GENERATION_TIMEOUT_SECONDS = _positive_int(
    _config_value("image_generation", "timeout_seconds", default=180),
    180,
)
# Upper bound for an input image ingested for editing (upload / path).
IMAGE_GENERATION_MAX_INPUT_BYTES = _positive_int(
    _env_or_config(
        "IMAGE_GENERATION_MAX_INPUT_BYTES",
        "image_generation",
        "max_input_bytes",
        default=8 * 1024 * 1024,
    ),
    8 * 1024 * 1024,
)

if IS_TEST_ENV:
    IMAGE_GENERATION_OUTPUT_DIR = TEST_WORKSPACE / "media"
    IMAGE_GENERATION_INPUT_DIR = TEST_WORKSPACE / "media-input"
else:
    _image_output_dir_raw = _env_or_config(
        "IMAGE_GENERATION_OUTPUT_DIR", "image_generation", "output_dir"
    )
    if _image_output_dir_raw:
        IMAGE_GENERATION_OUTPUT_DIR = Path(str(_image_output_dir_raw)).expanduser()
    else:
        IMAGE_GENERATION_OUTPUT_DIR = Path(
            "~/.config/obsidian-ai-hub/media"
        ).expanduser()
    # Root for resolving relative `source_path` inputs. Defaults to the Vault so
    # Vault-relative paths work like other vault tools.
    _image_input_dir_raw = _env_or_config(
        "IMAGE_GENERATION_INPUT_DIR", "image_generation", "input_dir"
    )
    if _image_input_dir_raw:
        IMAGE_GENERATION_INPUT_DIR = Path(str(_image_input_dir_raw)).expanduser()
    else:
        IMAGE_GENERATION_INPUT_DIR = VAULT_PATH

