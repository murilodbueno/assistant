from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .business import list_templates, parse_business
from .config import ROOT


def load_template(name: str, *, business_dir: Path | None = None) -> dict[str, Any]:
    directory = business_dir or ROOT / "business"
    path = directory / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Template nao encontrado: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Template invalido: {path}")
    return data


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML invalido: {path}")
    return data


def validate_business(data: dict[str, Any]) -> None:
    parse_business(data)
    if not str(data.get("nome", "")).strip():
        raise ValueError("Campo 'nome' e obrigatorio")
    if not str(data.get("segmento", "")).strip():
        raise ValueError("Campo 'segmento' e obrigatorio")
    if not data.get("servicos"):
        raise ValueError("Cadastre ao menos um servico")
    if not (data.get("variantes") or data.get("portes")):
        raise ValueError("Cadastre variantes de preco")
    if not data.get("horarios"):
        raise ValueError("Informe horarios de funcionamento")


def dump_business(data: dict[str, Any], path: Path) -> None:
    validate_business(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.dump(
            data,
            fh,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )


def available_templates(*, business_dir: Path | None = None) -> list[str]:
    return [p.stem for p in list_templates(business_dir)]
