from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────────────────────
    APP_ENV: str = "development"
    APP_VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str
    ADMIN_API_KEY: str

    # ── Model APIs ───────────────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str
    OPENAI_API_KEY: str
    QWEN_API_KEY: str
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    GEMINI_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # ── Telegram ─────────────────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_ALERT_CHAT_ID: str
    TELEGRAM_WEBHOOK_SECRET: str = ""

    # ── Facebook ─────────────────────────────────────────────────────────────────
    FB_PAGE_ID: str = ""
    FB_PAGE_ACCESS_TOKEN: str = ""

    # ── Database ─────────────────────────────────────────────────────────────────
    DATABASE_URL: str

    # ── Supabase ─────────────────────────────────────────────────────────────────
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""

    # ── Redis ────────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── JWT ──────────────────────────────────────────────────────────────────────
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # ── Cost limits ──────────────────────────────────────────────────────────────
    DEFAULT_DAILY_BUDGET_USD: float = 5.00
    GLOBAL_DAILY_BUDGET_USD: float = 50.00

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
