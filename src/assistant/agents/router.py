from __future__ import annotations

import logging
from typing import Literal

from ..business import Business, normalize
from ..config import Settings
from ..llm import chat_json

log = logging.getLogger("assistant.router")

Intent = Literal[
    "faq",
    "agendar",
    "remarcar",
    "cancelar",
    "confirmar_lembrete",
    "humano",
    "outro",
]

BOOKING_VERBS = ("quero", "preciso", "gostaria", "marca", "marcar", "agendar", "reservar", "schedule")


def _system_prompt(business: Business) -> str:
    return (
        f"Voce classifica mensagens de clientes de um(a) {business.kind}.\n"
        'Responda JSON: {"intent": "<valor>"}\n'
        "Valores: faq, agendar, remarcar, cancelar, confirmar_lembrete, humano, outro.\n"
        "- faq: precos, horarios, servicos, endereco, regras\n"
        "- agendar: marcar servico\n"
        "- remarcar: mudar horario\n"
        "- cancelar: desmarcar\n"
        "- confirmar_lembrete: confirmar presenca apos lembrete\n"
        "- humano: pede atendente/dono ou reclamacao grave\n"
        "- outro: cumprimento ou conversa geral"
    )


def classify_intent(
    settings: Settings,
    business: Business,
    message: str,
    history: list[dict[str, str]],
) -> Intent:
    messages = [{"role": "system", "content": _system_prompt(business)}]
    messages.extend(history[-6:])
    messages.append({"role": "user", "content": message})
    data = chat_json(settings, messages)
    if data and data.get("intent") in {
        "faq", "agendar", "remarcar", "cancelar", "confirmar_lembrete", "humano", "outro",
    }:
        return data["intent"]

    return _heuristic_intent(business, message)


def _heuristic_intent(business: Business, message: str) -> Intent:
    lowered = normalize(message)

    if any(w in lowered for w in ("atendente", "humano", "dono", "reclamacao", "reclamar")):
        return "humano"

    if any(w in lowered for w in ("confirmar", "confirmo", "confirmado")) and "lembrete" in lowered:
        return "confirmar_lembrete"

    if any(w in lowered for w in ("remarcar", "mudar horario", "trocar horario", "alterar horario")):
        return "remarcar"

    if any(w in lowered for w in ("cancelar", "desmarcar")):
        return "cancelar"

    # FAQ antes de agendar — preco/endereco nao devem cair no scheduler
    if any(w in lowered for w in ("preco", "quanto", "valor", "custa", "cobram", "endereco", "onde fica", "pagamento", "formas de pagamento")):
        return "faq"

    if any(w in lowered for w in ("horario", "funcionamento", "abre", "aberto", "fechado")):
        if not any(v in lowered for v in BOOKING_VERBS):
            return "faq"

    if any(w in lowered for w in ("agendar", "marcar", "reservar")):
        return "agendar"

    if any(v in lowered for v in BOOKING_VERBS):
        service_words = [normalize(s.name) for s in business.services]
        if any(word in lowered for word in service_words):
            return "agendar"
        if any(w in lowered for w in ("horario", "vaga", "encaixe")):
            return "agendar"

    return "outro"
