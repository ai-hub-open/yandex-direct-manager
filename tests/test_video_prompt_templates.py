"""Шаблоны видео-промптов: маппинг типов и ориентации."""
from __future__ import annotations

from scripts.video_prompt_templates import (
    VIDEO_TYPE_BY_CONCEPT_TYPE,
    _get_orientation,
    build_video_prompt,
    detect_video_type,
)


def test_all_concept_types_map_to_video_types():
    expected = {
        "pain_split": "pain_reframe",
        "abstract_brand": "brand_motion",
        "product_offer": "product_showcase",
        "social_proof": "product_showcase",
        "ui_mockup": "product_showcase",
    }
    assert VIDEO_TYPE_BY_CONCEPT_TYPE == expected
    for ctype, vtype in expected.items():
        assert detect_video_type({"type": ctype}) == vtype


def test_unknown_concept_type_defaults_to_product_showcase():
    assert detect_video_type({"type": "something_else"}) == "product_showcase"
    assert detect_video_type({}) == "product_showcase"


def test_orientation_by_aspect():
    assert _get_orientation("16:9") == ("Horizontal", "horizontal")
    assert _get_orientation("9:16") == ("Vertical", "vertical")
    assert _get_orientation("1:1") == ("Square", "square")
    assert _get_orientation("4:3") == ("Horizontal", "horizontal")


def test_build_video_prompt_no_placeholders_and_fallbacks():
    brand = {"product_name": "Acme", "primary_color": "#111", "accent_color": "#222"}
    concept = {"type": "pain_split", "usp_on_creative": "Без боли"}
    prompt = build_video_prompt(concept, brand, duration=7, aspect="9:16")
    assert "{" not in prompt
    assert "7 seconds" in prompt or "7" in prompt
    assert "Vertical" in prompt
    assert "Acme" in prompt
    assert "Без боли" in prompt  # angle падает на usp_on_creative
