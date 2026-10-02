from __future__ import annotations

import logging

from ..config import Settings
from ..store import Store
from ..whatsapp import WhatsAppClient

log = logging.getLogger("petshop.handoff")


def run_handoff(
    settings: Settings,
    store: Store,
    whatsapp: WhatsAppClient,
    *,
    client_phone: str,
    question: str,
) -> str:
    if not settings.owner_phone:
        return "Vou verificar com a equipe e ja retorno."
    handoff_id = store.create_handoff(client_phone, question)
    msg = (
        f"[Pet Shop] Cliente {client_phone} perguntou:\n"
        f"{question}\n\n"
        f"Responda esta mensagem para repassar ao cliente."
    )
    whatsapp.send_text(settings.owner_phone, msg)
    log.info("Handoff %s created for %s", handoff_id, client_phone)
    return "Boa pergunta! Vou confirmar com o responsavel e ja te retorno."
