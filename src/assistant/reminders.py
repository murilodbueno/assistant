from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from .business import Business
from .config import Settings
from .store import Store
from .whatsapp import WhatsAppClient

log = logging.getLogger("assistant.reminders")


async def reminder_loop(
    settings: Settings,
    store: Store,
    whatsapp: WhatsAppClient,
    business_getter: Callable[[], Business],
    *,
    interval_sec: float = 300,
) -> None:
    while True:
        try:
            _send_due_reminders(settings, store, whatsapp, business_getter())
        except Exception:
            log.exception("Reminder loop error")
        await asyncio.sleep(interval_sec)


def _send_due_reminders(
    settings: Settings,
    store: Store,
    whatsapp: WhatsAppClient,
    business: Business,
) -> None:
    tz = settings.tz
    now = datetime.now(tz)
    if not (settings.reminder_start_hour <= now.hour < settings.reminder_end_hour):
        return
    tomorrow = (now + timedelta(days=1)).date()
    start = datetime.combine(tomorrow, datetime.min.time(), tzinfo=tz).timestamp()
    end = datetime.combine(tomorrow + timedelta(days=1), datetime.min.time(), tzinfo=tz).timestamp()
    for appt in store.appointments_between(start, end):
        if store.reminder_sent(appt.id):
            continue
        when = datetime.fromtimestamp(appt.start_ts, tz).strftime("%d/%m as %H:%M")
        text = (
            f"Ola! Lembrete do {business.name}: amanha ({when}) "
            f"{appt.service} — {appt.pet_name}.\n"
            f"Responda CONFIRMAR ou REMARCAR."
        )
        if whatsapp.send_text(appt.phone, text):
            store.mark_reminder_sent(appt.id)
            log.info("Reminder sent for appointment %s", appt.id)
