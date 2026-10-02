from __future__ import annotations

import re
from typing import Any

WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")
DAY_ALIASES = {
    "segunda": "seg",
    "terca": "ter",
    "terça": "ter",
    "quarta": "qua",
    "quinta": "qui",
    "sexta": "sex",
    "sabado": "sab",
    "sábado": "sab",
    "domingo": "dom",
}


def _norm_day(token: str) -> str | None:
    raw = token.strip().lower()[:3]
    if raw in WEEKDAYS:
        return raw
    return DAY_ALIASES.get(token.strip().lower())


def _day_index(day: str) -> int:
    return WEEKDAYS.index(day)


def expand_day_span(start: str, end: str) -> list[str]:
    i, j = _day_index(start), _day_index(end)
    if i <= j:
        return list(WEEKDAYS[i : j + 1])
    return list(WEEKDAYS[i:]) + list(WEEKDAYS[: j + 1])


def parse_hours(text: str) -> dict[str, list[str]]:
    """Ex.: 'ter a sex 08-18, sab 08-14' ou 'seg-sex 09:00-19:00'."""
    result: dict[str, list[str]] = {}
    chunks = re.split(r"[,;\n]+", text.strip())
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        time_match = re.search(r"(\d{1,2}:?\d{0,2})\s*-\s*(\d{1,2}:?\d{0,2})", chunk)
        if not time_match:
            raise ValueError(f"Horario invalido em: {chunk}")
        start = _fmt_time(time_match.group(1))
        end = _fmt_time(time_match.group(2))
        slot = f"{start}-{end}"
        day_part = chunk[: time_match.start()].strip(" ,")
        days = _parse_day_part(day_part)
        for day in days:
            result.setdefault(day, []).append(slot)
    if not result:
        raise ValueError("Nenhum horario reconhecido")
    return result


def _fmt_time(raw: str) -> str:
    raw = raw.strip()
    if ":" in raw:
        h, m = raw.split(":", 1)
        return f"{int(h):02d}:{int(m or 0):02d}"
    if len(raw) <= 2:
        return f"{int(raw):02d}:00"
    return f"{int(raw[:-2]):02d}:{int(raw[-2:]):02d}"


def _parse_day_part(text: str) -> list[str]:
    text = text.strip().lower()
    if not text:
        raise ValueError("Informe os dias (ex.: ter a sex)")
    text = text.replace(" a ", "-").replace(" à ", "-").replace(" ate ", "-").replace(" até ", "-")
    if "-" in text and text.count("-") == 1 and not re.search(r"\d", text):
        left, right = (part.strip() for part in text.split("-", 1))
        start = _norm_day(left) or _norm_day(left[:3])
        end = _norm_day(right) or _norm_day(right[:3])
        if start and end:
            return expand_day_span(start, end)
    days: list[str] = []
    for token in re.split(r"[,/\s]+", text):
        if not token or token == "-":
            continue
        day = _norm_day(token) or _norm_day(token[:3])
        if day:
            days.append(day)
    if not days:
        raise ValueError(f"Dias invalidos: {text}")
    return days


def parse_variants(text: str) -> dict[str, str]:
    """Ex.: 'pequeno: ate 10kg, medio: 10-25kg, grande: acima 25kg' ou 'unico'."""
    text = text.strip()
    if text.lower() in ("unico", "único", "preco unico", "preço único"):
        return {"unico": "preco unico"}
    result: dict[str, str] = {}
    parts = re.split(r"[,;\n]+", text)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            key, desc = part.split(":", 1)
        elif " " in part:
            key, desc = part.split(" ", 1)
        else:
            key, desc = part, part
        key = _slug(key)
        if key:
            result[key] = desc.strip() or key
    if not result:
        raise ValueError("Informe as categorias de preco")
    return result


def parse_prices(text: str, variants: list[str]) -> dict[str, float]:
    """Ex.: 'pequeno 50 medio 70' ou '45' quando so existe variante unico."""
    text = text.strip().replace("R$", "").replace(",", ".")
    if len(variants) == 1 and variants[0] == "unico":
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        if not match:
            raise ValueError("Informe o preco")
        return {"unico": float(match.group(1))}
    result: dict[str, float] = {}
    for variant in variants:
        pattern = rf"{re.escape(variant)}\s*[:=]?\s*(\d+(?:\.\d+)?)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            result[variant] = float(match.group(1))
    if len(result) != len(variants):
        missing = [v for v in variants if v not in result]
        raise ValueError(f"Faltam precos para: {', '.join(missing)}")
    return result


def parse_durations(text: str, variants: list[str]) -> dict[str, int]:
    text = text.strip().lower()
    if len(variants) == 1 and variants[0] == "unico":
        match = re.search(r"(\d+)", text)
        if not match:
            raise ValueError("Informe a duracao em minutos")
        return {"unico": int(match.group(1))}
    result: dict[str, int] = {}
    for variant in variants:
        pattern = rf"{re.escape(variant)}\s*[:=]?\s*(\d+)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            result[variant] = int(match.group(1))
    if not result:
        single = re.search(r"(\d+)", text)
        if single and len(variants) == 1:
            return {variants[0]: int(single.group(1))}
        raise ValueError("Informe duracao por variante (ex.: pequeno 60 medio 90)")
    if len(result) != len(variants):
        missing = [v for v in variants if v not in result]
        raise ValueError(f"Faltam duracoes para: {', '.join(missing)}")
    return result


def parse_faq_line(text: str) -> dict[str, str] | None:
    text = text.strip()
    if not text:
        return None
    if "?" in text and "|" in text:
        pergunta, resposta = text.split("|", 1)
        return {"pergunta": pergunta.strip(), "resposta": resposta.strip()}
    if "?" in text:
        q, _, a = text.partition("?")
        if a.strip():
            return {"pergunta": f"{q.strip()}?", "resposta": a.strip(" :.-")}
    raise ValueError("Use formato: pergunta? | resposta")


def parse_package(text: str, variants: list[str]) -> dict[str, Any]:
    """Ex.: 'Noiva completa | 350' ou 'Combo | pequeno 120 medio 150'."""
    if "|" not in text:
        raise ValueError("Use formato: nome do pacote | preco(s)")
    name, rest = (part.strip() for part in text.split("|", 1))
    pkg: dict[str, Any] = {"nome": name}
    if any(v in rest.lower() for v in variants if v != "unico"):
        pkg["precos"] = parse_prices(rest, variants)
    else:
        match = re.search(r"(\d+(?:\.\d+)?)", rest.replace(",", "."))
        if not match:
            raise ValueError("Informe o preco do pacote")
        pkg["preco"] = float(match.group(1))
    return pkg


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return cleaned[:40]
