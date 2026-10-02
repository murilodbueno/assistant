from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from ..booking_draft import (
    advance_booking,
    extract_hints,
    get_draft,
    merge_draft,
    merge_llm_data,
    set_draft,
)
from ..booking_state import get_pending, set_pending
from ..business import Business
from ..calendar import CalendarClient
from ..config import Settings
from ..llm import chat_json
from ..store import Store
from ..tools import available_slots, cancel_booking, reschedule_booking

log = logging.getLogger("assistant.scheduler")


def _system_prompt(business: Business) -> str:
    variants = ", ".join(business.sizes.keys())
    return (
        f"Voce agenda servicos em um(a) {business.kind}.\n"
        "Responda JSON com campos:\n"
        "- reply: mensagem ao cliente em portugues\n"
        "- action: null | list_slots | propose | reschedule | cancel\n"
        f"- service, size ({variants}), subject_name, day (YYYY-MM-DD), time (HH:MM), appointment_id\n\n"
        f"Regras:\n"
        f"- Reutilize dados ja conhecidos do rascunho de agendamento.\n"
        f"- Colete servico, {business.variant_label}, {business.subject_label} e data/hora.\n"
        "- Use action=propose somente quando tiver todos os dados.\n"
        "- Se faltar dado, action=null."
    )


def run_scheduler(
    settings: Settings,
    business: Business,
    store: Store,
    calendar: CalendarClient,
    phone: str,
    message: str,
    history: list[dict[str, str]],
    intent: str,
) -> str:
    appt = store.find_active_appointment(phone)
    if intent == "cancelar" and appt:
        cancel_booking(store=store, calendar=calendar, appointment_id=appt.id)
        set_pending(store, phone, None)
        set_draft(store, phone, None)
        return "Agendamento cancelado. Se quiser, posso marcar outro horario."

    if intent == "remarcar" and appt:
        return _reschedule_with_llm(settings, business, store, calendar, phone, message, history, appt)

    draft = get_draft(store, phone)
    hints = extract_hints(message, business, today=datetime.now(settings.tz).date())
    draft = merge_draft(draft, hints)

    data = _call_scheduler_llm(settings, business, store, phone, message, history, intent, draft)
    if data:
        draft = merge_draft(draft, merge_llm_data(data))
        action = data.get("action")
        if action == "book":
            action = "propose"
        reply = str(data.get("reply") or "").strip()

        if action == "cancel" and appt:
            cancel_booking(store=store, calendar=calendar, appointment_id=appt.id)
            set_draft(store, phone, None)
            return "Agendamento cancelado."

        if action == "list_slots" and draft.get("day"):
            set_draft(store, phone, draft)
            if _draft_ready_for_propose(draft):
                return advance_booking(settings, business, store, calendar, phone, draft)
            slots_reply = _list_slots_reply(settings, business, store, calendar, draft, reply)
            if slots_reply:
                return slots_reply

        if action in ("propose", "book") and _draft_ready_for_propose(draft):
            set_draft(store, phone, draft)
            return advance_booking(settings, business, store, calendar, phone, draft)

        if action is None and reply:
            set_draft(store, phone, draft)
            if _draft_ready_for_propose(draft) and not draft.get("time"):
                slots_reply = _list_slots_reply(settings, business, store, calendar, draft, "")
                if slots_reply:
                    return slots_reply
            return reply

    set_draft(store, phone, draft)
    return advance_booking(settings, business, store, calendar, phone, draft)


def _call_scheduler_llm(
    settings: Settings,
    business: Business,
    store: Store,
    phone: str,
    message: str,
    history: list[dict[str, str]],
    intent: str,
    draft: dict[str, Any],
) -> dict[str, Any] | None:
    appt = store.find_active_appointment(phone)
    context: dict[str, Any] = {
        "intent": intent,
        "rascunho": draft,
        "agendamento_ativo": None if appt is None else {
            "id": appt.id,
            "servico": appt.service,
            "sujeito": appt.pet_name,
            "variante": appt.size,
        },
        "proposta_pendente": get_pending(store, phone),
        "servicos": [s.name for s in business.services],
        "variantes": list(business.sizes.keys()),
    }
    messages = [
        {"role": "system", "content": _system_prompt(business)},
        {"role": "system", "content": json.dumps(context, ensure_ascii=False)},
    ]
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": message})
    return chat_json(settings, messages)


def _draft_ready_for_propose(draft: dict[str, Any]) -> bool:
    return all(draft.get(k) for k in ("service", "size", "subject", "day", "time"))


def _list_slots_reply(
    settings: Settings,
    business: Business,
    store: Store,
    calendar: CalendarClient,
    draft: dict[str, Any],
    prefix: str,
) -> str | None:
    if not all(draft.get(k) for k in ("service", "size", "subject", "day")):
        return None
    day = date.fromisoformat(str(draft["day"]))
    period = draft.get("period")
    slots = available_slots(
        business,
        calendar,
        service_name=str(draft["service"]),
        size_name=str(draft["size"]),
        day=day,
        limit=6,
        period=period,
        store=store,
    )
    if isinstance(slots, str):
        return slots
    if not slots:
        label = f" ({period})" if period else ""
        return f"Nao ha horarios livres{label} em {day.strftime('%d/%m')}."
    formatted = ", ".join(s.start.strftime("%H:%M") for s in slots)
    head = prefix or f"Horarios para {draft['service']} — {draft['subject']}:"
    period_note = f" ({period})" if period else ""
    return f"{head}\n{formatted}{period_note}\n\nQual horario prefere?"


def _reschedule_with_llm(
    settings: Settings,
    business: Business,
    store: Store,
    calendar: CalendarClient,
    phone: str,
    message: str,
    history: list[dict[str, str]],
    appt: Any,
) -> str:
    data = _call_scheduler_llm(settings, business, store, phone, message, history, "remarcar", get_draft(store, phone))
    hints = extract_hints(message, business, today=datetime.now(settings.tz).date())
    day_raw = (data or {}).get("day") or hints.get("day")
    time_raw = (data or {}).get("time") or hints.get("time")
    if not day_raw or not time_raw:
        return "Para remarcar, informe o novo dia e horario."
    svc = business.service(appt.service)
    duration = svc.durations.get(appt.size, 60) if svc else 60
    start = datetime.fromisoformat(f"{day_raw}T{time_raw}").replace(tzinfo=settings.tz)
    slots = available_slots(
        business,
        calendar,
        service_name=appt.service,
        size_name=appt.size,
        day=start.date(),
        limit=48,
        store=store,
        exclude_appointment_id=appt.id,
    )
    if isinstance(slots, str):
        return slots
    time_str = start.strftime("%H:%M")
    if not any(s.start.strftime("%H:%M") == time_str for s in slots):
        if slots:
            formatted = ", ".join(s.start.strftime("%H:%M") for s in slots[:6])
            return (
                f"O horario {time_str} nao esta disponivel em {start.strftime('%d/%m')}. "
                f"Horarios livres: {formatted}"
            )
        return f"Nao ha horarios livres em {start.strftime('%d/%m')}. Quer tentar outro dia?"
    result = reschedule_booking(
        store=store,
        calendar=calendar,
        appointment_id=appt.id,
        new_start=start,
        duration_min=duration,
    )
    if result.get("ok"):
        return f"Remarcado para {start.strftime('%d/%m %H:%M')}."
    return "Nao consegui remarcar. Quer tentar outro horario?"
