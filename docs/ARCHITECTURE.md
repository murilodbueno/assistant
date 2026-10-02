# Assistant — Plano de Arquitetura (MVP)

> Assistente WhatsApp multi-agente para pequenos negócios: atende clientes, agenda no Google Calendar, envia lembretes e escala para o dono.

---

## 1. Visão geral

```
Cliente WhatsApp
      │
      ▼
   [ WAHA ]  ← QR code, número WhatsApp do negócio
      │ webhook (HMAC)
      ▼
┌─────────────────────────────────────┐
│  FastAPI (assistant)                │
│  ┌───────────┐                      │
│  │ Orquestrador │                   │
│  └─────┬─────┘                      │
│        │ classifica intenção        │
│   ┌────┴────┬─────────┬──────────┐  │
│   ▼         ▼         ▼          ▼  │
│ Router    FAQ    Scheduler   Handoff│
│ Agent    Agent     Agent      Agent │
│   │         │         │          │  │
│   └──── tools: calendar, store, whatsapp, llm
└─────────────────────────────────────┘
      │                    │
      ▼                    ▼
 Google Calendar      SQLite (conversas,
 (conta serviço)       agendamentos, lembretes)
```

**Fora do escopo MVP:** cobrança SaaS, painel web, multi-loja, API Meta oficial.

---

## 2. Agentes e responsabilidades

| Agente | Função | Modelo LLM | Temperatura |
|--------|--------|------------|-------------|
| **Router** | Classifica intenção da mensagem em: `faq`, `agendar`, `remarcar`, `cancelar`, `confirmar_lembrete`, `humano`, `outro` | `openai/gpt-4.1-mini` (rápido/barato) | 0 |
| **FAQ** | Responde preços, horários, regras e FAQ do `business.yaml` | `openai/gpt-4.1-mini` | 0.3 |
| **Scheduler** | Coleta dados (serviço, porte, pet, data/hora), chama ferramentas de agenda | `openai/gpt-4.1` (melhor raciocínio) | 0.2 |
| **Handoff** | Detecta quando não sabe; avisa dono; repassa resposta do dono ao cliente | regras + LLM mínimo | 0 |

**Fallback global:** se LLM principal falhar (timeout/5xx), tenta `FALLBACK_LLM_*` (ex.: NVIDIA Nemotron).

### 2.1 Orquestrador (`agent.py`)

1. Recebe mensagem debounced por telefone.
2. Carrega histórico curto (últimas N mensagens) do SQLite.
3. Se conversa em **pausa** (dono respondeu) → ignora bot por `BOT_PAUSE_HOURS`.
4. Se mensagem veio do **OWNER_PHONE** → trata como resposta de handoff.
5. Chama Router → delega ao agente especializado.
6. Agente pode chamar **tools** (funções Python puras, não MCP).
7. Resposta final enviada via WAHA `sendText`.

### 2.2 Tools disponíveis

| Tool | Agente | Descrição |
|------|--------|-----------|
| `buscar_faq` | FAQ | Busca FAQ + regras no YAML |
| `listar_servicos` | FAQ, Scheduler | Serviços, preços, portes |
| `horarios_disponiveis` | Scheduler | Slots livres (business rules + Google Calendar) |
| `criar_agendamento` | Scheduler | Cria evento no Calendar + registro SQLite |
| `remarcar_agendamento` | Scheduler | Atualiza evento |
| `cancelar_agendamento` | Scheduler | Remove evento |
| `buscar_agendamento_cliente` | Scheduler | Por telefone |
| `chamar_dono` | Handoff | Envia WhatsApp ao OWNER_PHONE com contexto |

---

## 3. Fluxos principais

### 3.1 Agendamento

```
Cliente: "Quero banho pro Rex, cachorro grande, sexta de tarde"
  → Router: agendar
  → Scheduler extrai: serviço=Banho, porte=grande, pet=Rex
  → horarios_disponiveis(sex, 13-18)
  → oferece 2-3 opções
  → cliente confirma
  → criar_agendamento → Google Calendar + SQLite
  → confirma com preço e endereço
```

### 3.2 Handoff (escalação)

```
Cliente: "Vocês fazem tosa na tesoura estilo poodle francês?"
  → FAQ não encontra resposta segura
  → chamar_dono(mensagem, contexto, telefone_cliente)
  → Dono recebe: "Cliente 5511999... perguntou: ..."
  → Dono responde (qualquer texto)
  → Bot repassa ao cliente e pausa automática por 12h
```

### 3.3 Lembretes

- Job em background (thread asyncio ou APScheduler leve).
- Diariamente, entre `REMINDER_START_HOUR` e `REMINDER_END_HOUR`:
  - Busca agendamentos de **amanhã** no SQLite/Calendar.
  - Envia lembrete se `reminder_sent_at IS NULL`.
  - Cliente pode responder "confirmar" ou "remarcar" → Router trata.

---

## 4. Persistência (SQLite)

Tabelas:

```sql
conversations(phone TEXT PK, state_json TEXT, paused_until REAL, updated_at REAL)
messages(id INTEGER PK, phone TEXT, role TEXT, content TEXT, created_at REAL)
appointments(id INTEGER PK, phone TEXT, pet_name TEXT, service TEXT, size TEXT,
             start_ts REAL, end_ts REAL, gcal_event_id TEXT, status TEXT, created_at REAL)
handoffs(id INTEGER PK, client_phone TEXT, question TEXT, owner_notified_at REAL,
         owner_reply TEXT, resolved_at REAL)
reminder_log(appointment_id INTEGER, sent_at REAL)
```

---

## 5. Integrações

### 5.1 WAHA

- **Entrada:** `POST /webhook/waha` — valida HMAC (`X-Webhook-Hmac` ou header WAHA).
- **Saída:** `POST /api/sendText` com `session`, `chatId`, `text`.
- **Debounce:** agrupa mensagens do mesmo `chatId` por `DEBOUNCE_SEC`.

### 5.2 Google Calendar

- Conta de serviço JSON; dono compartilha agenda com e-mail da SA.
- Escopo: `https://www.googleapis.com/auth/calendar`.
- Eventos incluem: título `Banho - Rex (João)`, descrição com telefone.
- **Sem google-api-python-client** no MVP: usar REST via `requests` + `google-auth` (menos deps).

---

## 6. Segurança

| Área | Medida |
|------|--------|
| Webhook | HMAC-SHA512 do body com `WAHA_HMAC_KEY`; rejeitar se inválido |
| API keys | Só via `.env`; nunca commitar; `.gitignore` para `secrets/` e `.env` |
| Google SA | Arquivo em `secrets/` montado como volume read-only no Docker |
| SQLite | Permissões 600; backup diário criptografado opcional (fase 2) |
| LLM | System prompt: só usar dados do `business.yaml`; não inventar preços |
| Dono | Só `OWNER_PHONE` pode resolver handoffs |
| HTTPS | Caddy com Let's Encrypt na VPS |
| Rate limit | Debounce + max 1 resposta/telefone a cada 2s |

---

## 7. DevOps — Hetzner CX22

### 7.1 Stack Docker Compose

```yaml
services:
  caddy:      # reverse proxy, TLS automático
  waha:       # WhatsApp (devlikeapro/waha)
  app:        # assistant (FastAPI + uvicorn)
```

Volumes:
- `./data` → SQLite
- `./secrets` → Google SA (ro)
- `./business.yaml` → config da loja
- `caddy_data` → certificados

### 7.2 Rede

```
Internet → Caddy:443 → app:8000
                    → waha:3000 (só /api interno, não expor publicamente)
WAHA webhook → https://bot.seudominio.com/webhook/waha
```

### 7.3 Deploy

1. Provisionar CX22 (Ubuntu 24.04).
2. Instalar Docker + Compose.
3. DNS A record → IP da VPS.
4. Copiar `.env`, `secrets/`, `business.yaml`.
5. `docker compose up -d`.
6. Escanear QR WAHA em `/dashboard` (protegido por basic auth no Caddy).
7. Configurar webhook WAHA apontando para `/webhook/waha`.

### 7.4 Backup

- Cron diário: `sqlite3 .backup data/assistant.db backups/assistant-$(date +%F).db`
- Retenção 7 dias local; opcional rsync/S3 depois.

### 7.5 Monitoramento MVP

- Healthcheck: `GET /health`
- Logs: `docker compose logs -f app`
- Uptime: UptimeRobot no `/health` (grátis)

---

## 8. Escolha de modelos por agente (custo x qualidade)

| Cenário | Modelo | Motivo |
|---------|--------|--------|
| Router, FAQ | `gpt-4.1-mini` | Classificação e respostas factuais; ~10x mais barato |
| Scheduler (slots, confirmação) | `gpt-4.1` | Menos erro em datas/horários |
| Fallback | Nemotron ou similar | Resiliência se gateway cair |
| Futuro (multi-loja) | Fine-tune ou RAG por loja | Escalar sem aumentar prompt |

**Estimativa de custo por loja:** ~500 msgs/mês × ~800 tokens = ~400k tokens ≈ US$ 0.50–2/mês com mini.

---

## 9. Templates por nicho (`business/`)

Cada tipo de negócio tem seu YAML em `business/`. Veja [business/README.md](../business/README.md) para templates disponíveis.

Novo nicho = novo arquivo + `BUSINESS_FILE=business/novo_nicho.yaml`. O código do assistente não muda.

## 10. Estrutura de código

```
src/assistant/
  config.py          ✅
  business.py        ✅
  store.py           SQLite
  llm.py             OpenAI-compatible + fallback
  calendar.py        Google Calendar REST
  whatsapp.py        WAHA client + HMAC verify
  tools.py           Tool definitions + executors
  agents/
    router.py
    faq.py
    scheduler.py
    handoff.py
  orchestrator.py    Pipeline principal
  reminders.py       Background job
  main.py            FastAPI app
  simulator.py       CLI terminal
tests/
  test_business.py
  test_store.py
  test_calendar.py   (mock HTTP)
  test_webhook.py
  test_agents.py
docker-compose.yml
Caddyfile
docs/DEPLOY.md
```

---

## 10. Simulador (dev sem WhatsApp)

```bash
assistant-simulator
# ou: python -m assistant.simulator
```

Loop REPL: digita como cliente → orquestrador responde → mostra tool calls no debug.

---

## 11. Roadmap pós-MVP

1. Painel simples (FastAPI + HTMX) para editar `business.yaml`.
2. Multi-loja (tenant_id por número WAHA).
3. Cobrança Stripe/R$ 79/mês.
4. Migrar para API oficial Meta (quando volume justificar).
5. Confirmação por botão WhatsApp (WAHA suporta).

---

## 12. Critérios de aceite MVP

- [ ] Cliente pergunta preço → resposta correta do YAML
- [ ] Cliente agenda banho → evento no Google Calendar
- [ ] Cliente remarca/cancela → Calendar atualizado
- [ ] Pergunta desconhecida → dono recebe aviso e resposta repassada
- [ ] Lembrete enviado na véspera (1x por agendamento)
- [ ] Webhook HMAC rejeita requests inválidos
- [ ] Simulador funciona sem WAHA
- [ ] `pytest` passa com mocks (sem segredos reais)
- [ ] Docker Compose sobe na Hetzner com HTTPS
