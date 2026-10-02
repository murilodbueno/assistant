from __future__ import annotations

import json
import logging

from ..business import Business, WEEKDAYS, normalize
from ..config import Settings
from ..llm import chat
from ..tools import business_context, price_reply, search_faq

log = logging.getLogger("petshop.faq")

DAY_LABELS = {
    "seg": "Segunda",
    "ter": "Terca",
    "qua": "Quarta",
    "qui": "Quinta",
    "sex": "Sexta",
    "sab": "Sabado",
    "dom": "Domingo",
}


def _system_prompt(business: Business) -> str:
    return (
        f"Voce e a atendente virtual de um(a) {business.kind}.\n"
        "Responda em portugues, de forma cordial e curta.\n"
        "Use SOMENTE os dados fornecidos em contexto. Nao invente precos ou horarios.\n"
        "Se nao souber, diga que vai verificar com a equipe."
    )


def _hours_reply(business: Business) -> str:
    horarios = business.raw.get("horarios") or {}
    if not horarios:
        return "Horario de funcionamento nao informado. Posso verificar com a equipe."
    lines = ["Horarios de funcionamento:"]
    for key in WEEKDAYS:
        if key in horarios:
            ranges = ", ".join(horarios[key])
            lines.append(f"  {DAY_LABELS[key]}: {ranges}")
    closed = [DAY_LABELS[k] for k in WEEKDAYS if k not in horarios]
    if closed:
        lines.append(f"  Fechado: {', '.join(closed)}")
    return "\n".join(lines)


def _address_reply(business: Business) -> str:
    endereco = business.raw.get("endereco")
    if not endereco:
        return "Endereco nao informado. Posso verificar com a equipe."
    return f"Estamos em: {endereco}"


def _payment_reply(business: Business) -> str:
    pagamento = business.raw.get("pagamento")
    if not pagamento:
        return "Formas de pagamento nao informadas."
    return f"Aceitamos: {pagamento}"


def _deterministic_reply(business: Business, message: str) -> str | None:
    faq_hits = search_faq(business, message)
    if faq_hits:
        return faq_hits[0]["resposta"]

    price = price_reply(business, message)
    if price:
        return price

    lowered = normalize(message)
    if any(w in lowered for w in ("horario", "funcionamento", "abre", "aberto", "fechado")):
        return _hours_reply(business)
    if any(w in lowered for w in ("endereco", "onde fica", "localizacao", "como chegar")):
        return _address_reply(business)
    if any(w in lowered for w in ("pagamento", "pix", "cartao", "dinheiro")):
        return _payment_reply(business)

    return None


def run_faq(
    settings: Settings,
    business: Business,
    message: str,
    history: list[dict[str, str]],
) -> tuple[str, bool]:
    """Returns (reply, needs_handoff)."""
    direct = _deterministic_reply(business, message)
    if direct is not None:
        return direct, False

    ctx = business_context(business)
    messages = [
        {"role": "system", "content": _system_prompt(business)},
        {"role": "system", "content": json.dumps(ctx, ensure_ascii=False)},
    ]
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": message})
    result = chat(settings, messages)
    if result is None:
        return "Desculpe, estou com instabilidade. Pode tentar de novo em instantes?", False
    reply = result.content.strip()
    needs_handoff = any(p in reply.lower() for p in ("nao sei", "verificar com", "equipe", "dono"))
    return reply, needs_handoff
