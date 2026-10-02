from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from .agents import classify_intent, run_faq, run_handoff, run_scheduler
from datetime import datetime

from .booking_draft import get_draft, is_booking_followup, set_draft
from .booking_state import try_confirm_pending, try_reminder_reply
from .business import Business, load_business
from .calendar import CalendarClient
from .config import Settings
from .setup.admin import WhatsAppAdmin
from .store import Store
from .whatsapp import WhatsAppClient

log = logging.getLogger("petshop.orchestrator")


@dataclass
class Orchestrator:
    settings: Settings
    business: Business
    store: Store
    calendar: CalendarClient
    whatsapp: WhatsAppClient
    admin: WhatsAppAdmin | None = None
    on_business_reload: Callable[[Business], None] | None = None
    _pending: dict[str, asyncio.Task] = field(default_factory=dict)
    _buffers: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.admin is None:
            self.admin = WhatsAppAdmin(self.settings, self.store)

    def reload_business(self) -> None:
        self.business = load_business(self.settings.business_file)
        if self.on_business_reload:
            self.on_business_reload(self.business)
        log.info("Business config reloaded from %s", self.settings.business_file)

    async def handle_webhook_message(self, phone: str, text: str) -> str | None:
        if self._is_owner(phone):
            reply = self._handle_owner(phone, text)
            if reply:
                self.whatsapp.send_text(phone, reply)
            return reply
        if self.store.is_paused(phone):
            log.info("Conversation paused for %s", phone)
            return None
        return await self._debounced_reply(phone, text)

    def _is_owner(self, phone: str) -> bool:
        owner = self.settings.owner_phone
        if not owner:
            return False

        def digits(p: str) -> str:
            return "".join(ch for ch in p if ch.isdigit())

        return digits(phone).endswith(digits(owner)[-11:])

    def _handle_owner(self, phone: str, text: str) -> str | None:
        assert self.admin is not None
        result = self.admin.handle(phone, text)
        if result.handled:
            if result.reload_business:
                self.reload_business()
            return result.reply or None
        row = self.store.latest_open_handoff()
        if row is None:
            return None
        client_phone = str(row["client_phone"])
        self.store.resolve_handoff(int(row["id"]), text)
        self.whatsapp.send_text(client_phone, text)
        pause_until = time.time() + self.settings.bot_pause_hours * 3600
        self.store.pause(client_phone, pause_until)
        return None

    async def _debounced_reply(self, phone: str, text: str) -> str | None:
        self._buffers.setdefault(phone, []).append(text)
        if phone in self._pending:
            self._pending[phone].cancel()
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._flush_after_delay(phone))
        self._pending[phone] = task
        try:
            return await task
        except asyncio.CancelledError:
            return None

    async def _flush_after_delay(self, phone: str) -> str:
        await asyncio.sleep(self.settings.debounce_sec)
        parts = self._buffers.pop(phone, [])
        self._pending.pop(phone, None)
        if not parts:
            return ""
        message = "\n".join(parts)
        reply = self.process_message(phone, message)
        self.store.add_message(phone, "user", message)
        self.store.add_message(phone, "assistant", reply)
        self.whatsapp.send_text(phone, reply)
        return reply

    def process_message(self, phone: str, message: str) -> str:
        reminder = try_reminder_reply(self.settings, self.store, phone, message, self.business)
        if reminder is not None:
            return reminder

        confirmed = try_confirm_pending(
            self.settings, self.business, self.store, self.calendar, phone, message
        )
        if confirmed is not None:
            return confirmed

        today = datetime.now(self.settings.tz).date()
        draft = get_draft(self.store, phone)
        if draft and is_booking_followup(message, self.business, draft, today=today):
            return run_scheduler(
                self.settings,
                self.business,
                self.store,
                self.calendar,
                phone,
                message,
                self.store.recent_messages(phone),
                "agendar",
            )

        history = self.store.recent_messages(phone)
        intent = classify_intent(self.settings, self.business, message, history)

        if draft and intent not in ("agendar", "remarcar", "cancelar", "confirmar_lembrete"):
            set_draft(self.store, phone, None)

        if intent == "humano":
            return run_handoff(self.settings, self.store, self.whatsapp, client_phone=phone, question=message)

        if intent in ("agendar", "remarcar", "cancelar", "confirmar_lembrete"):
            return run_scheduler(
                self.settings,
                self.business,
                self.store,
                self.calendar,
                phone,
                message,
                history,
                intent,
            )

        if intent == "faq":
            reply, needs_handoff = run_faq(self.settings, self.business, message, history)
            if needs_handoff:
                return run_handoff(self.settings, self.store, self.whatsapp, client_phone=phone, question=message)
            return reply

        if intent == "outro":
            lowered = message.lower().strip()
            if lowered in ("oi", "ola", "bom dia", "boa tarde", "boa noite"):
                return f"Ola! Sou a assistente do {self.business.name}. {self.business.greeting}"
            reply, needs_handoff = run_faq(self.settings, self.business, message, history)
            if needs_handoff:
                return run_handoff(self.settings, self.store, self.whatsapp, client_phone=phone, question=message)
            return reply

        return f"Como posso ajudar? {self.business.greeting}"
