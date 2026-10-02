from pathlib import Path

import pytest

from petshop.business import load_business
from petshop.business_io import dump_business
from petshop.setup.parsers import parse_hours, parse_prices, parse_variants
from petshop.setup.wizard import SetupWizard, Step


def test_parse_hours_week_range():
    hours = parse_hours("ter a sex 08:00-18:00, sab 08:00-14:00")
    assert "ter" in hours and "sex" in hours and "sab" in hours
    assert hours["ter"] == ["08:00-18:00"]


def test_parse_variants_and_prices():
    variants = parse_variants("pequeno: ate 10kg, medio: 10-25kg, grande: acima 25kg")
    keys = list(variants.keys())
    prices = parse_prices("pequeno 50 medio 70 grande 90", keys)
    assert prices["medio"] == 70.0


def test_parse_unico_price():
    variants = parse_variants("unico")
    prices = parse_prices("45", list(variants.keys()))
    assert prices["unico"] == 45.0


def test_wizard_full_flow_saves_valid_yaml(tmp_path: Path):
    wizard = SetupWizard(business_dir=tmp_path / "business")
    (tmp_path / "business").mkdir(parents=True)
    assert "Como quer comecar" in wizard.start()

    wizard.handle("1")
    wizard.handle("barbearia")
    wizard.handle("Barbearia Teste | Rua X, 1 | Pix")
    wizard.handle("pular")
    wizard.handle("seg a sex 09:00-19:00")
    wizard.handle("cabelo: corte, barba: barba, combo: combo")
    wizard.handle("Corte cabelo")
    wizard.handle("cabelo 40 barba 30 combo 65")
    wizard.handle("cabelo 30 barba 20 combo 45")
    wizard.handle("pronto")
    wizard.handle("nao")
    wizard.handle("pular")
    wizard.handle("pular")
    wizard.handle("pular")
    wizard.handle("Atendemos com horario marcado.")
    out = tmp_path / "business" / "barbearia_teste.yaml"
    wizard.handle(str(out))
    reply = wizard.handle("sim")

    assert wizard.step == Step.DONE
    assert "BUSINESS_FILE=" in reply
    assert out.is_file()
    biz = load_business(out)
    assert biz.segment == "barbearia"
    assert biz.service("Corte cabelo") is not None


def test_wizard_from_template(tmp_path: Path):
    src = Path(__file__).resolve().parents[1] / "business"
    wizard = SetupWizard(business_dir=src)
    wizard.start()
    wizard.handle("2")
    wizard.handle("salao")
    assert wizard.draft.get("segmento") == "salao"
    wizard.handle("pular")
    wizard.handle("pular")
    wizard.handle("pular")
    wizard.handle("pular")
    wizard.handle("pronto")
    wizard.handle("nao")
    wizard.handle("pular")
    wizard.handle("pular")
    wizard.handle("pular")
    wizard.handle("pular")
    out = tmp_path / "salao_copy.yaml"
    wizard.handle(str(out))
    wizard.handle("sim")
    assert out.is_file()


def test_dump_validates_incomplete():
    with pytest.raises(ValueError):
        dump_business({"nome": "X"}, Path("fake.yaml"))
