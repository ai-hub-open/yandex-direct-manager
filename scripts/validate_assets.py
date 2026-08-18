#!/usr/bin/env python3
"""
validate_assets.py — проверка картинок и видео под техтребования Яндекс.Директа
(ЕПК/РСЯ) ДО заливки. Источник: yandex.ru/support/direct/ru/moderation/technical-restrictions.

Картинки: стороны 450–5000 px; 16:9 — от 1080x607; соотношения 1:1/4:3/3:4/16:9;
JPG/PNG/GIF; ≤10 МБ.
Видео: MP4/WebM/MOV/QT/FLV/AVI; ≤100 МБ (длительность 5–60 c проверяется на стороне API).

Usage:
    python -m scripts.validate_assets --workspace <dir>
"""

import argparse
import json
import sys
from pathlib import Path

IMAGE_MAX_MB = 10
VIDEO_MAX_MB = 100
SIDE_MIN, SIDE_MAX = 450, 5000
WIDE_MIN_W, WIDE_MIN_H = 1080, 607
RATIOS = {"1x1": 1.0, "4x3": 4 / 3, "3x4": 3 / 4, "16x9": 16 / 9}
# Допуск 1% для совпадения с целевым соотношением; не 0.02, т.к. допуск 2% пропускал бы 1080×800 (отклонение от 4:3 всего 1.25%)
RATIO_TOLERANCE = 0.01
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".qt", ".flv", ".avi"}


def validate_image(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"file": str(path), "status": "fail", "issues": ["файл не найден"]}
    issues = []
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > IMAGE_MAX_MB:
        issues.append(f"вес {size_mb:.1f} МБ > {IMAGE_MAX_MB} МБ")
    try:
        from PIL import Image
        with Image.open(path) as img:
            if img.format not in ("PNG", "JPEG", "GIF"):
                issues.append(f"формат {img.format} — нужен PNG/JPEG/GIF")
            w, h = img.size
    except Exception as e:
        return {"file": str(path), "status": "fail", "issues": [f"не открылась: {e}"]}

    if min(w, h) < SIDE_MIN:
        issues.append(f"{w}x{h}: сторона меньше {SIDE_MIN} px")
    if max(w, h) > SIDE_MAX:
        issues.append(f"{w}x{h}: сторона больше {SIDE_MAX} px")

    ratio = w / h
    matched = None
    for name, r in RATIOS.items():
        if abs(ratio - r) / r <= RATIO_TOLERANCE:
            matched = name
            break
    if matched is None:
        issues.append(f"соотношение {w}x{h} не из списка 1:1 / 4:3 / 3:4 / 16:9")
    elif matched == "16x9" and (w < WIDE_MIN_W or h < WIDE_MIN_H):
        issues.append(f"16:9 {w}x{h} меньше минимума {WIDE_MIN_W}x{WIDE_MIN_H}")

    return {"file": str(path), "status": "ok" if not issues else "fail", "issues": issues}


def validate_video(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"file": str(path), "status": "fail", "issues": ["файл не найден"]}
    issues = []
    if path.suffix.lower() not in VIDEO_EXTS:
        issues.append(f"расширение {path.suffix} — нужно {'/'.join(sorted(VIDEO_EXTS))}")
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > VIDEO_MAX_MB:
        issues.append(f"вес {size_mb:.1f} МБ > {VIDEO_MAX_MB} МБ")
    return {"file": str(path), "status": "ok" if not issues else "fail", "issues": issues}


def main():
    # Кириллица и эмодзи в stdout/stderr на Windows-консолях (cp1251) иначе ломаются.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="Валидация ассетов под требования Директа")
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    ws = Path(args.workspace)

    report = []
    for p in sorted((ws / "assets" / "images").glob("*.*")) if (ws / "assets" / "images").exists() else []:
        report.append(validate_image(p))
    for p in sorted((ws / "assets" / "videos").glob("*.*")) if (ws / "assets" / "videos").exists() else []:
        if p.suffix.lower() != ".png":  # пропускаем служебные last-frame картинки
            report.append(validate_video(p))

    out = ws / "assets" / "validation_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    fails = [r for r in report if r["status"] == "fail"]
    print(f"Проверено: {len(report)}, ошибок: {len(fails)}")
    for r in fails:
        print(f"  ✗ {r['file']}: {'; '.join(r['issues'])}")
    print(f"Отчёт: {out}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
