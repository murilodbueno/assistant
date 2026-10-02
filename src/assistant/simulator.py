from __future__ import annotations

import logging
import sys

from .business import load_business
from .calendar import CalendarClient
from .config import load_settings
from .orchestrator import Orchestrator
from .store import Store
from .whatsapp import WhatsAppClient

logging.basicConfig(level=logging.WARNING)


class _PrintWhatsApp(WhatsAppClient):
    def send_text(self, phone: str, text: str) -> bool:
        print(f"\n[bot -> {phone}]\n{text}\n")
        return True


def main() -> None:
    settings = load_settings()
    business = load_business(settings.business_file)
    store = Store(settings.db_path)
    store.init_db()
    calendar = CalendarClient(settings)
    whatsapp = _PrintWhatsApp(settings)
    orchestrator = Orchestrator(settings, business, store, calendar, whatsapp)
    print(f"Simulador — {business.name} [{business.segment}]")
    print(f"Template: {settings.business_file}")
    print("Digite como cliente (ou 'sair'). Telefone simulado: 5511999999999")
    phone = "5511999999999"
    while True:
        try:
            line = input("\n[cliente] ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in ("sair", "exit", "quit"):
            break
        reply = orchestrator.process_message(phone, line)
        store.add_message(phone, "user", line)
        store.add_message(phone, "assistant", reply)
        whatsapp.send_text(phone, reply)


if __name__ == "__main__":
    main()
    sys.exit(0)
