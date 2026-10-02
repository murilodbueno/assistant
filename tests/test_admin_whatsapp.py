from pathlib import Path
from unittest.mock import patch

import yaml

from petshop.business import load_business
from petshop.calendar import CalendarClient
from petshop.config import Settings
from petshop.orchestrator import Orchestrator
from petshop.setup.admin import WhatsAppAdmin
from petshop.store import Store
from petshop.whatsapp import WhatsAppClient


def _settings(tmp_path: Path, business_file: Path) -> Settings:
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
        owner_phone="5511999887766",
        bot_pause_hours=12.0,
        debounce_sec=0.1,
        reminder_start_hour=9,
        reminder_end_hour=19,
        business_file=business_file,
        db_path=tmp_path / "admin.db",
        timezone="America/Sao_Paulo",
    )


def _copy_business_template(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parents[1] / "business" / "pet_shop.yaml"
    dst = tmp_path / "business.yaml"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dst


def test_admin_menu_and_quick_price(tmp_path: Path):
    biz_path = _copy_business_template(tmp_path)
    settings = _settings(tmp_path, biz_path)
    store = Store(settings.db_path)
    store.init_db()
    admin = WhatsAppAdmin(settings, store)
    owner = "5511999887766"

    menu = admin.handle(owner, "configurar")
    assert menu.handled
    assert "Painel de configuracao" in menu.reply

    result = admin.handle(owner, "preco Banho pequeno 55")
    assert result.reload_business
    data = yaml.safe_load(biz_path.read_text(encoding="utf-8"))
    banho = next(s for s in data["servicos"] if s["nome"] == "Banho")
    assert banho["precos"]["pequeno"] == 55


def test_admin_add_faq(tmp_path: Path):
    biz_path = _copy_business_template(tmp_path)
    settings = _settings(tmp_path, biz_path)
    store = Store(settings.db_path)
    store.init_db()
    admin = WhatsAppAdmin(settings, store)
    owner = "5511999887766"

    admin.handle(owner, "configurar")
    admin.handle(owner, "5")
    result = admin.handle(owner, "Aceita cartao? | Sim, debito e credito")
    assert result.reload_business
    data = yaml.safe_load(biz_path.read_text(encoding="utf-8"))
    assert any("cartao" in item["pergunta"].lower() for item in data["faq"])


@patch("petshop.agents.router.chat_json", return_value={"intent": "outro"})
def test_owner_config_does_not_go_to_clients(_mock, tmp_path: Path):
    biz_path = _copy_business_template(tmp_path)
    settings = _settings(tmp_path, biz_path)
    store = Store(settings.db_path)
    store.init_db()
    orch = Orchestrator(settings, load_business(biz_path), store, CalendarClient(settings), WhatsAppClient(settings))
    sent: list[tuple[str, str]] = []

    class CaptureWhatsApp(WhatsAppClient):
        def send_text(self, phone: str, text: str) -> bool:
            sent.append((phone, text))
            return True

    orch.whatsapp = CaptureWhatsApp(settings)
    reply = orch._handle_owner("5511999887766", "configurar")
    assert reply is not None
    assert "Painel" in reply
    assert not any(phone != "5511999887766" for phone, _ in sent)


def test_orchestrator_reload_after_price_change(tmp_path: Path):
    biz_path = _copy_business_template(tmp_path)
    settings = _settings(tmp_path, biz_path)
    store = Store(settings.db_path)
    store.init_db()
    orch = Orchestrator(settings, load_business(biz_path), store, CalendarClient(settings), WhatsAppClient(settings))
    before = orch.business.service("Banho").prices["pequeno"]
    orch._handle_owner("5511999887766", "preco Banho pequeno 99")
    after = orch.business.service("Banho").prices["pequeno"]
    assert before != after
    assert after == 99
