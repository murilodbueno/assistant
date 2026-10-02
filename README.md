# Assistant — WhatsApp multi-agente para pequenos negócios

Assistente virtual via **WhatsApp** para pequenos negócios de serviços: atende clientes, responde FAQ, agenda no **Google Calendar**, envia lembretes e escala para o dono quando necessário.

Stack: **Python 3.11+**, **FastAPI**, **WAHA** (QR code), **SQLite**, **Docker**.

---

## Funcionalidades

- **Multi-agente:** Router, FAQ, Scheduler e Handoff
- **FAQ determinística** a partir de YAML (preços, horários, regras)
- **Agendamento com memória** (rascunho por conversa, confirmação SIM/NAO)
- **Filtro manhã/tarde** e validação de horários ocupados
- **Lembretes** automáticos no dia anterior
- **Painel admin via WhatsApp** (`configurar`, `preco ...`, `faq ...`)
- **Setup interativo** no terminal (`assistant-setup`)
- **Templates por nicho** em `business/` (salão, barbearia, etc.)

---

## Início rápido (local)

```bash
git clone https://github.com/murilodbueno/assistant.git
cd assistant

python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env
# Edite .env — veja seção Variáveis abaixo

assistant-setup          # wizard opcional para preencher business/*.yaml
assistant-simulator      # simula atendimento no terminal
pytest -q              # testes
```

API local (webhook WAHA):

```bash
uvicorn assistant.main:app --host 0.0.0.0 --port 8000
curl http://localhost:8000/health
```

---

## Variáveis de ambiente

Copie `.env.example` para `.env`. Principais:

| Variável | Descrição |
|----------|-----------|
| `LLM_API_KEY` | Chave da API compatível com OpenAI (router/FAQ/scheduler) |
| `BUSINESS_FILE` | Template YAML do nicho (ex.: `business/salao.yaml`) |
| `OWNER_PHONE` | WhatsApp do dono (admin + handoff) |
| `WAHA_URL` / `WAHA_API_KEY` | Conexão com WAHA |
| `WAHA_HMAC_KEY` | **Obrigatório em produção** — valida webhook |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | JSON da conta de serviço |
| `GOOGLE_CALENDAR_ID` | ID da agenda compartilhada |
| `DEBOUNCE_SEC` | Espera antes de responder (padrão: 2s) |

---

## Nicho do negócio (YAML)

Escolha ou crie um arquivo em `business/`:

```env
BUSINESS_FILE=business/salao.yaml
```

Veja [business/README.md](business/README.md) para estrutura do YAML e como adicionar nichos.

---

## Deploy

Guia completo: [docs/DEPLOY.md](docs/DEPLOY.md) (Hetzner + Docker + Caddy + WAHA + Google Calendar).

Resumo:

```bash
docker compose up -d --build
docker compose logs -f app
```

---

## Documentação

| Arquivo | Conteúdo |
|---------|----------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Agentes, fluxos, decisões técnicas |
| [docs/DEPLOY.md](docs/DEPLOY.md) | Produção passo a passo |
| [business/README.md](business/README.md) | Templates por tipo de negócio |

---

## Estrutura do projeto

```
src/assistant/
  agents/          # router, faq, scheduler, handoff
  setup/           # wizard CLI + admin WhatsApp
  booking_draft.py # memória de agendamento
  orchestrator.py  # debounce + roteamento
  main.py          # FastAPI + webhook WAHA
business/          # YAML por nicho
tests/             # pytest + simulate_client_flow
docs/              # arquitetura e deploy
```

---

## Licença

Ver [LICENSE](LICENSE).
