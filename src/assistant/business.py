from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from typing import Any

import yaml

WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")


def normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(stripped.lower().split())


@dataclass(frozen=True)
class Service:
    name: str
    prices: dict[str, float]
    durations: dict[str, int]


@dataclass(frozen=True)
class Business:
    name: str
    segment: str
    kind: str
    hours: dict[int, list[tuple[time, time]]]
    services: list[Service]
    sizes: dict[str, str]
    labels: dict[str, str]
    packages: list[dict[str, Any]]
    capacity: int = 1
    slot_step_min: int = 30
    min_notice_hours: float = 2.0
    max_days_ahead: int = 30
    raw: dict[str, Any] = field(default_factory=dict)

    def service(self, name: str) -> Service | None:
        wanted = normalize(name)
        for svc in self.services:
            if normalize(svc.name) == wanted:
                return svc
        return None

    def size(self, name: str) -> str | None:
        wanted = normalize(name)
        return wanted if wanted in self.sizes else None

    @property
    def greeting(self) -> str:
        atendimento = self.raw.get("atendimento") or {}
        if atendimento.get("saudacao"):
            return str(atendimento["saudacao"])
        return "Posso ajudar com precos, horarios ou agendar servicos."

    @property
    def variant_label(self) -> str:
        return self.labels.get("variantes", "categoria")

    @property
    def subject_label(self) -> str:
        return self.labels.get("sujeito", "nome")


def _parse_range(raw: str) -> tuple[time, time]:
    start, end = (part.strip() for part in raw.split("-"))
    return time.fromisoformat(start), time.fromisoformat(end)


def _parse_packages(data: list[Any]) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        pkg = dict(item)
        if "precos" in pkg and isinstance(pkg["precos"], dict):
            pkg["precos"] = {normalize(k): float(v) for k, v in pkg["precos"].items()}
        packages.append(pkg)
    return packages


def parse_business(data: dict[str, Any]) -> Business:
    hours: dict[int, list[tuple[time, time]]] = {}
    for key, ranges in (data.get("horarios") or {}).items():
        day = WEEKDAYS.index(normalize(str(key))[:3])
        hours[day] = [_parse_range(r) for r in ranges]
    services = [
        Service(
            name=str(svc["nome"]),
            prices={normalize(k): float(v) for k, v in svc["precos"].items()},
            durations={normalize(k): int(v) for k, v in svc["duracao_min"].items()},
        )
        for svc in data.get("servicos") or []
    ]
    variants = data.get("variantes") or data.get("portes") or {}
    labels = {str(k): str(v) for k, v in (data.get("labels") or {}).items()}
    segment = str(data.get("segmento") or "generico")
    kind = str(data.get("tipo") or data.get("nome") or segment)
    return Business(
        name=str(data.get("nome", "")),
        segment=segment,
        kind=kind,
        hours=hours,
        services=services,
        sizes={normalize(k): str(v) for k, v in variants.items()},
        labels=labels,
        packages=_parse_packages(data.get("pacotes") or []),
        capacity=int(data.get("atendimentos_simultaneos", 1)),
        slot_step_min=int(data.get("intervalo_min", 30)),
        min_notice_hours=float(data.get("antecedencia_min_horas", 2)),
        max_days_ahead=int(data.get("dias_max_agenda", 30)),
        raw=data,
    )


def load_business(path: Path) -> Business:
    with path.open(encoding="utf-8") as fh:
        return parse_business(yaml.safe_load(fh) or {})


def list_templates(directory: Path | None = None) -> list[Path]:
    root = directory or Path(__file__).resolve().parents[2] / "business"
    if not root.is_dir():
        return []
    return sorted(root.glob("*.yaml"))
