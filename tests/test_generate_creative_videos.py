"""Генерация видео: валидация входов, dry-run, статусы, лимит 6."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.generate_creative_videos import run_video_generation


def _ws(tmp_path, creatives=None):
    ws = tmp_path / "ws"
    ws.mkdir()
    data = creatives if creatives is not None else {
        "groups": [{
            "name": "G1",
            "combined_ad": {
                "visual_concepts": [
                    {"id": "A", "type": "product_offer", "angle": "цена",
                     "usp_on_creative": "Дешевле"},
                ],
                "videos": [],
            },
        }],
    }
    (ws / "08_creatives.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return ws


def test_missing_creatives_returns_1(tmp_path):
    assert run_video_generation(tmp_path / "empty", None, True, False, None, 5, "16:9") == 1


def test_duration_out_of_range(tmp_path):
    ws = _ws(tmp_path)
    assert run_video_generation(ws, None, True, False, None, 4, "16:9") == 1
    assert run_video_generation(ws, None, True, False, None, 61, "16:9") == 1


def test_live_without_model_returns_1(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    assert run_video_generation(ws, None, False, False, None, 5, "16:9") == 1


def test_dry_run_writes_prompts(tmp_path):
    ws = _ws(tmp_path)
    code = run_video_generation(ws, None, True, False, None, 5, "16:9")
    assert code == 0
    prompts = list((ws / "assets" / "video_prompts").glob("*.txt"))
    assert len(prompts) == 1
    assert "16x9" in prompts[0].name
    log = json.loads((ws / "assets" / "video_generation_log.json").read_text(encoding="utf-8"))
    assert log["entries"][0]["status"] == "dry_run"


def test_provider_exception_becomes_failed(tmp_path, monkeypatch, fast_sleep):
    class Boom:
        def generate(self, **kw):
            raise RuntimeError("provider down")

    monkeypatch.setattr(
        "scripts.generate_creative_videos.get_provider",
        lambda *a, **k: Boom(),
    )
    ws = _ws(tmp_path)
    code = run_video_generation(ws, "kwaivgi/kling-v1.6-standard", False, False, None, 5, "16:9")
    assert code == 0
    log = json.loads((ws / "assets" / "video_generation_log.json").read_text(encoding="utf-8"))
    assert log["entries"][0]["status"] == "failed"
    assert "provider down" in log["entries"][0]["error"]


def test_exists_without_force(tmp_path, monkeypatch, fast_sleep):
    class Unused:
        def generate(self, **kw):
            raise AssertionError("не должен вызываться")

    monkeypatch.setattr(
        "scripts.generate_creative_videos.get_provider",
        lambda *a, **k: Unused(),
    )
    ws = _ws(tmp_path)
    out = ws / "assets" / "videos" / "g1_A_16x9.mp4"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"mp4")
    run_video_generation(ws, "kwaivgi/kling-v1.6-standard", False, False, None, 5, "16:9")
    data = json.loads((ws / "08_creatives.json").read_text(encoding="utf-8"))
    assert "assets/videos/g1_A_16x9.mp4" in data["groups"][0]["combined_ad"]["videos"]
    log = json.loads((ws / "assets" / "video_generation_log.json").read_text(encoding="utf-8"))
    assert log["entries"][0]["status"] == "exists"


def test_videos_capped_at_six(tmp_path, monkeypatch, fast_sleep):
    class Fake:
        def generate(self, **kw):
            Path(kw["output_path"]).parent.mkdir(parents=True, exist_ok=True)
            Path(kw["output_path"]).write_bytes(b"mp4")
            return kw["output_path"]

    monkeypatch.setattr(
        "scripts.generate_creative_videos.get_provider",
        lambda *a, **k: Fake(),
    )
    # одна концепция на группу → по одному видео; симулируем уже заполненный список
    existing = [f"assets/videos/old{i}.mp4" for i in range(6)]
    ws = _ws(tmp_path, creatives={
        "groups": [{
            "name": "G",
            "combined_ad": {
                "visual_concepts": [
                    {"id": "A", "type": "product_offer", "angle": "a", "usp_on_creative": "U"},
                ],
                "videos": list(existing),
            },
        }],
    })
    run_video_generation(ws, "kwaivgi/kling-v1.6-standard", False, False, None, 5, "16:9")
    data = json.loads((ws / "08_creatives.json").read_text(encoding="utf-8"))
    assert len(data["groups"][0]["combined_ad"]["videos"]) == 6


def test_aspect_slug_in_filename(tmp_path):
    ws = _ws(tmp_path)
    run_video_generation(ws, None, True, False, None, 5, "9:16")
    names = [p.name for p in (ws / "assets" / "video_prompts").glob("*.txt")]
    assert any("9x16" in n for n in names)
