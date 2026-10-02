from pathlib import Path
from unittest.mock import patch

from petshop.business import load_business
from petshop.calendar import CalendarClient
from petshop.config import Settings
from petshop.orchestrator import Orchestrator
from petshop.store import Store
from petshop.whatsapp import WhatsAppClient


def _settings() -> Settings:
    return Settings(
        llm_api_key="",
        llm_base_url="https://example.com/v1",
        llm_model="test-model",
        llm_timeout_sec=5.0,
        fallback_api_key="",
        fallback_base_url="https://example.com/v1",
        fallback_model="",
        fallback_timeout_sec=5.0,
        waha_url="http://localhost:3000",
        waha_api_key="",
        waha_session="default",
        waha_hmac_key="",
        google_service_account_file=Path("/nonexistent/fake.json"),
        google_calendar_id="",
        owner_phone="",
        bot_pause_hours=12.0,
        debounce_sec=6.0,
        reminder_start_hour=9,
        reminder_end_hour=19,
        business_file=Path("business/pet_shop.yaml"),
        db_path=Path("data/test-orch.db"),
        timezone="America/Sao_Paulo",
    )


def test_greeting(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    settings = _settings()
    settings = Settings(**{**settings.__dict__, "db_path": tmp_path / "orch.db"})
    business = load_business(root / "business" / "pet_shop.yaml")
    store = Store(settings.db_path)
    store.init_db()
    orch = Orchestrator(settings, business, store, CalendarClient(settings), WhatsAppClient(settings))
    reply = orch.process_message("5511888888888", "oi")
    assert "Pet Shop Exemplo" in reply


def test_price_question_without_llm(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    settings = _settings()
    settings = Settings(**{**settings.__dict__, "db_path": tmp_path / "orch2.db"})
    business = load_business(root / "business" / "pet_shop.yaml")
    store = Store(settings.db_path)
    store.init_db()
    orch = Orchestrator(settings, business, store, CalendarClient(settings), WhatsAppClient(settings))
    reply = orch.process_message("5511888888888", "quanto custa banho?")
    assert "R$ 50" in reply
