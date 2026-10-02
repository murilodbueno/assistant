from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Literal

from .booking_state import format_proposal, set_pending
from .business import Business, normalize
from .calendar import CalendarClient, Slot
from .config import Settings
from .store import Store
from .tools import available_slots

Period = Literal["manha", "tarde", "noite"]

WEEKDAY_WORDS: dict[str, int] = {
    "segunda": 0,
    "terca": 1,
    "terça": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sabado": 5,
    "sábado": 5,
    "domingo": 6,
}


def is_booking_followup(
    message: str,
    business: Business,
    draft: dict[str, Any],
    *,
    today: date | None = None,
) -> bool:
    if not draft:
        return False
    hints = extract_hints(message, business, today=today)
    missing = _missing_fields(draft, business)
    field_map = {
        "servico": "service",
        business.variant_label: "size",
        business.subject_label: "subject",
        "dia": "day",
    }
    missing_keys = {field_map.get(m, m) for m in missing}
    if missing_keys & hints.keys():
        return True
    if "period" in hints and not draft.get("time"):
        return True
    if not draft.get("time"):
        if hints.get("time"):
            return True
        lowered = normalize(message)
        if re.fullmatch(r"\d{1,2}(:\d{2})?\s*h?", lowered) or re.fullmatch(r"\d{1,2}h", lowered):
            return True
    return False


def get_draft(store: Store, phone: str) -> dict[str, Any]:
    draft = store.get_state(phone).get("booking_draft")
    return dict(draft) if isinstance(draft, dict) else {}


def set_draft(store: Store, phone: str, draft: dict[str, Any] | None) -> None:
    state = store.get_state(phone)
    if draft:
        state["booking_draft"] = draft
    else:
        state.pop("booking_draft", None)
    store.set_state(phone, state)


def clear_booking_context(store: Store, phone: str) -> None:
    state = store.get_state(phone)
    state.pop("booking_draft", None)
    state.pop("booking_pending", None)
    store.set_state(phone, state)


def detect_period(message: str) -> Period | None:
    lowered = normalize(message)
    if any(w in lowered for w in ("manha", "de manha")):
        return "manha"
    if any(w in lowered for w in ("tarde", "de tarde")):
        return "tarde"
    if any(w in lowered for w in ("noite", "de noite")):
        return "noite"
    return None


def filter_slots_by_period(slots: list[Slot], period: Period | None) -> list[Slot]:
    if period is None:
        return slots
    if period == "manha":
        return [s for s in slots if s.start.hour < 12]
    if period == "tarde":
        return [s for s in slots if 12 <= s.start.hour < 18]
    return [s for s in slots if s.start.hour >= 18]


def extract_hints(message: str, business: Business, *, today: date | None = None) -> dict[str, Any]:
    lowered = normalize(message)
    hints: dict[str, Any] = {}

    service = _extract_service(lowered, business)
    if service:
        hints["service"] = service

    size = _extract_size(lowered, business)
    if size:
        hints["size"] = size

    subject = _extract_subject(message)
    if subject:
        hints["subject"] = subject

    day = _extract_day(lowered, today or date.today())
    if day:
        hints["day"] = day.isoformat()

    time_val = _extract_time(message)
    if time_val:
        hints["time"] = time_val

    period = detect_period(message)
    if period:
        hints["period"] = period

    return hints


def merge_draft(draft: dict[str, Any], *updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(draft)
    for part in updates:
        for key, value in part.items():
            if value not in (None, ""):
                merged[key] = value
    return merged


def merge_llm_data(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if data.get("service"):
        out["service"] = str(data["service"])
    if data.get("size"):
        out["size"] = str(data["size"])
    subject = data.get("subject_name") or data.get("pet_name")
    if subject:
        out["subject"] = str(subject)
    if data.get("day"):
        out["day"] = str(data["day"])
    if data.get("time"):
        out["time"] = str(data["time"])
    return out


def advance_booking(
    settings: Settings,
    business: Business,
    store: Store,
    calendar: CalendarClient,
    phone: str,
    draft: dict[str, Any],
) -> str:
    missing = _missing_fields(draft, business)
    if missing:
        return _ask_missing(business, draft, missing)

    service = str(draft["service"])
    size = str(draft["size"])
    subject = str(draft["subject"])
    day = date.fromisoformat(str(draft["day"]))
    period = draft.get("period")

    if not draft.get("time"):
        slots = available_slots(
            business,
            calendar,
            service_name=service,
            size_name=size,
            day=day,
            limit=12,
            period=period,
        )
        if isinstance(slots, str):
            return slots
        if not slots:
            label = f" na {period}" if period else ""
            return f"Nao ha horarios livres{label} em {day.strftime('%d/%m')}. Quer tentar outro dia?"
        formatted = ", ".join(s.start.strftime("%H:%M") for s in slots[:6])
        period_label = f" ({period})" if period else ""
        return (
            f"Horarios disponiveis{period_label} em {day.strftime('%d/%m')} para {service} — {subject}:\n"
            f"{formatted}\n\nQual horario prefere?"
        )

    try:
        start = datetime.fromisoformat(f"{draft['day']}T{draft['time']}").replace(tzinfo=settings.tz)
    except ValueError:
        return "Informe o horario no formato HH:MM (ex.: 14:00)."

    slots = available_slots(
        business,
        calendar,
        service_name=service,
        size_name=size,
        day=day,
        limit=48,
        period=period,
    )
    if isinstance(slots, str):
        return slots
    time_str = str(draft["time"])
    if not any(s.start.strftime("%H:%M") == time_str for s in slots):
        if slots:
            formatted = ", ".join(s.start.strftime("%H:%M") for s in slots[:6])
            return (
                f"O horario {time_str} nao esta disponivel em {day.strftime('%d/%m')}. "
                f"Horarios livres: {formatted}\n\nQual horario prefere?"
            )
        label = f" na {period}" if period else ""
        return f"Nao ha horarios livres{label} em {day.strftime('%d/%m')}. Quer tentar outro dia?"

    svc = business.service(service)
    variant = business.size(size)
    preco = svc.prices.get(variant) if svc and variant else None
    set_pending(
        store,
        phone,
        {
            "service": service,
            "size": size,
            "subject": subject,
            "start_iso": start.isoformat(),
            "preco": preco,
        },
    )
    set_draft(store, phone, None)
    return format_proposal(
        business,
        subject=subject,
        service=service,
        size=size,
        start=start,
        preco=preco,
    )


def _missing_fields(draft: dict[str, Any], business: Business) -> list[str]:
    missing: list[str] = []
    if not draft.get("service"):
        missing.append("servico")
    elif business.service(str(draft["service"])) is None:
        missing.append("servico")
    if not draft.get("size"):
        missing.append(business.variant_label)
    elif business.size(str(draft["size"])) is None:
        missing.append(business.variant_label)
    if not draft.get("subject"):
        missing.append(business.subject_label)
    if not draft.get("day"):
        missing.append("dia")
    return missing


def _ask_missing(business: Business, draft: dict[str, Any], missing: list[str]) -> str:
    known = []
    if draft.get("service"):
        known.append(f"servico: {draft['service']}")
    if draft.get("size"):
        known.append(f"{business.variant_label}: {draft['size']}")
    if draft.get("subject"):
        known.append(f"{business.subject_label}: {draft['subject']}")
    if draft.get("day"):
        known.append(f"dia: {draft['day']}")
    prefix = "Anotei " + ", ".join(known) + ". " if known else ""
    labels = {
        "servico": f"qual servico ({', '.join(s.name for s in business.services[:4])}...)?",
        business.variant_label: f"qual {business.variant_label} ({', '.join(business.sizes.keys())})?",
        business.subject_label: f"qual o {business.subject_label}?",
        "dia": "qual dia voce prefere?",
    }
    questions = [labels.get(m, m) for m in missing[:2]]
    return prefix + " ".join(q.capitalize() for q in questions)


def _extract_service(lowered: str, business: Business) -> str | None:
    hits: list[tuple[int, str]] = []
    for svc in business.services:
        key = normalize(svc.name)
        if key in lowered:
            hits.append((len(key), svc.name))
    if not hits:
        if "banho" in lowered and "tosa" not in lowered:
            svc = business.service("Banho")
            return svc.name if svc else None
        return None
    hits.sort(key=lambda x: x[0])
    return hits[0][1]


def _extract_size(lowered: str, business: Business) -> str | None:
    for key in business.sizes:
        if key in lowered.split():
            return key
        if key in lowered:
            return key
    return None


def _extract_subject(message: str) -> str | None:
    patterns = [
        r"(?:pro|para|pra|pet|nome)\s+([A-Za-z][a-z]{1,20})",
        r"(?:cachorro|gato|cao|cadela)\s+(?:chamado|de nome|nome)\s+([A-Za-z][a-z]{1,20})",
    ]
    skip = {"banho", "tosa", "grande", "medio", "pequeno", "sexta", "terca", "quarta", "quinta", "sabado"}
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            if normalize(name) not in skip:
                return name[0].upper() + name[1:].lower()
    return None


def _extract_time(message: str) -> str | None:
    patterns = [
        r"(?:\bas\s|\bàs\s|^)(\d{1,2})(?::(\d{2}))?\s*h?\b",
        r"\b(\d{1,2}):(\d{2})\b",
        r"\b(\d{1,2})h\b",
    ]
    colon = re.search(r"\b(\d{1,2}):(\d{2})\b", message)
    if colon:
        hour, minute = int(colon.group(1)), int(colon.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    hours = re.search(r"\b(\d{1,2})h\b", message, flags=re.IGNORECASE)
    if hours:
        hour = int(hours.group(1))
        if 0 <= hour <= 23:
            return f"{hour:02d}:00"
    prefixed = re.search(r"(?:\bas\s|\bàs\s)(\d{1,2})(?::(\d{2}))?\b", message, flags=re.IGNORECASE)
    if prefixed:
        hour = int(prefixed.group(1))
        minute = int(prefixed.group(2) or 0)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    return None


def _extract_day(lowered: str, today: date) -> date | None:
    if "amanha" in lowered:
        return today + timedelta(days=1)
    if "hoje" in lowered:
        return today
    iso = re.search(r"(\d{4}-\d{2}-\d{2})", lowered)
    if iso:
        try:
            return date.fromisoformat(iso.group(1))
        except ValueError:
            return None
    br = re.search(r"(\d{1,2})[/-](\d{1,2})", lowered)
    if br:
        day, month = int(br.group(1)), int(br.group(2))
        year = today.year
        try:
            candidate = date(year, month, day)
            if candidate < today:
                candidate = date(year + 1, month, day)
            return candidate
        except ValueError:
            return None
    for word, weekday in WEEKDAY_WORDS.items():
        if word in lowered.split() or word in lowered:
            return _next_weekday(today, weekday)
    return None


def _next_weekday(today: date, weekday: int) -> date:
    delta = (weekday - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)
