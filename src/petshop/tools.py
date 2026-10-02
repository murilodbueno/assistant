from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .business import Business, Service, normalize
from .calendar import CalendarClient, Slot

Period = str | None
from .store import Store


def list_services(business: Business) -> list[dict[str, Any]]:
    return [
        {
            "nome": svc.name,
            "precos": svc.prices,
            "duracao_min": svc.durations,
        }
        for svc in business.services
    ]


def is_price_question(message: str) -> bool:
    lowered = normalize(message)
    return any(w in lowered for w in ("preco", "quanto", "valor", "custa", "cobram", "quanto custa"))


def _matching_services(business: Business, lowered: str) -> list[Service]:
    hits: list[Service] = []
    for svc in business.services:
        key = normalize(svc.name)
        if key in lowered:
            hits.append(svc)
    if hits:
        hits.sort(key=lambda s: len(normalize(s.name)))
        shortest = normalize(hits[0].name)
        return [s for s in hits if normalize(s.name) == shortest or normalize(s.name).startswith(shortest + " ")]
    return []


def price_reply(business: Business, message: str) -> str | None:
    if not is_price_question(message):
        return None
    lowered = normalize(message)
    services = _matching_services(business, lowered)
    if services:
        body = "\n\n".join(_format_service_prices(s, business) for s in services)
        return f"{body}\n\nQuer agendar?"
    return _format_all_prices(business) + "\n\nQuer agendar?"


def _format_service_prices(svc: Service, business: Business) -> str:
    lines = [f"*{svc.name}*:"]
    for variant, price in svc.prices.items():
        desc = business.sizes.get(variant, variant)
        lines.append(f"  • {desc}: R$ {price:.0f}")
    return "\n".join(lines)


def _format_all_prices(business: Business) -> str:
    lines = ["Precos:"]
    for svc in business.services:
        lines.append(_format_service_prices(svc, business))
    return "\n".join(lines)


def search_faq(business: Business, query: str) -> list[dict[str, str]]:
    wanted = normalize(query)
    faq = business.raw.get("faq") or []
    hits = []
    for item in faq:
        pergunta = normalize(str(item.get("pergunta", "")))
        if wanted in pergunta or pergunta in wanted:
            hits.append({"pergunta": str(item["pergunta"]), "resposta": str(item["resposta"])})
    return hits


def business_context(business: Business) -> dict[str, Any]:
    return {
        "nome": business.name,
        "segmento": business.segment,
        "tipo": business.kind,
        "endereco": business.raw.get("endereco"),
        "pagamento": business.raw.get("pagamento"),
        "regras": business.raw.get("regras") or [],
        "variantes": business.sizes,
        "label_variantes": business.variant_label,
        "label_sujeito": business.subject_label,
        "servicos": list_services(business),
        "pacotes": business.packages,
    }


def available_slots(
    business: Business,
    calendar: CalendarClient,
    *,
    service_name: str,
    size_name: str,
    day: date,
    limit: int = 5,
    period: Period = None,
) -> list[Slot] | str:
    from .booking_draft import filter_slots_by_period

    svc = business.service(service_name)
    if svc is None:
        return f"Servico nao encontrado: {service_name}"
    size = business.size(size_name)
    if size is None:
        return f"{business.variant_label.capitalize()} invalido: {size_name}. Use: {', '.join(business.sizes)}"
    duration = svc.durations.get(size)
    if duration is None:
        return f"Duracao nao definida para {service_name} / {size}"
    fetch_limit = limit * 3 if period else limit
    slots = calendar.free_slots(business, day, duration, limit=fetch_limit)
    if period:
        slots = filter_slots_by_period(slots, period)
    return slots[:limit]


def create_booking(
    *,
    store: Store,
    calendar: CalendarClient,
    business: Business,
    phone: str,
    pet_name: str,
    service_name: str,
    size_name: str,
    start: datetime,
) -> dict[str, Any]:
    svc = business.service(service_name)
    if svc is None:
        return {"ok": False, "error": "servico invalido"}
    size = business.size(size_name)
    if size is None:
        return {"ok": False, "error": "porte invalido"}
    duration = svc.durations.get(size)
    if duration is None:
        return {"ok": False, "error": "duracao invalida"}
    end = start + timedelta(minutes=duration)
    title = f"{svc.name} - {pet_name}"
    description = (
        f"Cliente: {phone}\n{business.subject_label.capitalize()}: {pet_name}\n"
        f"{business.variant_label.capitalize()}: {size}\nPreco: R$ {svc.prices.get(size, 0):.0f}"
    )
    event_id = calendar.create_event(title=title, description=description, start=start, end=end)
    appt_id = store.create_appointment(
        phone=phone,
        pet_name=pet_name,
        service=svc.name,
        size=size,
        start_ts=start.timestamp(),
        end_ts=end.timestamp(),
        gcal_event_id=event_id,
    )
    return {
        "ok": True,
        "appointment_id": appt_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "preco": svc.prices.get(size),
    }


def reschedule_booking(
    *,
    store: Store,
    calendar: CalendarClient,
    appointment_id: int,
    new_start: datetime,
    duration_min: int,
) -> dict[str, Any]:
    appt = store.get_appointment(appointment_id)
    if appt is None or appt.status != "confirmed":
        return {"ok": False, "error": "agendamento nao encontrado"}
    new_end = new_start + timedelta(minutes=duration_min)
    if appt.gcal_event_id:
        calendar.update_event(appt.gcal_event_id, start=new_start, end=new_end)
    store.update_appointment(appointment_id, start_ts=new_start.timestamp(), end_ts=new_end.timestamp())
    return {"ok": True, "start": new_start.isoformat(), "end": new_end.isoformat()}


def cancel_booking(*, store: Store, calendar: CalendarClient, appointment_id: int) -> dict[str, Any]:
    appt = store.get_appointment(appointment_id)
    if appt is None:
        return {"ok": False, "error": "agendamento nao encontrado"}
    if appt.gcal_event_id:
        calendar.delete_event(appt.gcal_event_id)
    store.update_appointment(appointment_id, status="cancelled")
    return {"ok": True}
