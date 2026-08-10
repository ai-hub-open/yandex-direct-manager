"""Шаблоны промптов картинок: план форматов, детект типа, подстановка."""
from __future__ import annotations

from scripts.prompt_templates import (
    IMAGE_SPECS,
    MAX_IMAGES_PER_AD,
    build_format_plan,
    build_prompt,
    detect_creative_type,
)


def _concept(**kw):
    base = {"id": "A", "angle": "быстрый старт", "usp_on_creative": "Старт за день"}
    base.update(kw)
    return base


def test_format_plan_first_concept_three_formats_others_two():
    concepts = [_concept(id="A"), _concept(id="B"), _concept(id="C")]
    plan = build_format_plan(concepts)
    assert len(plan) == MAX_IMAGES_PER_AD
    assert [c["id"] for c, _ in plan].count("A") == 3
    assert [c["id"] for c, _ in plan].count("B") == 2
    assert all(fmt in IMAGE_SPECS for _, fmt in plan)


def test_format_plan_respects_explicit_formats():
    plan = build_format_plan([_concept(formats=["1x1", "3x4"])])
    assert [(c["id"], f) for c, f in plan] == [("A", "1x1"), ("A", "3x4")]


def test_unknown_formats_do_not_consume_slots():
    """Лимит проверяется до IMAGE_SPECS — мусорные форматы не должны съедать слоты."""
    plan = build_format_plan([
        _concept(id="A", formats=["bogus", "also-bad", "1x1", "4x3"]),
        _concept(id="B", formats=["16x9", "nope"]),
    ])
    assert len(plan) <= MAX_IMAGES_PER_AD
    assert all(fmt in IMAGE_SPECS for _, fmt in plan)
    assert ("A", "1x1") in [(c["id"], f) for c, f in plan]


def test_detect_explicit_type_wins():
    assert detect_creative_type(_concept(type="social_proof", angle="скриншот интерфейса")) == "social_proof"


def test_detect_keywords():
    assert detect_creative_type(_concept(angle="скриншот кабинета")) == "ui_mockup"
    assert detect_creative_type(_concept(angle="боль клиента до/после")) == "pain_split"
    assert detect_creative_type(_concept(angle="200+ клиентов и рейтинг")) == "social_proof"
    assert detect_creative_type(_concept(angle="имидж бренда")) == "abstract_brand"
    assert detect_creative_type(_concept(angle="цена и доставка")) == "product_offer"


def test_build_prompt_no_leftover_placeholders():
    brand = {
        "product_name": "AcmeCRM",
        "primary_color": "#111111",
        "accent_color": "#22C55E",
        "style_references": ["flat"],
    }
    prompt = build_prompt(_concept(), brand, {"name": "Группа"}, "4x3")
    assert "{" not in prompt
    assert "AcmeCRM" in prompt
    assert "Старт за день" in prompt
    assert "central 80%" in prompt


def test_build_prompt_usp_falls_back_to_group_name():
    brand = {"product_name": "P", "primary_color": "#000", "accent_color": "#fff"}
    prompt = build_prompt(
        _concept(usp_on_creative=""), brand, {"name": "Имя группы"}, "1x1"
    )
    assert "Имя группы" in prompt


def test_ui_mockup_prompt_skips_yandex_rules_and_colors():
    brand = {"product_name": "Acme"}
    prompt = build_prompt(
        _concept(type="ui_mockup", angle="дашборд"), brand, {"name": "G"}, "1x1"
    )
    assert "PLACEHOLDER" in prompt or "скриншот" in prompt.lower()
    assert "central 80%" not in prompt
    assert "#2D5BFF" not in prompt
