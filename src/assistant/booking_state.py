from __future__ import annotations

from datetime import datetime
from typing import Any

from .business import Business, normalize
from .calendar import CalendarClient
from .config import Settings
from .store import Store
from .tools import create_booking

CONFIRM_WORDS = frozenset({"sim", "confirmo", "confirmar", "ok", "pode ser", "isso", "certo", "fechado"})
REJECT_WORDS = frozenset({"nao", "não", "cancela", "cancelar", "outro", "mudar"})
REMINDER_CONFIRM = frozenset({"confirmar", "confirmo", "confirmed"})


def is_confirmation(message: str) -> bool:
    lowered = normalize(message)
    return lowered in CONFIRM_WORDS or lowered.startswith("sim ") or lowered == "s"


def is_rejection(message: str) -> bool:
    lowered = normalize(message)
    return lowered in REJECT_WORDS or lowered.startswith("nao") or lowered.startswith("não")


def get_pending(store: Store, phone: str) -> dict[str, Any] | None:
    pending = store.get_state(phone).get("booking_pending")
    return pending if isinstance(pending, dict) else None


def set_pending(store: Store, phone: str, pending: dict[str, Any] | None) -> None:
    state = store.get_state(phone)
    if pending is None:
        state.pop("booking_pending", None)
    else:
        state["booking_pending"] = pending
    store.set_state(phone, state)


def format_proposal(
    business: Business,
    *,
    subject: str,
    service: str,
    size: str,
    start: datetime,
    preco: float | None,
) -> str:
    when = start.strftime("%d/%m as %H:%M")
    msg = (
        f"Confirmar agendamento?\n"
        f"  {service} — {subject} ({size})\n"
        f"  {when}"
    )
    if preco is not None:
        msg += f"\n  Valor estimado: R$ {preco:.0f}"
    msg += "\n\nResponda *SIM* para confirmar ou *NAO* para cancelar."
    return msg


def try_reminder_reply(
    settings: Settings,
    store: Store,
    phone: str,
    message: str,
    business: Business,
) -> str | None:
    appt = store.find_active_appointment(phone)
    if appt is None:
        return None
    lowered = normalize(message)
    if lowered in REMINDER_CONFIRM:
        when = datetime.fromtimestamp(appt.start_ts, settings.tz).strftime("%d/%m as %H:%M")
        return (
            f"Presenca confirmada! Te esperamos em {when} para {appt.service} — {appt.pet_name}."
        )
    if lowered == "remarcar" or lowered.startswith("remarcar "):
        return "Para remarcar, informe o novo dia e horario (ex.: sexta as 14h)."
    return None


def try_confirm_pending(
    settings: Settings,
    business: Business,
    store: Store,
    calendar: CalendarClient,
    phone: str,
    message: str,
) -> str | None:
    pending = get_pending(store, phone)
    if pending is None:
        return None
    if is_confirmation(message):
        start = datetime.fromisoformat(str(pending["start_iso"])).replace(tzinfo=settings.tz)
        result = create_booking(
            store=store,
            calendar=calendar,
            business=business,
            phone=phone,
            pet_name=str(pending["subject"]),
            service_name=str(pending["service"]),
            size_name=str(pending["size"]),
            start=start,
        )
        if not result.get("ok"):
            return f"Nao foi possivel confirmar: {result.get('error')}"
        set_pending(store, phone, None)
        from .booking_draft import set_draft

        set_draft(store, phone, None)
        return (
            f"Agendado! {pending['subject']} — {pending['service']} "
            f"em {start.strftime('%d/%m as %H:%M')}."
        )
    if is_rejection(message):
        set_pending(store, phone, None)
        return "Ok, nao confirmei. Quer escolher outro horario?"
    return None
