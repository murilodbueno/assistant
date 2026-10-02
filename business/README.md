# Templates por tipo de negócio

Cada arquivo YAML descreve **um nicho**. Para ativar, aponte `BUSINESS_FILE` no `.env`:

```env
BUSINESS_FILE=business/pet_shop.yaml
# ou
BUSINESS_FILE=business/salao.yaml
```

## Arquivos disponíveis

| Arquivo | Nicho |
|---------|-------|
| `pet_shop.yaml` | Pet shop — banho, tosa, hospedagem, day care |
| `salao.yaml` | Salão / cabeleireiro — corte, escova, pacotes |

## Adicionar um nicho novo

1. Copie o template mais parecido (`cp business/salao.yaml business/meu_nicho.yaml`).
2. Ajuste `segmento`, `tipo`, `servicos`, `variantes`, `faq` e `regras`.
3. Defina `BUSINESS_FILE=business/meu_nicho.yaml` no `.env`.
4. Reinicie o app.

## Campos principais

- **segmento** — identificador curto (`pet_shop`, `salao`, `barbearia`…)
- **tipo** — texto humano usado nos prompts da IA
- **variantes** — categorias de preço (porte, tipo de corte, `unico` para preço fixo)
- **servicos** — nome, `precos` e `duracao_min` por variante
- **pacotes** — combos especiais (opcional)
- **labels** — como a IA chama variante e sujeito do agendamento
- **atendimento.saudacao** — mensagem de boas-vindas

O código do assistente é o mesmo para todos os nichos; só muda o YAML carregado.

## Assistente de configuração

Para montar ou editar um YAML conversando no terminal:

```bash
petshop-setup
```

O assistente guia passo a passo: tipo de negócio, horários, serviços, preços, FAQ e salva o arquivo em `business/`.

## Configuração pelo WhatsApp (dono)

Com `OWNER_PHONE` configurado no `.env`, o dono edita direto no WhatsApp:

| Comando | Ação |
|---------|------|
| `configurar` | Abre o painel com menu |
| `preco Banho pequeno 55` | Altera preço rapidamente |
| `faq Pergunta? \| Resposta` | Adiciona FAQ |
| `horario ter a sex 08:00-18:00` | Atualiza horários |
| `servico Tosa higienica` | Inicia cadastro de serviço |
| `0` ou `sair` | Fecha o painel |

Alterações são salvas no YAML e aplicadas na hora, sem reiniciar o servidor.
