"""validate_assets: техтребования Директа на картинки и видео."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.validate_assets import main, validate_image, validate_video


def _png(path: Path, size: tuple[int, int]):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=(20, 40, 60)).save(path, "PNG")


def test_ok_1080_square(tmp_path):
    p = tmp_path / "ok.png"
    _png(p, (1080, 1080))
    r = validate_image(p)
    assert r["status"] == "ok"
    assert r["issues"] == []


def test_too_small_side(tmp_path):
    p = tmp_path / "tiny.png"
    _png(p, (100, 100))
    r = validate_image(p)
    assert r["status"] == "fail"
    assert any("меньше" in i for i in r["issues"])


def test_too_large_side(tmp_path):
    p = tmp_path / "huge.png"
    _png(p, (6000, 6000))
    r = validate_image(p)
    assert r["status"] == "fail"
    assert any("больше" in i for i in r["issues"])


def test_16x9_below_wide_minimum(tmp_path):
    p = tmp_path / "wide_small.png"
    _png(p, (800, 450))  # 16:9, но меньше 1080×607
    r = validate_image(p)
    assert r["status"] == "fail"
    assert any("16:9" in i and "минимум" in i for i in r["issues"])


def test_1080x800_not_in_ratio_list(tmp_path):
    """Допуск 1% не должен пропускать 1080×800 (отклонение от 4:3 ~1.25%)."""
    p = tmp_path / "odd.png"
    _png(p, (1080, 800))
    r = validate_image(p)
    assert r["status"] == "fail"
    assert any("не из списка" in i for i in r["issues"])


def test_missing_file_is_fail_not_exception(tmp_path):
    r = validate_image(tmp_path / "nope.png")
    assert r["status"] == "fail"
    assert any("не найден" in i for i in r["issues"])


def test_broken_image(tmp_path):
    p = tmp_path / "broken.png"
    p.write_bytes(b"not-an-image")
    r = validate_image(p)
    assert r["status"] == "fail"
    assert any("не открылась" in i for i in r["issues"])


def test_video_bad_extension(tmp_path):
    p = tmp_path / "clip.mkv"
    p.write_bytes(b"x")
    r = validate_video(p)
    assert r["status"] == "fail"
    assert any("расширение" in i for i in r["issues"])


def test_video_oversize_sparse(tmp_path):
    p = tmp_path / "big.mp4"
    # sparse: seek past 100 MB without writing that much data
    with p.open("wb") as f:
        f.seek(101 * 1024 * 1024)
        f.write(b"\0")
    r = validate_video(p)
    assert r["status"] == "fail"
    assert any("МБ" in i for i in r["issues"])


def test_main_writes_report_and_exit_codes(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    (ws / "assets" / "images").mkdir(parents=True)
    (ws / "assets" / "videos").mkdir(parents=True)
    _png(ws / "assets" / "images" / "bad.png", (100, 100))
    (ws / "assets" / "videos" / "last-frame.png").write_bytes(b"png")  # должен пропускаться
    ok_vid = ws / "assets" / "videos" / "ok.mp4"
    ok_vid.write_bytes(b"mp4")

    monkeypatch.setattr("sys.argv", ["validate_assets", "--workspace", str(ws)])
    code = main()
    assert code == 1
    report = json.loads((ws / "assets" / "validation_report.json").read_text(encoding="utf-8"))
    files = [Path(r["file"]).name for r in report]
    assert "bad.png" in files
    assert "ok.mp4" in files
    assert "last-frame.png" not in files

    # чистый набор
    (ws / "assets" / "images" / "bad.png").unlink()
    _png(ws / "assets" / "images" / "good.png", (1080, 1080))
    monkeypatch.setattr("sys.argv", ["validate_assets", "--workspace", str(ws)])
    assert main() == 0
