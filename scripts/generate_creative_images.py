#!/usr/bin/env python3
"""
generate_creative_images.py — генерация РСЯ-картинок для комбинаторных объявлений
через OpenAI Images API (gpt-image-1 / dall-e-3).

Читает 08_creatives.json (+ brand.json) из рабочей папки кампании,
для каждой группы генерит до 5 картинок (концепции × форматы 4:3/16:9/1:1),
постпроцессит размер через PIL, сохраняет в assets/images/ и дописывает
относительные пути в combined_ad["images"].

Usage:
    python -m scripts.generate_creative_images --workspace <dir> --dry-run
    python -m scripts.generate_creative_images --workspace <dir> --concept A
    python -m scripts.generate_creative_images --workspace <dir> --force

Ключ OpenAI: env OPENAI_API_KEY или `python -m scripts.manage_credentials set openai`.
"""

import argparse
import base64
import json
import sys
import time
from pathlib import Path

try:
    from scripts.prompt_templates import (
        IMAGE_SPECS, build_format_plan, build_prompt, detect_creative_type,
    )
    from scripts.credentials import load_api_key, CredentialNotFound
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.prompt_templates import (
        IMAGE_SPECS, build_format_plan, build_prompt, detect_creative_type,
    )
    from scripts.credentials import load_api_key, CredentialNotFound


def load_brand_config(workspace: Path) -> dict:
    local = workspace / "brand.json"
    if local.exists():
        with local.open(encoding="utf-8") as f:
            return json.load(f)
    defaults_path = Path(__file__).parent / "brand_defaults.json"
    if defaults_path.exists():
        with defaults_path.open(encoding="utf-8") as f:
            return {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    return {"product_name": "Product", "primary_color": "#2D5BFF", "accent_color": "#22C55E"}


def load_creatives(workspace: Path) -> dict:
    path = workspace / "08_creatives.json"
    if not path.exists():
        raise FileNotFoundError(f"Не найден {path} — сначала Шаг 8 (объявления).")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_prompt(prompt: str, path: Path, concept: dict, ctype: str, fmt: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"# Промпт концепции {concept.get('id')} ({ctype}), формат {fmt}\n"
        f"# УТП: {concept.get('usp_on_creative', '—')}\n\n---\n\n{prompt}\n"
    )
    path.write_text(body, encoding="utf-8")


def generate_via_openai(prompt: str, size: str, model: str, output_path: Path, api_key: str = None) -> bool:
    """
    Вызывает OpenAI Images API. Возвращает True при успехе.
    """
    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai SDK не установлен. pip install openai>=1.40", file=sys.stderr)
        return False

    # Если ключ передан явно — используем его, иначе OpenAI SDK сам прочитает env
    if api_key:
        client = OpenAI(api_key=api_key)
    else:
        client = OpenAI()

    try:
        if model == "gpt-image-1":
            response = client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                size=size,
                quality="high",
                n=1,
            )
            # gpt-image-1 возвращает base64 по умолчанию
            b64 = response.data[0].b64_json
            if b64:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(base64.b64decode(b64))
                return True
            # Иначе пробуем URL
            url = getattr(response.data[0], "url", None)
            if url:
                return _download(url, output_path)
        else:  # dall-e-3
            response = client.images.generate(
                model=model,
                prompt=prompt,
                size=size,
                quality="hd",
                n=1,
            )
            url = response.data[0].url
            return _download(url, output_path)
    except Exception as e:
        print(f"  ERROR OpenAI: {e}", file=sys.stderr)
        return False


def _download(url: str, output_path: Path) -> bool:
    """Скачивает картинку по URL и сохраняет."""
    try:
        import requests
    except ImportError:
        import urllib.request

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(url, output_path)
            return True
        except Exception as e:
            print(f"  ERROR urllib download: {e}", file=sys.stderr)
            return False
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(r.content)
        return True
    except Exception as e:
        print(f"  ERROR requests download: {e}", file=sys.stderr)
        return False


def postprocess(image_path: Path, target_size: tuple):
    """
    Ресайз/crop картинки до целевого размера VK через PIL.
    Если PIL не установлен — пропускает (картинка остаётся в исходном размере).
    """
    try:
        from PIL import Image
    except ImportError:
        print(f"  WARN: PIL не установлен — картинка останется в исходном размере", file=sys.stderr)
        return

    img = Image.open(image_path)
    target_w, target_h = target_size

    # Ресайз с сохранением пропорций, потом центральный crop до target
    src_w, src_h = img.size
    src_ratio = src_w / src_h
    target_ratio = target_w / target_h

    if abs(src_ratio - target_ratio) < 0.01:
        # Пропорции совпадают — простой ресайз
        img = img.resize(target_size, Image.LANCZOS)
    elif src_ratio > target_ratio:
        # Источник шире — ресайзим по высоте, crop по ширине
        new_h = target_h
        new_w = int(new_h * src_ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - target_w) // 2
        img = img.crop((left, 0, left + target_w, target_h))
    else:
        # Источник выше — ресайзим по ширине, crop по высоте
        new_w = target_w
        new_h = int(new_w / src_ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        top = (new_h - target_h) // 2
        img = img.crop((0, top, target_w, top + target_h))

    img.save(image_path, "PNG", optimize=True)


def run_generation(workspace: Path, model: str, dry_run: bool, force: bool,
                   only_group, only_concept) -> int:
    workspace = Path(workspace)
    brand = load_brand_config(workspace)
    data = load_creatives(workspace)

    openai_key = None
    if not dry_run:
        try:
            openai_key = load_api_key("openai")
            print("✓ Ключ OpenAI загружен")
        except CredentialNotFound as e:
            print(str(e), file=sys.stderr)
            return 1

    images_dir = workspace / "assets" / "images"
    prompts_dir = workspace / "assets" / "prompts"
    log_path = workspace / "assets" / "generation_log.json"
    log = []
    changed = False

    for gi, group in enumerate(data.get("groups", []), 1):
        if only_group and gi != int(only_group):
            continue
        ca = group.get("combined_ad") or {}
        concepts = ca.get("visual_concepts") or []
        if not concepts:
            print(f"[группа {gi}] WARN: нет visual_concepts — пропускаю. "
                  f"Добавь концепции на Шаге 8.5.", file=sys.stderr)
            log.append({"group": gi, "status": "no_visual_concepts"})
            continue

        generated_paths = list(ca.get("images") or [])
        for concept, fmt in build_format_plan(concepts):
            cid = concept.get("id", "X")
            if only_concept and cid != only_concept:
                continue
            ctype = detect_creative_type(concept)
            name = f"g{gi}_{cid}_{fmt}"
            spec = IMAGE_SPECS[fmt]
            image_path = images_dir / f"{name}.png"
            rel_path = f"assets/images/{name}.png"

            prompt = build_prompt(concept, brand, group, fmt)
            save_prompt(prompt, prompts_dir / f"{name}.txt", concept, ctype, fmt)
            print(f"[{name}] type={ctype}")

            if dry_run:
                log.append({"name": name, "type": ctype, "status": "dry_run"})
                continue
            if ctype == "ui_mockup":
                print("  ⚠ UI mockup — запросите реальный скриншот у клиента")
                log.append({"name": name, "type": ctype, "status": "needs_real_screenshot"})
                continue
            if image_path.exists() and not force:
                print("  уже есть, skip")
                log.append({"name": name, "type": ctype, "status": "exists"})
                if rel_path not in generated_paths:
                    generated_paths.append(rel_path)
                    changed = True
                continue

            print("  генерим...")
            ok = generate_via_openai(prompt, spec["openai_size"], model, image_path, api_key=openai_key)
            if ok:
                postprocess(image_path, spec["target_size"])
                w, h = spec["target_size"]
                print(f"    ✓ {image_path.name} ({w}×{h})")
                log.append({"name": name, "type": ctype, "status": "generated", "path": rel_path})
                if rel_path not in generated_paths:
                    generated_paths.append(rel_path)
                    changed = True
            else:
                log.append({"name": name, "type": ctype, "status": "failed"})
            time.sleep(1.5)

        if generated_paths:
            ca["images"] = generated_paths[:5]

    if changed:
        (workspace / "08_creatives.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("✓ 08_creatives.json обновлён (combined_ad.images)")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== Сводка ===")
    statuses = {}
    for e in log:
        statuses[e["status"]] = statuses.get(e["status"], 0) + 1
    for s, n in sorted(statuses.items()):
        print(f"  {s}: {n}")
    print(f"Лог: {log_path}")
    return 0


def main():
    # Кириллица и эмодзи в stdout/stderr на Windows-консолях (cp1251) иначе ломаются.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="Генератор РСЯ-картинок для Яндекс.Директа")
    parser.add_argument("--workspace", required=True, help="Папка direct-campaigns/<slug>/")
    parser.add_argument("--model", default="gpt-image-1", choices=["gpt-image-1", "dall-e-3"])
    parser.add_argument("--group", default=None, help="Только группа с этим номером (1-based)")
    parser.add_argument("--concept", default=None, help="Только концепция с этим id (например A)")
    parser.add_argument("--dry-run", action="store_true", help="Только промпты, без вызова API")
    parser.add_argument("--force", action="store_true", help="Перегенерировать существующие")
    args = parser.parse_args()

    workspace = Path(args.workspace)
    if not workspace.exists():
        print(f"ERROR: {workspace} не существует", file=sys.stderr)
        return 1
    return run_generation(workspace, args.model, args.dry_run, args.force, args.group, args.concept)


if __name__ == "__main__":
    sys.exit(main())
