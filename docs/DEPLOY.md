# Deploy na Hetzner (CX22)

## 1. Servidor

1. Crie uma VPS CX22 (Ubuntu 24.04) na Hetzner.
2. Aponte um registro DNS `A` do seu dominio para o IP da VPS.
3. Instale Docker e Docker Compose:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

## 2. Arquivos na VPS

```bash
git clone <seu-repo> assistant
cd assistant
cp .env.example .env
# Edite .env com chaves reais (LLM, WAHA, Google, OWNER_PHONE)
mkdir -p secrets data backups
# Copie google-service-account.json para secrets/
# Escolha o template do nicho em business/ (ex.: salao.yaml)
nano business/salao.yaml
```

Variaveis extras para o Compose:

```bash
echo "DOMAIN=bot.seudominio.com.br" >> .env
# WAHA_HMAC_KEY deve ser igual em .env e no servico waha
```

## 3. Subir

```bash
docker compose up -d --build
docker compose logs -f app
```

## 4. WhatsApp (WAHA)

1. Acesse `https://bot.seudominio.com.br/waha/` (proteja com basic auth no Caddy se exposto).
2. Crie sessao `default` e escaneie o QR code com o WhatsApp do negocio.
3. Confirme webhook em `/webhook/waha`.

## 5. Google Agenda

1. Crie projeto no Google Cloud e habilite Calendar API.
2. Crie conta de servico e baixe JSON para `secrets/google-service-account.json`.
3. Compartilhe a agenda do dono com o e-mail da conta de servico (permissao de editar eventos).
4. Coloque o ID da agenda em `GOOGLE_CALENDAR_ID`.

## 6. Backup SQLite

Cron diario:

```bash
0 3 * * * cd /opt/assistant && sqlite3 data/assistant.db ".backup backups/assistant-$(date +\%F).db"
```

## 7. Healthcheck

Configure UptimeRobot ou similar em `https://bot.seudominio.com.br/health`.

## 8. Simulador local (sem WhatsApp)

```bash
assistant-simulator
```
