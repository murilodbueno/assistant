from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw is None or raw.strip() == "" else float(raw)


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw is None or raw.strip() == "" else int(raw)


def _path(name: str, default: str) -> Path:
    path = Path(os.getenv(name, "").strip() or default)
    return path if path.is_absolute() else ROOT / path


def _digits(raw: str) -> str:
    return "".join(ch for ch in raw if ch.isdigit())


@dataclass(frozen=True)
class Settings:
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    llm_timeout_sec: float
    fallback_api_key: str
    fallback_base_url: str
    fallback_model: str
    fallback_timeout_sec: float
    waha_url: str
    waha_api_key: str
    waha_session: str
    waha_hmac_key: str
    google_service_account_file: Path
    google_calendar_id: str
    owner_phone: str
    bot_pause_hours: float
    debounce_sec: float
    reminder_start_hour: int
    reminder_end_hour: int
    business_file: Path
    db_path: Path
    timezone: str

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def fallback_enabled(self) -> bool:
        return bool(self.fallback_api_key.strip() and self.fallback_model.strip())

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_calendar_id) and self.google_service_account_file.is_file()


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    return Settings(
        llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
        llm_base_url=(os.getenv("LLM_BASE_URL", "").strip() or "https://ai-gateway.vercel.sh/v1").rstrip("/"),
        llm_model=os.getenv("LLM_MODEL", "").strip() or "openai/gpt-4.1-mini",
        llm_timeout_sec=_float("LLM_TIMEOUT_SEC", 30.0),
        fallback_api_key=os.getenv("FALLBACK_LLM_API_KEY", "").strip(),
        fallback_base_url=(
            os.getenv("FALLBACK_LLM_BASE_URL", "").strip() or "https://integrate.api.nvidia.com/v1"
        ).rstrip("/"),
        fallback_model=os.getenv("FALLBACK_LLM_MODEL", "").strip(),
        fallback_timeout_sec=_float("FALLBACK_LLM_TIMEOUT_SEC", 30.0),
        waha_url=(os.getenv("WAHA_URL", "").strip() or "http://waha:3000").rstrip("/"),
        waha_api_key=os.getenv("WAHA_API_KEY", "").strip(),
        waha_session=os.getenv("WAHA_SESSION", "").strip() or "default",
        waha_hmac_key=os.getenv("WAHA_HMAC_KEY", "").strip(),
        google_service_account_file=_path("GOOGLE_SERVICE_ACCOUNT_FILE", "secrets/google-service-account.json"),
        google_calendar_id=os.getenv("GOOGLE_CALENDAR_ID", "").strip(),
        owner_phone=_digits(os.getenv("OWNER_PHONE", "")),
        bot_pause_hours=_float("BOT_PAUSE_HOURS", 12.0),
        debounce_sec=_float("DEBOUNCE_SEC", 2.0),
        reminder_start_hour=_int("REMINDER_START_HOUR", 9),
        reminder_end_hour=_int("REMINDER_END_HOUR", 19),
        business_file=_path("BUSINESS_FILE", "business/pet_shop.yaml"),
        db_path=_path("DB_PATH", "data/petshop.db"),
        timezone=os.getenv("TIMEZONE", "").strip() or "America/Sao_Paulo",
    )
