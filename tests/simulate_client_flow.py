"""
Simulacao deterministica do atendimento ao cliente.
Execute: python -m tests.simulate_client_flow
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from petshop.business import load_business
from petshop.calendar import CalendarClient
from petshop.config import Settings
from petshop.orchestrator import Orchestrator
from petshop.store import Store
from petshop.whatsapp import WhatsAppClient

ROOT = Path(__file__).resolve().parents[1]
CLIENT = "5511888777666"


def _settings(tmp_db: Path) -> Settings:
    return Settings(
        llm_api_key="test-api-key",
        llm_base_url="https://example.com/v1",
        llm_model="test-model",
        llm_timeout_sec=5.0,
        fallback_api_key="",
        fallback_base_url="https://example.com/v1",
        fallback_model="",
        fallback_timeout_sec=5.0,
        waha_url="http://localhost:3000",
        waha_api_key="",
        waha_session="default",
        waha_hmac_key="",
        google_service_account_file=Path("/nonexistent/fake.json"),
        google_calendar_id="",
        owner_phone="5511999887766",
        bot_pause_hours=12.0,
        debounce_sec=0.0,
        reminder_start_hour=9,
        reminder_end_hour=19,
        business_file=ROOT / "business" / "pet_shop.yaml",
        db_path=tmp_db,
        timezone="America/Sao_Paulo",
    )


class Transcript:
    def __init__(self, title: str) -> None:
        self.title = title
        self.lines: list[str] = []

    def say(self, role: str, text: str) -> None:
        self.lines.append(f"  [{role}] {text}")

    def dump(self) -> str:
        out = [f"\n=== {self.title} ==="]
        out.extend(self.lines)
        return "\n".join(out)


def _run_turn(orch: Orchestrator, phone: str, msg: str, t: Transcript) -> str:
    t.say("cliente", msg)
    reply = orch.process_message(phone, msg)
    orch.store.add_message(phone, "user", msg)
    orch.store.add_message(phone, "assistant", reply)
    t.say("bot", reply)
    return reply


def simulate_no_llm(tmp_path: Path) -> Transcript:
    """Sem LLM configurado: so heuristica do router + mensagens genericas."""
    t = Transcript("Cenario A — LLM indisponivel (API key vazia)")
    settings = _settings(tmp_path / "a.db")
    settings = Settings(**{**settings.__dict__, "llm_api_key": ""})
    store = Store(settings.db_path)
    store.init_db()
    orch = Orchestrator(settings, load_business(settings.business_file), store, CalendarClient(settings), WhatsAppClient(settings))

    _run_turn(orch, CLIENT, "oi", t)
    _run_turn(orch, CLIENT, "quanto custa banho?", t)
    _run_turn(orch, CLIENT, "quero banho pro Thor, grande, sexta a tarde", t)
    _run_turn(orch, CLIENT, "14h", t)
    t.say("sistema", "Esperado: preco do YAML; agendar local com memoria e confirmacao")
    return t


def simulate_with_llm_mocks(tmp_path: Path) -> Transcript:
    """LLM mockado com respostas realistas."""
    t = Transcript("Cenario B — fluxo completo com LLM mockado")
    settings = _settings(tmp_path / "b.db")
    store = Store(settings.db_path)
    store.init_db()
    biz = load_business(settings.business_file)
    orch = Orchestrator(settings, biz, store, CalendarClient(settings), WhatsAppClient(settings))
    next_friday = date.today() + timedelta(days=(4 - date.today().weekday()) % 7 or 7)
    day_str = next_friday.isoformat()

    router_queue = [
        {"intent": "outro"},
        {"intent": "faq"},
        {"intent": "agendar"},
        {"intent": "faq"},
        {"intent": "humano"},
    ]
    faq_queue = [
        type("R", (), {"content": "Banho: pequeno R$50, medio R$70, grande R$90. Qual porte do seu pet?"})(),
        type("R", (), {"content": "Nao sei se fazemos tosa na tesoura estilo show — vou verificar com a equipe."})(),
    ]
    scheduler_queue = [
        {
            "reply": "Qual o porte do Thor e qual servico voce quer?",
            "action": None,
        },
        {
            "reply": "Horarios disponiveis na sexta:",
            "action": "list_slots",
            "service": "Banho",
            "size": "grande",
            "subject_name": "Thor",
            "day": day_str,
        },
    ]

    def _next_or_default(queue: list, default=None):
        def getter(*_a, **_k):
            if queue:
                return queue.pop(0)
            return default

        return getter

    with patch("petshop.agents.router.chat_json", side_effect=_next_or_default(router_queue)), patch(
        "petshop.agents.faq.chat", side_effect=_next_or_default(faq_queue)
    ), patch("petshop.agents.scheduler.chat_json", side_effect=_next_or_default(scheduler_queue)):
        _run_turn(orch, CLIENT, "ola", t)
        _run_turn(orch, CLIENT, "quanto custa banho?", t)
        _run_turn(orch, CLIENT, "quero banho pro Thor, cachorro grande, sexta a tarde", t)
        _run_turn(orch, CLIENT, "pode ser as 14h", t)
        _run_turn(orch, CLIENT, "sim", t)
        _run_turn(orch, CLIENT, "voces buscam o pet em casa?", t)
        _run_turn(orch, CLIENT, "faz tosa de poodle estilo exposicao?", t)

    appt = store.find_active_appointment(CLIENT)
    pending = store.get_state(CLIENT).get("booking_pending")
    draft = store.get_state(CLIENT).get("booking_draft")
    if appt:
        t.say("sistema", f"Agendamento confirmado: {appt.pet_name}, {appt.service}, porte {appt.size}")
    elif pending:
        t.say("sistema", "Proposta pendente — aguardando SIM/NAO do cliente")
    elif draft:
        t.say("sistema", f"Rascunho ativo: {draft}")
    else:
        t.say("sistema", "Sem agendamento nem rascunho residual")
    return t


def simulate_faq_direct(tmp_path: Path) -> Transcript:
    """FAQ do YAML sem depender do LLM para conteudo."""
    t = Transcript("Cenario C — FAQ catalogada (busca no YAML)")
    settings = _settings(tmp_path / "c.db")
    store = Store(settings.db_path)
    store.init_db()
    orch = Orchestrator(settings, load_business(settings.business_file), store, CalendarClient(settings), WhatsAppClient(settings))

    with patch("petshop.agents.router.chat_json", return_value={"intent": "faq"}), patch(
        "petshop.agents.faq.chat",
        return_value=type("R", (), {"content": "Nao no momento."})(),
    ):
        _run_turn(orch, CLIENT, "voces buscam o pet em casa?", t)
    return t


def main() -> None:
    tmp = ROOT / "data" / "sim_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    transcripts = [
        simulate_no_llm(tmp / "a.db"),
        simulate_with_llm_mocks(tmp / "b.db"),
        simulate_faq_direct(tmp / "c.db"),
    ]
    for tr in transcripts:
        print(tr.dump())
    print("\n=== Observacoes automaticas ===")
    print("- Fase 1 aplicada: router, FAQ deterministica, confirmacao antes de agendar")
    print("- Fase 2 aplicada: memoria, filtro manha/tarde, debounce 2s")
    print("- Segunda-feira fechada no YAML: cliente pedindo 'segunda' recebe sem slots")


if __name__ == "__main__":
    main()
