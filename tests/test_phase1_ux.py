from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from assistant.agents.router import classify_intent
from assistant.booking_state import format_proposal, is_confirmation, try_confirm_pending
from assistant.business import load_business
from assistant.calendar import CalendarClient
from assistant.config import Settings
from assistant.orchestrator import Orchestrator
from assistant.store import Store
from assistant.tools import price_reply
from assistant.whatsapp import WhatsAppClient


def _settings(db: Path, biz: Path) -> Settings:
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
        debounce_sec=0.0,
        reminder_start_hour=9,
        reminder_end_hour=19,
        business_file=biz,
        db_path=db,
        timezone="America/Sao_Paulo",
    )


def test_router_price_before_booking():
    root = Path(__file__).resolve().parents[1]
    biz = load_business(root / "business" / "pet_shop.yaml")
    s = _settings(root / "data" / "t.db", root / "business" / "pet_shop.yaml")
    assert classify_intent(s, biz, "quanto custa banho?", []) == "faq"
    assert classify_intent(s, biz, "preco da tosa", []) == "faq"
    assert classify_intent(s, biz, "quero marcar banho", []) == "agendar"


def test_price_reply_without_llm():
    root = Path(__file__).resolve().parents[1]
    biz = load_business(root / "business" / "pet_shop.yaml")
    reply = price_reply(biz, "quanto custa banho?")
    assert reply is not None
    assert "R$ 50" in reply
    assert "R$ 70" in reply


def test_faq_catalog_without_llm(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    biz_path = root / "business" / "pet_shop.yaml"
    settings = _settings(tmp_path / "orch.db", biz_path)
    store = Store(settings.db_path)
    store.init_db()
    orch = Orchestrator(settings, load_business(biz_path), store, CalendarClient(settings), WhatsAppClient(settings))
    reply = orch.process_message("5511888888888", "voces buscam o pet em casa?")
    assert "nao no momento" in reply.lower()


def test_booking_requires_confirmation(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    biz_path = root / "business" / "pet_shop.yaml"
    settings = _settings(tmp_path / "book.db", biz_path)
    store = Store(settings.db_path)
    store.init_db()
    biz = load_business(biz_path)
    orch = Orchestrator(settings, biz, store, CalendarClient(settings), WhatsAppClient(settings))
    phone = "5511888888888"

    propose = {
        "reply": "Confirmar?",
        "action": "propose",
        "service": "Banho",
        "size": "grande",
        "subject_name": "Thor",
        "day": "2026-10-09",
        "time": "14:00",
    }
    with patch("assistant.agents.router.chat_json", return_value={"intent": "agendar"}), patch(
        "assistant.agents.scheduler.chat_json", return_value=propose
    ):
        reply = orch.process_message(phone, "quero banho pro Thor grande sexta 14h")
    assert "confirmar" in reply.lower()
    assert store.find_active_appointment(phone) is None

    confirm = orch.process_message(phone, "sim")
    assert "agendado" in confirm.lower()
    assert store.find_active_appointment(phone) is not None


def test_booking_rejection_clears_pending(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    biz_path = root / "business" / "pet_shop.yaml"
    settings = _settings(tmp_path / "reject.db", biz_path)
    store = Store(settings.db_path)
    store.init_db()
    biz = load_business(biz_path)
    calendar = CalendarClient(settings)
    phone = "5511888888888"
    start = datetime(2026, 10, 10, 14, 0, tzinfo=settings.tz)
    from assistant.booking_state import set_pending

    set_pending(
        store,
        phone,
        {"service": "Banho", "size": "grande", "subject": "Thor", "start_iso": start.isoformat(), "preco": 90},
    )
    reply = try_confirm_pending(settings, biz, store, calendar, phone, "nao")
    assert reply is not None
    assert "nao confirmei" in reply.lower()
    assert store.get_state(phone).get("booking_pending") is None


def test_is_confirmation():
    assert is_confirmation("sim")
    assert is_confirmation("Confirmo")
    assert not is_confirmation("sim, mas outro horario")
