from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from petshop.agents.router import classify_intent
from petshop.agents.scheduler import run_scheduler
from petshop.booking_state import get_pending
from petshop.booking_draft import (
    advance_booking,
    detect_period,
    extract_hints,
    filter_slots_by_period,
    get_draft,
    merge_draft,
)
from petshop.business import load_business
from petshop.calendar import CalendarClient, Slot
from petshop.config import Settings
from petshop.orchestrator import Orchestrator
from petshop.store import Store
from petshop.whatsapp import WhatsAppClient


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
        debounce_sec=2.0,
        reminder_start_hour=9,
        reminder_end_hour=19,
        business_file=biz,
        db_path=db,
        timezone="America/Sao_Paulo",
    )


def test_extract_hints_from_message():
    root = Path(__file__).resolve().parents[1]
    biz = load_business(root / "business" / "pet_shop.yaml")
    friday = date(2026, 10, 2)
    hints = extract_hints("quero banho pro Thor, cachorro grande, sexta a tarde", biz, today=friday - timedelta(days=1))
    assert hints["service"] == "Banho"
    assert hints["size"] == "grande"
    assert hints["subject"] == "Thor"
    assert hints["period"] == "tarde"
    assert hints["day"] == friday.isoformat()


def test_filter_afternoon_slots():
    base = date(2026, 10, 2)
    slots = [
        Slot(start=__import__("datetime").datetime(2026, 10, 2, 9, 0), end=__import__("datetime").datetime(2026, 10, 2, 10, 0)),
        Slot(start=__import__("datetime").datetime(2026, 10, 2, 14, 0), end=__import__("datetime").datetime(2026, 10, 2, 15, 0)),
    ]
    afternoon = filter_slots_by_period(slots, "tarde")
    assert len(afternoon) == 1
    assert afternoon[0].start.hour == 14


def test_booking_flow_without_llm(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    biz_path = root / "business" / "pet_shop.yaml"
    settings = _settings(tmp_path / "flow.db", biz_path)
    store = Store(settings.db_path)
    store.init_db()
    biz = load_business(biz_path)
    calendar = CalendarClient(settings)
    orch = Orchestrator(settings, biz, store, calendar, WhatsAppClient(settings))
    phone = "5511888888888"

    # Sexta 2026-10-02 e um dia aberto no YAML
    r1 = orch.process_message(phone, "quero banho pro Thor, grande, sexta a tarde")
    assert "horarios" in r1.lower() or "14:" in r1
    assert "08:00" not in r1 or "14:" in r1

    draft = get_draft(store, phone)
    assert draft.get("subject") == "Thor"
    assert draft.get("size") == "grande"

    r2 = orch.process_message(phone, "14h")
    assert "confirmar" in r2.lower()

    r3 = orch.process_message(phone, "sim")
    assert "agendado" in r3.lower()
    assert store.find_active_appointment(phone) is not None


def test_debounce_default_is_two():
    root = Path(__file__).resolve().parents[1]
    settings = _settings(root / "data" / "x.db", root / "business" / "pet_shop.yaml")
    assert settings.debounce_sec == 2.0


def test_faq_question_is_not_booking_followup():
    root = Path(__file__).resolve().parents[1]
    biz = load_business(root / "business" / "pet_shop.yaml")
    draft = {
        "service": "Banho",
        "size": "grande",
        "subject": "Thor",
        "day": "2026-10-02",
        "period": "tarde",
    }
    from petshop.booking_draft import is_booking_followup

    assert not is_booking_followup("faz tosa de poodle estilo exposicao?", biz, draft)


def test_draft_memory_across_turns(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    biz = load_business(root / "business" / "pet_shop.yaml")
    settings = _settings(tmp_path / "draft.db", root / "business" / "pet_shop.yaml")
    store = Store(settings.db_path)
    store.init_db()
    calendar = CalendarClient(settings)
    phone = "5511999999999"

    draft = merge_draft({}, extract_hints("quero banho pro Mel", biz, today=date(2026, 10, 1)))
    draft = merge_draft(draft, extract_hints("grande", biz, today=date(2026, 10, 1)))
    draft = merge_draft(draft, extract_hints("sexta a tarde", biz, today=date(2026, 10, 1)))
    assert draft["subject"] == "Mel"
    assert draft["size"] == "grande"
    assert draft["period"] == "tarde"

    reply = advance_booking(settings, biz, store, calendar, phone, draft)
    assert "horario" in reply.lower()


def test_list_slots_with_time_proposes_instead(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    biz_path = root / "business" / "pet_shop.yaml"
    settings = _settings(tmp_path / "propose.db", biz_path)
    store = Store(settings.db_path)
    store.init_db()
    biz = load_business(biz_path)
    calendar = CalendarClient(settings)
    phone = "5511777777777"
    day = date(2026, 10, 2).isoformat()

    draft = {
        "service": "Banho",
        "size": "grande",
        "subject": "Thor",
        "day": day,
        "period": "tarde",
        "time": "14:00",
    }
    store.set_state(phone, {"booking_draft": draft})

    llm_reply = {
        "reply": "Horarios na sexta:",
        "action": "list_slots",
        "day": day,
    }
    with patch("petshop.agents.scheduler.chat_json", return_value=llm_reply):
        reply = run_scheduler(settings, biz, store, calendar, phone, "pode ser as 14h", [], "agendar")

    assert "confirmar" in reply.lower()
    assert get_pending(store, phone) is not None
    assert get_draft(store, phone) == {}


def test_reject_unavailable_time(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    biz_path = root / "business" / "pet_shop.yaml"
    settings = _settings(tmp_path / "badtime.db", biz_path)
    store = Store(settings.db_path)
    store.init_db()
    biz = load_business(biz_path)
    calendar = CalendarClient(settings)
    phone = "5511666666666"
    day = date(2026, 10, 2).isoformat()

    draft = {
        "service": "Banho",
        "size": "grande",
        "subject": "Thor",
        "day": day,
        "time": "03:00",
    }
    reply = advance_booking(settings, biz, store, calendar, phone, draft)
    assert "nao esta disponivel" in reply.lower() or "nao ha horarios" in reply.lower()
    assert get_pending(store, phone) is None


def test_extract_size_ignores_substring():
    root = Path(__file__).resolve().parents[1]
    biz = load_business(root / "business" / "pet_shop.yaml")
    hints = extract_hints("preciso agendar imediato para o Rex", biz, today=date(2026, 10, 1))
    assert "size" not in hints


def test_reminder_confirmar_reply(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    settings = _settings(tmp_path / "reminder.db", root / "business" / "pet_shop.yaml")
    store = Store(settings.db_path)
    store.init_db()
    biz = load_business(root / "business" / "pet_shop.yaml")
    orch = Orchestrator(settings, biz, store, CalendarClient(settings), WhatsAppClient(settings))
    phone = "5511555555555"
    start = __import__("datetime").datetime(2026, 10, 3, 14, 0, tzinfo=settings.tz)
    store.create_appointment(
        phone=phone,
        pet_name="Thor",
        service="Banho",
        size="grande",
        start_ts=start.timestamp(),
        end_ts=start.timestamp() + 3600,
    )
    reply = orch.process_message(phone, "confirmar")
    assert "confirmada" in reply.lower() or "esperamos" in reply.lower()


def test_busy_slot_blocks_double_booking(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    biz = load_business(root / "business" / "pet_shop.yaml")
    settings = _settings(tmp_path / "busy.db", root / "business" / "pet_shop.yaml")
    store = Store(settings.db_path)
    store.init_db()
    calendar = CalendarClient(settings)
    day = date(2026, 10, 2)
    start = __import__("datetime").datetime(2026, 10, 2, 14, 0, tzinfo=settings.tz)
    store.create_appointment(
        phone="5511111111111",
        pet_name="A",
        service="Banho",
        size="grande",
        start_ts=start.timestamp(),
        end_ts=start.timestamp() + 5400,
    )
    slots = __import__("petshop.tools", fromlist=["available_slots"]).available_slots(
        biz, calendar, service_name="Banho", size_name="grande", day=day, limit=12, store=store
    )
    assert isinstance(slots, list)
    assert not any(s.start.hour == 14 and s.start.minute == 0 for s in slots)
