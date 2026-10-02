from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..business_io import available_templates, dump_business, load_template, load_yaml
from ..config import ROOT
from .parsers import parse_durations, parse_faq_line, parse_hours, parse_package, parse_prices, parse_variants


class Step(str, Enum):
    WELCOME = "welcome"
    MODE = "mode"
    TEMPLATE = "template"
    SEGMENT = "segment"
    BASICS = "basics"
    LABELS = "labels"
    HOURS = "hours"
    VARIANTS = "variants"
    SERVICE_NAME = "service_name"
    SERVICE_PRICES = "service_prices"
    SERVICE_DURATIONS = "service_durations"
    MORE_SERVICES = "more_services"
    PACKAGES = "packages"
    RULES = "rules"
    FAQ = "faq"
    GREETING = "greeting"
    FILENAME = "filename"
    PREVIEW = "preview"
    DONE = "done"


NICHE_HINTS: dict[str, dict[str, Any]] = {
    "pet_shop": {
        "tipo": "pet shop de banho e tosa",
        "labels": {"variantes": "porte", "sujeito": "nome do pet"},
        "variantes": {"pequeno": "ate 10 kg", "medio": "de 10 a 25 kg", "grande": "acima de 25 kg"},
        "saudacao": "Posso ajudar com precos, horarios ou agendar banho e tosa.",
    },
    "salao": {
        "tipo": "salao de beleza",
        "labels": {"variantes": "tipo de corte", "sujeito": "nome do cliente"},
        "variantes": {"masculino": "corte masculino", "feminino": "corte feminino", "infantil": "ate 12 anos"},
        "saudacao": "Posso informar precos, horarios ou agendar corte, escova e tratamentos.",
    },
    "barbearia": {
        "tipo": "barbearia",
        "labels": {"variantes": "tipo de servico", "sujeito": "nome do cliente"},
        "variantes": {"barba": "barba", "cabelo": "cabelo", "combo": "cabelo + barba"},
        "saudacao": "Posso informar precos, horarios ou agendar corte e barba.",
    },
}


@dataclass
class SetupWizard:
    business_dir: Path = field(default_factory=lambda: ROOT / "business")
    draft: dict[str, Any] = field(default_factory=dict)
    step: Step = Step.WELCOME
    _pending_service: dict[str, Any] = field(default_factory=dict)
    _variant_keys: list[str] = field(default_factory=list)
    _saved_path: Path | None = None
    whatsapp_mode: bool = False
    fixed_save_path: Path | None = None

    def to_state(self) -> dict[str, Any]:
        return {
            "business_dir": str(self.business_dir),
            "draft": self.draft,
            "step": self.step.value,
            "pending_service": self._pending_service,
            "variant_keys": self._variant_keys,
            "saved_path": str(self._saved_path) if self._saved_path else None,
            "whatsapp_mode": self.whatsapp_mode,
            "fixed_save_path": str(self.fixed_save_path) if self.fixed_save_path else None,
        }

    @classmethod
    def from_state(cls, data: dict[str, Any]) -> SetupWizard:
        wizard = cls(
            business_dir=Path(data.get("business_dir") or ROOT / "business"),
            draft=dict(data.get("draft") or {}),
            step=Step(data.get("step", Step.WELCOME.value)),
            _pending_service=dict(data.get("pending_service") or {}),
            _variant_keys=list(data.get("variant_keys") or []),
            whatsapp_mode=bool(data.get("whatsapp_mode")),
        )
        if data.get("saved_path"):
            wizard._saved_path = Path(data["saved_path"])
        if data.get("fixed_save_path"):
            wizard.fixed_save_path = Path(data["fixed_save_path"])
        if not wizard._variant_keys:
            wizard._sync_variants()
        return wizard

    def start(self) -> str:
        self.step = Step.MODE
        templates = ", ".join(available_templates(business_dir=self.business_dir)[:6])
        return (
            "Ola! Vou te ajudar a montar o arquivo de configuracao do seu negocio.\n\n"
            "Como quer comecar?\n"
            "  1 — Do zero\n"
            "  2 — A partir de um template existente\n"
            "  3 — Editar um arquivo que ja existe\n\n"
            f"Templates disponiveis: {templates or 'nenhum'}"
        )

    def handle(self, message: str) -> str:
        text = message.strip()
        if text.lower() in ("cancelar", "sair", "exit", "quit") and self.step != Step.DONE:
            self.step = Step.DONE
            return "Configuracao cancelada. Nada foi salvo."
        if text.lower() in ("voltar", "back") and self.step != Step.WELCOME:
            return self._go_back()

        handlers = {
            Step.MODE: self._handle_mode,
            Step.TEMPLATE: self._handle_template,
            Step.SEGMENT: self._handle_segment,
            Step.BASICS: self._handle_basics,
            Step.LABELS: self._handle_labels,
            Step.HOURS: self._handle_hours,
            Step.VARIANTS: self._handle_variants,
            Step.SERVICE_NAME: self._handle_service_name,
            Step.SERVICE_PRICES: self._handle_service_prices,
            Step.SERVICE_DURATIONS: self._handle_service_durations,
            Step.MORE_SERVICES: self._handle_more_services,
            Step.PACKAGES: self._handle_packages,
            Step.RULES: self._handle_rules,
            Step.FAQ: self._handle_faq,
            Step.GREETING: self._handle_greeting,
            Step.FILENAME: self._handle_filename,
            Step.PREVIEW: self._handle_preview,
            Step.DONE: lambda _: "Sessao encerrada.",
        }
        handler = handlers.get(self.step)
        if handler is None:
            return self.start()
        return handler(text)

    def _go_back(self) -> str:
        order = [
            Step.MODE,
            Step.TEMPLATE,
            Step.SEGMENT,
            Step.BASICS,
            Step.LABELS,
            Step.HOURS,
            Step.VARIANTS,
            Step.SERVICE_NAME,
        ]
        if self.step in order[1:]:
            idx = order.index(self.step) - 1
            self.step = order[idx]
        prompt = {
            Step.MODE: self.start(),
            Step.SEGMENT: self._prompt_segment(),
            Step.BASICS: self._prompt_basics(),
            Step.LABELS: self._prompt_labels(),
            Step.HOURS: self._prompt_hours(),
            Step.VARIANTS: self._prompt_variants(),
            Step.SERVICE_NAME: self._prompt_service_name(),
        }
        return "Ok, voltando.\n\n" + prompt.get(self.step, self.start())

    def _handle_mode(self, text: str) -> str:
        choice = text.strip().lower()
        if choice in ("1", "zero", "do zero", "novo"):
            self.draft = _empty_draft()
            self.step = Step.SEGMENT
            return self._prompt_segment()
        if choice in ("2", "template", "modelo"):
            self.step = Step.TEMPLATE
            templates = "\n".join(f"  - {name}" for name in available_templates(business_dir=self.business_dir))
            return f"Qual template usar como base?\n{templates}\n\nDigite o nome (ex.: pet_shop ou salao)."
        if choice in ("3", "editar", "edit"):
            self.step = Step.TEMPLATE
            return "Digite o caminho do arquivo YAML (ex.: business/pet_shop.yaml)."
        return "Escolha 1, 2 ou 3."

    def _handle_template(self, text: str) -> str:
        path = Path(text.strip())
        if not path.is_absolute():
            path = ROOT / path
        if path.is_file():
            self.draft = load_yaml(path)
            self._sync_variants()
            self.step = Step.BASICS
            return (
                f"Arquivo carregado: {path}\n\n"
                + self._prompt_basics()
                + "\n\n(Dica: responda 'pular' para manter o valor atual.)"
            )
        try:
            self.draft = load_template(text.strip(), business_dir=self.business_dir)
            self._sync_variants()
            self.step = Step.BASICS
            return (
                f"Template '{text.strip()}' carregado.\n\n"
                + self._prompt_basics()
                + "\n\n(Dica: responda 'pular' para manter o valor do template.)"
            )
        except (FileNotFoundError, ValueError) as exc:
            return f"Nao encontrei esse template/arquivo: {exc}"

    def _handle_segment(self, text: str) -> str:
        segment = _slug_segment(text)
        if not segment:
            return "Informe um identificador curto (ex.: pet_shop, salao, barbearia)."
        self.draft["segmento"] = segment
        hint = NICHE_HINTS.get(segment, {})
        self.draft.setdefault("tipo", hint.get("tipo", segment.replace("_", " ")))
        self.draft.setdefault("labels", hint.get("labels", {"variantes": "categoria", "sujeito": "nome"}))
        if hint.get("variantes"):
            self.draft["variantes"] = dict(hint["variantes"])
        if hint.get("saudacao"):
            self.draft.setdefault("atendimento", {})["saudacao"] = hint["saudacao"]
        self._sync_variants()
        self.step = Step.BASICS
        return self._prompt_basics()

    def _handle_basics(self, text: str) -> str:
        if text.lower() != "pular":
            parts = [part.strip() for part in text.split("|")]
            if len(parts) == 1:
                self.draft["nome"] = parts[0]
            elif len(parts) >= 2:
                self.draft["nome"] = parts[0]
                self.draft["endereco"] = parts[1]
                if len(parts) >= 3:
                    self.draft["pagamento"] = parts[2]
        self.draft.setdefault("telefone_humano", "o proprio numero deste WhatsApp")
        self.step = Step.LABELS
        return self._prompt_labels()

    def _handle_labels(self, text: str) -> str:
        if text.lower() != "pular":
            parts = [part.strip() for part in text.split("|")]
            labels = dict(self.draft.get("labels") or {})
            if parts and parts[0]:
                labels["variantes"] = parts[0]
            if len(parts) > 1 and parts[1]:
                labels["sujeito"] = parts[1]
            self.draft["labels"] = labels
        self.step = Step.HOURS
        return self._prompt_hours()

    def _handle_hours(self, text: str) -> str:
        if text.lower() != "pular":
            try:
                self.draft["horarios"] = parse_hours(text)
            except ValueError as exc:
                return f"{exc}\n\nExemplo: ter a sex 08:00-18:00, sab 08:00-14:00"
        self.step = Step.VARIANTS
        return self._prompt_variants()

    def _handle_variants(self, text: str) -> str:
        if text.lower() != "pular":
            try:
                self.draft["variantes"] = parse_variants(text)
            except ValueError as exc:
                return f"{exc}\n\nExemplo: pequeno: ate 10kg, medio: 10-25kg, grande: acima 25kg\nOu digite 'unico' para preco fixo."
        self._sync_variants()
        self.draft.setdefault("servicos", [])
        self.step = Step.SERVICE_NAME
        return self._prompt_service_name()

    def _handle_service_name(self, text: str) -> str:
        if text.lower() in ("pronto", "fim", "nao", "não", "pular") and self.draft.get("servicos"):
            self.step = Step.MORE_SERVICES
            return self._after_services_prompt()
        if not text.strip():
            return "Informe o nome do servico (ex.: Banho, Corte masculino) ou 'pronto' se ja cadastrou todos."
        self._pending_service = {"nome": text.strip()}
        self.step = Step.SERVICE_PRICES
        variants = ", ".join(self._variant_keys)
        return f"Precos do servico '{text.strip()}' para: {variants}\nEx.: pequeno 50 medio 70 grande 90"

    def _handle_service_prices(self, text: str) -> str:
        try:
            prices = parse_prices(text, self._variant_keys)
        except ValueError as exc:
            return str(exc)
        self._pending_service["precos"] = prices
        self.step = Step.SERVICE_DURATIONS
        return f"Duracao em minutos para '{self._pending_service['nome']}'.\nEx.: pequeno 60 medio 90 grande 120"

    def _handle_service_durations(self, text: str) -> str:
        try:
            durations = parse_durations(text, self._variant_keys)
        except ValueError as exc:
            return str(exc)
        self._pending_service["duracao_min"] = durations
        services = list(self.draft.get("servicos") or [])
        services.append(dict(self._pending_service))
        self.draft["servicos"] = services
        self._pending_service = {}
        self.step = Step.SERVICE_NAME
        names = ", ".join(s["nome"] for s in services)
        return f"Servico salvo. Cadastrados: {names}.\n\nProximo servico (nome) ou digite 'pronto'."

    def _handle_more_services(self, text: str) -> str:
        if text.lower() in ("sim", "s", "mais", "add"):
            self.step = Step.SERVICE_NAME
            return self._prompt_service_name()
        self.step = Step.PACKAGES
        return self._prompt_packages()

    def _handle_packages(self, text: str) -> str:
        if text.lower() in ("nao", "não", "pular", "nenhum", "pronto"):
            self.draft.setdefault("pacotes", [])
            self.step = Step.RULES
            return self._prompt_rules()
        try:
            pkg = parse_package(text, self._variant_keys)
            packages = list(self.draft.get("pacotes") or [])
            packages.append(pkg)
            self.draft["pacotes"] = packages
            return "Pacote adicionado. Outro pacote (mesmo formato) ou 'pronto'."
        except ValueError as exc:
            return f"{exc}\n\nFormato: Nome do pacote | 350  ou  Combo | pequeno 120 medio 150"

    def _handle_rules(self, text: str) -> str:
        if text.lower() not in ("pular", "nao", "não", "nenhuma"):
            rules = list(self.draft.get("regras") or [])
            rules.extend(line.strip() for line in text.split("\n") if line.strip())
            self.draft["regras"] = rules
        self.step = Step.FAQ
        return self._prompt_faq()

    def _handle_faq(self, text: str) -> str:
        if text.lower() in ("pular", "nao", "não", "nenhuma", "pronto"):
            self.step = Step.GREETING
            return self._prompt_greeting()
        try:
            item = parse_faq_line(text)
        except ValueError as exc:
            return f"{exc}\n\nFormato: Voces atendem sabado? | Sim, das 8h as 14h"
        if item:
            faq = list(self.draft.get("faq") or [])
            faq.append(item)
            self.draft["faq"] = faq
        return "FAQ salva. Proxima pergunta/resposta ou 'pronto'."

    def _handle_greeting(self, text: str) -> str:
        if text.lower() != "pular":
            atendimento = dict(self.draft.get("atendimento") or {})
            atendimento["saudacao"] = text.strip()
            self.draft["atendimento"] = atendimento
        self._apply_defaults()
        if self.whatsapp_mode and self.fixed_save_path:
            self._saved_path = self.fixed_save_path
            self.step = Step.PREVIEW
            return self._preview(self.fixed_save_path)
        self.step = Step.FILENAME
        segment = str(self.draft.get("segmento") or "negocio")
        slug = _slug_segment(str(self.draft.get("nome") or segment))
        return (
            f"Em qual arquivo salvar?\n"
            f"Sugestao: business/{segment}_{slug}.yaml\n"
            f"(Enter aceita a sugestao)"
        )

    def _handle_filename(self, text: str) -> str:
        segment = str(self.draft.get("segmento") or "negocio")
        slug = _slug_segment(str(self.draft.get("nome") or segment))
        suggested = f"business/{segment}_{slug}.yaml"
        raw = text.strip() or suggested
        path = Path(raw)
        if not path.is_absolute():
            path = ROOT / path
        if not path.suffix:
            path = path.with_suffix(".yaml")
        self._saved_path = path
        self.step = Step.PREVIEW
        return self._preview(path)

    def _handle_preview(self, text: str) -> str:
        if text.lower() not in ("sim", "s", "ok", "salvar", "yes"):
            self.step = Step.FILENAME
            return "Ok, nao salvei. Informe outro caminho ou 'sim' para confirmar."
        assert self._saved_path is not None
        try:
            dump_business(self.draft, self._saved_path)
        except ValueError as exc:
            self.step = Step.BASICS
            return f"Configuracao incompleta: {exc}\nVamos corrigir."
        rel = self._saved_path.relative_to(ROOT) if self._saved_path.is_relative_to(ROOT) else self._saved_path
        self.step = Step.DONE
        if self.whatsapp_mode:
            return f"Configuracao salva ({rel})."
        return (
            f"Arquivo salvo em: {rel}\n\n"
            f"Proximo passo — no .env:\n"
            f"  BUSINESS_FILE={rel.as_posix()}\n\n"
            "Depois reinicie o assistente ou rode: petshop-simulator"
        )

    def _apply_defaults(self) -> None:
        self.draft.setdefault("atendimentos_simultaneos", 1)
        self.draft.setdefault("intervalo_min", 30)
        self.draft.setdefault("antecedencia_min_horas", 2)
        self.draft.setdefault("dias_max_agenda", 30)
        self.draft.setdefault("servicos", [])
        self.draft.setdefault("pacotes", [])
        self.draft.setdefault("regras", [])
        self.draft.setdefault("faq", [])
        if "tipo" not in self.draft:
            self.draft["tipo"] = str(self.draft.get("segmento", "negocio")).replace("_", " ")

    def _sync_variants(self) -> None:
        variants = self.draft.get("variantes") or {}
        self._variant_keys = list(variants.keys())

    def _after_services_prompt(self) -> str:
        if not self.draft.get("servicos"):
            self.step = Step.SERVICE_NAME
            return "Cadastre pelo menos um servico.\n\n" + self._prompt_service_name()
        return "Quer adicionar mais servicos? (sim/nao)"

    def _preview(self, path: Path) -> str:
        name = self.draft.get("nome", "?")
        services = self.draft.get("servicos") or []
        variants = ", ".join(self._variant_keys)
        lines = [
            "Revise antes de salvar:",
            f"  Negocio: {name} ({self.draft.get('segmento')})",
            f"  Variantes: {variants}",
            f"  Servicos: {len(services)}",
            f"  FAQ: {len(self.draft.get('faq') or [])}",
            f"  Arquivo: {path}",
            "",
            "Salvar? (sim/nao)",
        ]
        return "\n".join(lines)

    def _prompt_segment(self) -> str:
        hints = ", ".join(NICHE_HINTS.keys())
        return (
            f"Qual o tipo do negocio?\n"
            f"Sugestoes: {hints}\n"
            f"Ou digite outro identificador (ex.: estetica, clinica_vet)."
        )

    def _prompt_basics(self) -> str:
        current = self.draft.get("nome", "")
        return (
            "Dados basicos em uma linha:\n"
            "  nome | endereco | formas de pagamento\n"
            f"{'Atual: ' + current if current else 'Ex.: Studio Hair | Rua A, 10 | Pix e cartao'}"
        )

    def _prompt_labels(self) -> str:
        labels = self.draft.get("labels") or {}
        return (
            "Como chamar as categorias de preco e quem e agendado?\n"
            "  categoria | sujeito\n"
            f"Ex.: {labels.get('variantes', 'porte')} | {labels.get('sujeito', 'nome do pet')}\n"
            "(Digite 'pular' para manter.)"
        )

    def _prompt_hours(self) -> str:
        return (
            "Horario de funcionamento.\n"
            "Ex.: ter a sex 08:00-18:00, sab 08:00-14:00\n"
            "(Digite 'pular' para manter o horario atual.)"
        )

    def _prompt_variants(self) -> str:
        current = self.draft.get("variantes") or {}
        if current:
            formatted = ", ".join(f"{k}: {v}" for k, v in current.items())
            return f"Categorias de preco atuais: {formatted}\nAjuste ou digite 'pular'."
        return (
            "Como variam os precos?\n"
            "Ex.: pequeno: ate 10kg, medio: 10-25kg, grande: acima 25kg\n"
            "Ou digite 'unico' se todos os servicos tem um preco so."
        )

    def _prompt_service_name(self) -> str:
        return "Nome do servico (ex.: Banho, Corte, Hospedagem) ou 'pronto' para continuar."

    def _prompt_packages(self) -> str:
        return (
            "Pacotes especiais (opcional).\n"
            "Formato: Nome | preco  ou  Nome | pequeno 120 medio 150\n"
            "Digite 'pular' se nao tiver pacotes."
        )

    def _prompt_rules(self) -> str:
        return "Regras do negocio (uma por linha) ou 'pular'."

    def _prompt_faq(self) -> str:
        return "Pergunta frequente no formato: pergunta? | resposta\nOu 'pular'."

    def _prompt_greeting(self) -> str:
        current = (self.draft.get("atendimento") or {}).get("saudacao", "")
        return (
            "Mensagem de boas-vindas do assistente:\n"
            f"{current or 'Ex.: Posso ajudar com precos, horarios ou agendamentos.'}\n"
            "(Digite 'pular' para manter.)"
        )


def _empty_draft() -> dict[str, Any]:
    return {
        "servicos": [],
        "pacotes": [],
        "regras": [],
        "faq": [],
        "horarios": {},
        "variantes": {},
        "labels": {"variantes": "categoria", "sujeito": "nome"},
        "atendimento": {},
    }


def _slug_segment(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return cleaned[:40]
