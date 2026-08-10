"""Генерация картинок: dry-run, статусы лога, фильтры, лимит 5."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.generate_creative_images import (
    load_brand_config,
    load_creatives,
    run_generation,
)


def _workspace(tmp_path, creatives=None, brand=None):
    ws = tmp_path / "ws"
    ws.mkdir()
    if brand is not None:
        (ws / "brand.json").write_text(json.dumps(brand, ensure_ascii=False), encoding="utf-8")
    data = creatives if creatives is not None else {
        "campaign_name": "C",
        "groups": [{
            "name": "G1",
            "combined_ad": {
                "titles": ["T"],
                "texts": ["X"],
                "visual_concepts": [
                    {"id": "A", "type": "product_offer", "angle": "цена",
                     "usp_on_creative": "Дешевле"},
                    {"id": "B", "type": "ui_mockup", "angle": "скриншот кабинета"},
                ],
                "images": [],
            },
        }],
    }
    (ws / "08_creatives.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return ws


def test_load_brand_prefers_local(tmp_path):
    ws = _workspace(tmp_path, brand={"product_name": "Local", "primary_color": "#000",
                                     "accent_color": "#111"})
    assert load_brand_config(ws)["product_name"] == "Local"


def test_load_brand_defaults_strip_underscore_keys(tmp_path):
    ws = tmp_path / "empty"
    ws.mkdir()
    brand = load_brand_config(ws)
    assert not any(k.startswith("_") for k in brand)
    assert "product_name" in brand


def test_load_creatives_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="Шаг 8"):
        load_creatives(tmp_path / "nope")


def test_dry_run_writes_prompts_without_touching_creatives(tmp_path):
    ws = _workspace(tmp_path)
    before = (ws / "08_creatives.json").read_text(encoding="utf-8")
    code = run_generation(ws, "gpt-image-1", dry_run=True, force=False,
                          only_group=None, only_concept=None)
    assert code == 0
    prompts = list((ws / "assets" / "prompts").glob("*.txt"))
    assert prompts
    log = json.loads((ws / "assets" / "generation_log.json").read_text(encoding="utf-8"))
    assert all(e["status"] == "dry_run" for e in log)
    assert (ws / "08_creatives.json").read_text(encoding="utf-8") == before


def test_no_visual_concepts(tmp_path, monkeypatch, fast_sleep):
    ws = _workspace(tmp_path, creatives={
        "groups": [{"name": "G", "combined_ad": {"visual_concepts": [], "images": []}}],
    })
    monkeypatch.setattr(
        "scripts.generate_creative_images.load_api_key", lambda *_a, **_k: "sk-test"
    )
    code = run_generation(ws, "gpt-image-1", dry_run=False, force=False,
                          only_group=None, only_concept=None)
    assert code == 0
    log = json.loads((ws / "assets" / "generation_log.json").read_text(encoding="utf-8"))
    assert log[0]["status"] == "no_visual_concepts"


def test_ui_mockup_skips_api(tmp_path, monkeypatch, fast_sleep):
    called = []

    def fake_gen(*a, **k):
        called.append(1)
        return True

    monkeypatch.setattr("scripts.generate_creative_images.load_api_key", lambda *_a, **_k: "sk")
    monkeypatch.setattr("scripts.generate_creative_images.generate_via_openai", fake_gen)
    monkeypatch.setattr("scripts.generate_creative_images.postprocess", lambda *a, **k: None)

    ws = _workspace(tmp_path, creatives={
        "groups": [{
            "name": "G",
            "combined_ad": {
                "visual_concepts": [
                    {"id": "A", "type": "ui_mockup", "angle": "скриншот", "formats": ["1x1"]},
                ],
                "images": [],
            },
        }],
    })
    run_generation(ws, "gpt-image-1", dry_run=False, force=False, only_group=None, only_concept=None)
    log = json.loads((ws / "assets" / "generation_log.json").read_text(encoding="utf-8"))
    assert log[0]["status"] == "needs_real_screenshot"
    assert called == []


def test_exists_without_force_still_adds_path(tmp_path, monkeypatch, fast_sleep):
    monkeypatch.setattr("scripts.generate_creative_images.load_api_key", lambda *_a, **_k: "sk")
    called = []
    monkeypatch.setattr(
        "scripts.generate_creative_images.generate_via_openai",
        lambda *a, **k: called.append(1) or True,
    )
    monkeypatch.setattr("scripts.generate_creative_images.postprocess", lambda *a, **k: None)

    ws = _workspace(tmp_path, creatives={
        "groups": [{
            "name": "G",
            "combined_ad": {
                "visual_concepts": [
                    {"id": "A", "type": "product_offer", "angle": "x",
                     "usp_on_creative": "U", "formats": ["1x1"]},
                ],
                "images": [],
            },
        }],
    })
    img = ws / "assets" / "images" / "g1_A_1x1.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"png")

    run_generation(ws, "gpt-image-1", dry_run=False, force=False, only_group=None, only_concept=None)
    assert called == []
    data = json.loads((ws / "08_creatives.json").read_text(encoding="utf-8"))
    assert "assets/images/g1_A_1x1.png" in data["groups"][0]["combined_ad"]["images"]
    log = json.loads((ws / "assets" / "generation_log.json").read_text(encoding="utf-8"))
    assert log[0]["status"] == "exists"


def test_force_regenerates(tmp_path, monkeypatch, fast_sleep):
    monkeypatch.setattr("scripts.generate_creative_images.load_api_key", lambda *_a, **_k: "sk")
    called = []

    def fake_gen(prompt, size, model, output_path, api_key=None):
        called.append(str(output_path))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"new")
        return True

    monkeypatch.setattr("scripts.generate_creative_images.generate_via_openai", fake_gen)
    monkeypatch.setattr("scripts.generate_creative_images.postprocess", lambda *a, **k: None)

    ws = _workspace(tmp_path, creatives={
        "groups": [{
            "name": "G",
            "combined_ad": {
                "visual_concepts": [
                    {"id": "A", "type": "product_offer", "angle": "x",
                     "usp_on_creative": "U", "formats": ["1x1"]},
                ],
                "images": [],
            },
        }],
    })
    img = ws / "assets" / "images" / "g1_A_1x1.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"old")

    run_generation(ws, "gpt-image-1", dry_run=False, force=True, only_group=None, only_concept=None)
    assert called
    assert img.read_bytes() == b"new"


def test_failed_generation_does_not_add_path(tmp_path, monkeypatch, fast_sleep):
    monkeypatch.setattr("scripts.generate_creative_images.load_api_key", lambda *_a, **_k: "sk")
    monkeypatch.setattr("scripts.generate_creative_images.generate_via_openai", lambda *a, **k: False)
    monkeypatch.setattr("scripts.generate_creative_images.postprocess", lambda *a, **k: None)

    ws = _workspace(tmp_path, creatives={
        "groups": [{
            "name": "G",
            "combined_ad": {
                "visual_concepts": [
                    {"id": "A", "type": "product_offer", "angle": "x",
                     "usp_on_creative": "U", "formats": ["1x1"]},
                ],
                "images": [],
            },
        }],
    })
    before = (ws / "08_creatives.json").read_text(encoding="utf-8")
    run_generation(ws, "gpt-image-1", dry_run=False, force=False, only_group=None, only_concept=None)
    log = json.loads((ws / "assets" / "generation_log.json").read_text(encoding="utf-8"))
    assert log[0]["status"] == "failed"
    assert (ws / "08_creatives.json").read_text(encoding="utf-8") == before


def test_images_capped_at_five(tmp_path, monkeypatch, fast_sleep):
    monkeypatch.setattr("scripts.generate_creative_images.load_api_key", lambda *_a, **_k: "sk")

    def fake_gen(prompt, size, model, output_path, api_key=None):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"x")
        return True

    monkeypatch.setattr("scripts.generate_creative_images.generate_via_openai", fake_gen)
    monkeypatch.setattr("scripts.generate_creative_images.postprocess", lambda *a, **k: None)

    concepts = [
        {"id": "A", "type": "product_offer", "angle": "a", "usp_on_creative": "U",
         "formats": ["1x1", "4x3", "16x9"]},
        {"id": "B", "type": "product_offer", "angle": "b", "usp_on_creative": "U",
         "formats": ["1x1", "4x3", "16x9"]},
    ]
    ws = _workspace(tmp_path, creatives={
        "groups": [{"name": "G", "combined_ad": {"visual_concepts": concepts, "images": []}}],
    })
    run_generation(ws, "gpt-image-1", dry_run=False, force=False, only_group=None, only_concept=None)
    data = json.loads((ws / "08_creatives.json").read_text(encoding="utf-8"))
    assert len(data["groups"][0]["combined_ad"]["images"]) == 5


def test_group_and_concept_filters(tmp_path, monkeypatch, fast_sleep):
    monkeypatch.setattr("scripts.generate_creative_images.load_api_key", lambda *_a, **_k: "sk")
    names = []

    def fake_gen(prompt, size, model, output_path, api_key=None):
        names.append(Path(output_path).stem)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"x")
        return True

    monkeypatch.setattr("scripts.generate_creative_images.generate_via_openai", fake_gen)
    monkeypatch.setattr("scripts.generate_creative_images.postprocess", lambda *a, **k: None)

    ws = _workspace(tmp_path, creatives={
        "groups": [
            {"name": "G1", "combined_ad": {
                "visual_concepts": [
                    {"id": "A", "type": "product_offer", "angle": "a",
                     "usp_on_creative": "U", "formats": ["1x1"]},
                    {"id": "B", "type": "product_offer", "angle": "b",
                     "usp_on_creative": "U", "formats": ["1x1"]},
                ],
                "images": [],
            }},
            {"name": "G2", "combined_ad": {
                "visual_concepts": [
                    {"id": "A", "type": "product_offer", "angle": "a",
                     "usp_on_creative": "U", "formats": ["1x1"]},
                ],
                "images": [],
            }},
        ],
    })
    run_generation(ws, "gpt-image-1", dry_run=False, force=False, only_group="1", only_concept="B")
    assert names == ["g1_B_1x1"]
