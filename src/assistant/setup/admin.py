from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..business import normalize
from ..business_io import dump_business, load_yaml
from ..config import Settings
from ..store import Store
from .parsers import parse_durations, parse_faq_line, parse_hours, parse_prices
from .wizard import SetupWizard, Step


class AdminMode(str, Enum):
    IDLE = "idle"
    MENU = "menu"
    EDIT_BASICS = "edit_basics"
    EDIT_HOURS = "edit_hours"
    ADD_SERVICE_NAME = "add_service_name"
    ADD_SERVICE_PRICES = "add_service_prices"
    ADD_SERVICE_DURATIONS = "add_service_durations"
    EDIT_PRICE_PICK = "edit_price_pick"
    EDIT_PRICE_VARIANT = "edit_price_variant"
    EDIT_PRICE_VALUE = "edit_price_value"
    ADD_FAQ = "add_faq"
    ADD_RULE = "add_rule"
    WIZARD = "wizard"


ADMIN_TRIGGERS = frozenset({
    "configurar", "config", "admin", "!admin", "painel", "menu", "menu admin", "!config",
})


@dataclass(frozen=True)
class AdminResult:
    reply: str
    handled: bool = True
    reload_business: bool = False


@dataclass
class WhatsAppAdmin:
    settings: Settings
    store: Store

    def handle(self, phone: str, text: str) -> AdminResult:
        session = self.store.get_admin_session(phone)
        mode = AdminMode(session.get("mode", AdminMode.IDLE.value))
        lowered = text.strip().lower()

        if lowered in ("sair", "cancelar", "0") and mode != AdminMode.IDLE:
            self.store.clear_admin_session(phone)
            return AdminResult("Painel encerrado.", reload_business=False)

        quick = self._try_quick_command(phone, text)
        if quick is not None:
            if quick.reload_business and mode != AdminMode.IDLE:
                session = self.store.get_admin_session(phone)
                session["draft"] = load_yaml(self.settings.business_file)
                self.store.set_admin_session(phone, session)
            return quick

        if mode == AdminMode.WIZARD:
            return self._handle_wizard(phone, session, text)

        if mode != AdminMode.IDLE:
            return self._handle_flow(phone, session, text)

        if self._is_admin_trigger(lowered):
            return self._open_menu(phone)

        if self.store.latest_open_handoff() is not None:
            return AdminResult("", handled=False)

        return AdminResult(
            "Ola, dono! Digite *configurar* para editar precos, horarios e servicos.\n"
            "Comandos rapidos:\n"
            "  preco Banho pequeno 55\n"
            "  faq Pergunta? | Resposta\n"
            "  horario ter a sex 08:00-18:00",
        )

    def _open_menu(self, phone: str) -> AdminResult:
        draft = load_yaml(self.settings.business_file)
        self.store.set_admin_session(phone, {"mode": AdminMode.MENU.value, "draft": draft})
        return AdminResult(self._menu_text(draft))

    def _menu_text(self, draft: dict[str, Any]) -> str:
        name = draft.get("nome", "Negocio")
        services = draft.get("servicos") or []
        return (
            f"*Painel de configuracao* — {name}\n\n"
            "1 — Dados basicos (nome, endereco, pagamento)\n"
            "2 — Horarios\n"
            "3 — Adicionar servico\n"
            "4 — Alterar preco\n"
            "5 — Adicionar FAQ\n"
            "6 — Adicionar regra\n"
            "7 — Ver resumo\n"
            "8 — Assistente completo (revisar tudo)\n"
            "0 — Sair\n\n"
            f"Servicos cadastrados: {len(services)}"
        )

    def _handle_flow(self, phone: str, session: dict[str, Any], text: str) -> AdminResult:
        mode = AdminMode(session["mode"])
        draft = dict(session.get("draft") or {})

        if mode == AdminMode.MENU:
            choice = text.strip().lower()
            if choice in ("1", "dados", "basicos"):
                session["mode"] = AdminMode.EDIT_BASICS.value
                self.store.set_admin_session(phone, session)
                current = draft.get("nome", "")
                return AdminResult(
                    f"Dados basicos:\n  nome | endereco | pagamento\n"
                    f"Atual: {current} | {draft.get('endereco', '')} | {draft.get('pagamento', '')}"
                )
            if choice in ("2", "horarios", "horario"):
                session["mode"] = AdminMode.EDIT_HOURS.value
                self.store.set_admin_session(phone, session)
                return AdminResult("Informe horarios.\nEx.: ter a sex 08:00-18:00, sab 08:00-14:00")
            if choice in ("3", "servico", "adicionar servico"):
                session["mode"] = AdminMode.ADD_SERVICE_NAME.value
                self.store.set_admin_session(phone, session)
                return AdminResult("Nome do novo servico:")
            if choice in ("4", "preco", "alterar preco"):
                session["mode"] = AdminMode.EDIT_PRICE_PICK.value
                self.store.set_admin_session(phone, session)
                return AdminResult(self._service_list(draft))
            if choice in ("5", "faq"):
                session["mode"] = AdminMode.ADD_FAQ.value
                self.store.set_admin_session(phone, session)
                return AdminResult("FAQ no formato: pergunta? | resposta")
            if choice in ("6", "regra"):
                session["mode"] = AdminMode.ADD_RULE.value
                self.store.set_admin_session(phone, session)
                return AdminResult("Digite a regra (pode ser mais de uma linha):")
            if choice in ("7", "resumo", "ver"):
                return AdminResult(self._summary(draft))
            if choice in ("8", "completo", "assistente"):
                return self._start_wizard(phone, draft)
            return AdminResult("Opcao invalida.\n\n" + self._menu_text(draft))

        if mode == AdminMode.EDIT_BASICS:
            parts = [p.strip() for p in text.split("|")]
            if parts and parts[0]:
                draft["nome"] = parts[0]
            if len(parts) > 1:
                draft["endereco"] = parts[1]
            if len(parts) > 2:
                draft["pagamento"] = parts[2]
            return self._save_and_menu(phone, draft, "Dados basicos atualizados.")

        if mode == AdminMode.EDIT_HOURS:
            try:
                draft["horarios"] = parse_hours(text)
            except ValueError as exc:
                return AdminResult(str(exc))
            return self._save_and_menu(phone, draft, "Horarios atualizados.")

        if mode == AdminMode.ADD_SERVICE_NAME:
            session["pending_service"] = {"nome": text.strip()}
            session["mode"] = AdminMode.ADD_SERVICE_PRICES.value
            variants = ", ".join((draft.get("variantes") or {}).keys())
            self.store.set_admin_session(phone, session)
            return AdminResult(f"Precos para *{text.strip()}* ({variants}):\nEx.: pequeno 50 medio 70")

        if mode == AdminMode.ADD_SERVICE_PRICES:
            variants = list((draft.get("variantes") or {}).keys())
            try:
                session["pending_service"]["precos"] = parse_prices(text, variants)
            except ValueError as exc:
                return AdminResult(str(exc))
            session["mode"] = AdminMode.ADD_SERVICE_DURATIONS.value
            self.store.set_admin_session(phone, session)
            return AdminResult("Duracao em minutos.\nEx.: pequeno 60 medio 90")

        if mode == AdminMode.ADD_SERVICE_DURATIONS:
            variants = list((draft.get("variantes") or {}).keys())
            try:
                pending = dict(session.get("pending_service") or {})
                pending["duracao_min"] = parse_durations(text, variants)
            except ValueError as exc:
                return AdminResult(str(exc))
            services = list(draft.get("servicos") or [])
            services.append(pending)
            draft["servicos"] = services
            session.pop("pending_service", None)
            return self._save_and_menu(phone, draft, f"Servico *{pending['nome']}* adicionado.")

        if mode == AdminMode.EDIT_PRICE_PICK:
            svc = self._find_service(draft, text)
            if svc is None:
                return AdminResult("Servico nao encontrado.\n" + self._service_list(draft))
            session["edit_service"] = svc["nome"]
            session["mode"] = AdminMode.EDIT_PRICE_VARIANT.value
            variants = ", ".join((draft.get("variantes") or {}).keys())
            self.store.set_admin_session(phone, session)
            prices = svc.get("precos") or {}
            current = ", ".join(f"{k} R${v:.0f}" for k, v in prices.items())
            return AdminResult(f"Precos atuais de *{svc['nome']}*: {current}\nQual variante alterar? ({variants})")

        if mode == AdminMode.EDIT_PRICE_VARIANT:
            variant = normalize(text)
            if variant not in (draft.get("variantes") or {}):
                return AdminResult("Variante invalida.")
            session["edit_variant"] = variant
            session["mode"] = AdminMode.EDIT_PRICE_VALUE.value
            self.store.set_admin_session(phone, session)
            return AdminResult(f"Novo preco para {variant}:")

        if mode == AdminMode.EDIT_PRICE_VALUE:
            match = re.search(r"(\d+(?:[.,]\d+)?)", text.replace(",", "."))
            if not match:
                return AdminResult("Informe o valor numerico.")
            value = float(match.group(1))
            svc_name = session["edit_service"]
            variant = session["edit_variant"]
            for svc in draft.get("servicos") or []:
                if normalize(svc["nome"]) == normalize(svc_name):
                    svc.setdefault("precos", {})[variant] = value
            session.pop("edit_service", None)
            session.pop("edit_variant", None)
            return self._save_and_menu(phone, draft, f"Preco de {svc_name} ({variant}) = R$ {value:.0f}")

        if mode == AdminMode.ADD_FAQ:
            try:
                item = parse_faq_line(text)
            except ValueError as exc:
                return AdminResult(str(exc))
            if item:
                faq = list(draft.get("faq") or [])
                faq.append(item)
                draft["faq"] = faq
            return self._save_and_menu(phone, draft, "FAQ adicionada.")

        if mode == AdminMode.ADD_RULE:
            rules = list(draft.get("regras") or [])
            rules.extend(line.strip() for line in text.split("\n") if line.strip())
            draft["regras"] = rules
            return self._save_and_menu(phone, draft, "Regra adicionada.")

        return self._open_menu(phone)

    def _handle_wizard(self, phone: str, session: dict[str, Any], text: str) -> AdminResult:
        wizard = SetupWizard.from_state(session.get("wizard") or {})
        wizard.whatsapp_mode = True
        wizard.fixed_save_path = self.settings.business_file
        wizard._saved_path = self.settings.business_file
        reply = wizard.handle(text)
        if wizard.step == Step.DONE:
            self.store.clear_admin_session(phone)
            return AdminResult(reply + "\n\nConfiguracao aplicada. O assistente ja usa os dados novos.", reload_business=True)
        session["wizard"] = wizard.to_state()
        session["mode"] = AdminMode.WIZARD.value
        self.store.set_admin_session(phone, session)
        return AdminResult(reply)

    def _start_wizard(self, phone: str, draft: dict[str, Any]) -> AdminResult:
        wizard = SetupWizard()
        wizard.whatsapp_mode = True
        wizard.fixed_save_path = self.settings.business_file
        wizard._saved_path = self.settings.business_file
        wizard.draft = draft
        wizard._sync_variants()
        wizard.step = Step.BASICS
        reply = (
            "Assistente completo iniciado.\n"
            + wizard._prompt_basics()
            + "\n\n(Digite 'pular' para manter cada etapa. 'cancelar' aborta.)"
        )
        self.store.set_admin_session(phone, {"mode": AdminMode.WIZARD.value, "wizard": wizard.to_state()})
        return AdminResult(reply)

    def _save_and_menu(self, phone: str, draft: dict[str, Any], message: str) -> AdminResult:
        dump_business(draft, self.settings.business_file)
        self.store.set_admin_session(phone, {"mode": AdminMode.MENU.value, "draft": draft})
        return AdminResult(f"{message}\n\n" + self._menu_text(draft), reload_business=True)

    def _try_quick_command(self, phone: str, text: str) -> AdminResult | None:
        stripped = text.strip()
        lowered = stripped.lower()

        if lowered.startswith("preco "):
            parts = stripped.split()
            if len(parts) < 4:
                return AdminResult("Uso: preco Banho pequeno 55")
            _, svc_name, variant, raw_value, *_ = parts
            match = re.search(r"(\d+(?:[.,]\d+)?)", raw_value.replace(",", "."))
            if not match:
                return AdminResult("Preco invalido.")
            draft = load_yaml(self.settings.business_file)
            svc = self._find_service(draft, svc_name)
            if svc is None:
                return AdminResult(f"Servico nao encontrado: {svc_name}")
            variant_key = normalize(variant)
            if variant_key not in (draft.get("variantes") or {}):
                return AdminResult(f"Variante invalida: {variant}")
            svc.setdefault("precos", {})[variant_key] = float(match.group(1))
            dump_business(draft, self.settings.business_file)
            return AdminResult(
                f"Preco atualizado: {svc['nome']} ({variant_key}) = R$ {float(match.group(1)):.0f}",
                reload_business=True,
            )

        if lowered.startswith("faq "):
            try:
                item = parse_faq_line(stripped[4:])
            except ValueError as exc:
                return AdminResult(str(exc))
            draft = load_yaml(self.settings.business_file)
            faq = list(draft.get("faq") or [])
            faq.append(item)
            draft["faq"] = faq
            dump_business(draft, self.settings.business_file)
            return AdminResult("FAQ adicionada.", reload_business=True)

        if lowered.startswith("horario ") or lowered.startswith("horarios "):
            raw = stripped.split(" ", 1)[1]
            try:
                hours = parse_hours(raw)
            except ValueError as exc:
                return AdminResult(str(exc))
            draft = load_yaml(self.settings.business_file)
            draft["horarios"] = hours
            dump_business(draft, self.settings.business_file)
            return AdminResult("Horarios atualizados.", reload_business=True)

        if lowered.startswith("servico "):
            name = stripped.split(" ", 1)[1].strip()
            if not name:
                return AdminResult("Uso: servico Nome do servico")
            session = {"mode": AdminMode.ADD_SERVICE_NAME.value, "draft": load_yaml(self.settings.business_file)}
            self.store.set_admin_session(phone, session)
            return self._handle_flow(phone, session, name)

        return None

    @staticmethod
    def _is_admin_trigger(text: str) -> bool:
        return text in ADMIN_TRIGGERS or text.startswith("!")

    @staticmethod
    def _find_service(draft: dict[str, Any], name: str) -> dict[str, Any] | None:
        wanted = normalize(name)
        for svc in draft.get("servicos") or []:
            if normalize(str(svc.get("nome", ""))) == wanted:
                return svc
        return None

    @staticmethod
    def _service_list(draft: dict[str, Any]) -> str:
        lines = ["Qual servico?"]
        for svc in draft.get("servicos") or []:
            prices = svc.get("precos") or {}
            summary = ", ".join(f"{k} R${v:.0f}" for k, v in prices.items())
            lines.append(f"  • {svc['nome']}: {summary}")
        return "\n".join(lines)

    @staticmethod
    def _summary(draft: dict[str, Any]) -> str:
        services = draft.get("servicos") or []
        faq = draft.get("faq") or []
        rules = draft.get("regras") or []
        variants = ", ".join((draft.get("variantes") or {}).keys())
        return (
            f"*{draft.get('nome', '?')}* ({draft.get('segmento', '?')})\n"
            f"Endereco: {draft.get('endereco', '-')}\n"
            f"Variantes: {variants}\n"
            f"Servicos: {len(services)} | FAQ: {len(faq)} | Regras: {len(rules)}"
        )
