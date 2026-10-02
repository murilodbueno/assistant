from pathlib import Path

from assistant.business import list_templates, load_business, normalize


def test_normalize():
    assert normalize("Banho e Tosa") == "banho e tosa"


def test_load_pet_shop_template():
    root = Path(__file__).resolve().parents[1]
    biz = load_business(root / "business" / "pet_shop.yaml")
    assert biz.name == "Pet Shop Exemplo"
    assert biz.segment == "pet_shop"
    assert biz.service("Banho") is not None
    assert biz.size("medio") == "medio"
    assert biz.variant_label == "porte"
    assert biz.packages


def test_load_salao_template():
    root = Path(__file__).resolve().parents[1]
    biz = load_business(root / "business" / "salao.yaml")
    assert biz.segment == "salao"
    assert biz.size("masculino") == "masculino"
    assert biz.service("Corte + escova") is not None
    assert biz.service("Corte + escova").prices["unico"] == 90.0


def test_list_templates():
    root = Path(__file__).resolve().parents[1]
    names = [p.name for p in list_templates(root / "business")]
    assert "pet_shop.yaml" in names
    assert "salao.yaml" in names
