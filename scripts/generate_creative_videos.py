#!/usr/bin/env python3
"""
generate_creative_videos.py — генерация видео для комбинаторных объявлений
через Replicate (модель задаётся через --model, каталог: references/replicate-models.md).

Один ролик = один сегмент 5–10 секунд, 16:9 (лимиты Директа: 5–60 c, ≤100 МБ).
Длинные ролики со склейкой сегментов — вне скоупа этой версии.

Usage:
    python -m scripts.generate_creative_videos --workspace <dir> --dry-run
    python -m scripts.generate_creative_videos --workspace <dir> --model kwaivgi/kling-v1.6-standard --concept A

Ключ Replicate: env REPLICATE_API_TOKEN или `python -m scripts.manage_credentials set replicate`.
"""

import argparse
import json
import sys
import time
from pathlib import Path

try:
    from scripts.credentials import CredentialNotFound
    from scripts.video_providers import get_provider
    from scripts.video_prompt_templates import build_video_prompt, detect_video_type
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.credentials import CredentialNotFound
    from scripts.video_providers import get_provider
    from scripts.video_prompt_templates import build_video_prompt, detect_video_type


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


def run_video_generation(workspace: Path, model, dry_run: bool, force: bool,
                         only_concept, duration: int, aspect: str) -> int:
    workspace = Path(workspace)
    path = workspace / "08_creatives.json"
    if not path.exists():
        print(f"ERROR: не найден {path}", file=sys.stderr)
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    brand = load_brand_config(workspace)

    if not 5 <= duration <= 60:
        print("ERROR: длительность должна быть 5–60 секунд (лимит Директа)", file=sys.stderr)
        return 1

    provider = None
    if not dry_run:
        if not model:
            print("ERROR: нужен --model <owner/name>. Каталог: references/replicate-models.md",
                  file=sys.stderr)
            return 1
        try:
            provider = get_provider("replicate", model_id=model)
            print(f"✓ Replicate загружен (model={model})")
        except CredentialNotFound as e:
            print(str(e), file=sys.stderr)
            return 1

    videos_dir = workspace / "assets" / "videos"
    prompts_dir = workspace / "assets" / "video_prompts"
    log_path = workspace / "assets" / "video_generation_log.json"
    entries = []
    changed = False
    aspect_slug = aspect.replace(":", "x")

    for gi, group in enumerate(data.get("groups", []), 1):
        ca = group.get("combined_ad") or {}
        concepts = ca.get("visual_concepts") or []
        if not concepts:
            entries.append({"group": gi, "status": "no_visual_concepts"})
            continue
        videos = list(ca.get("videos") or [])
        # Дефолт: одно видео на группу — по первой концепции (или выбранной через --concept)
        selected = [c for c in concepts if not only_concept or c.get("id") == only_concept][:1]
        for concept in selected:
            cid = concept.get("id", "X")
            name = f"g{gi}_{cid}_{aspect_slug}"
            vtype = detect_video_type(concept)
            prompt = build_video_prompt(concept, brand, duration=duration, aspect=aspect)
            prompts_dir.mkdir(parents=True, exist_ok=True)
            (prompts_dir / f"{name}.txt").write_text(
                f"# Видео-промпт {name} (тип {vtype}, {duration}s, {aspect})\n\n---\n\n{prompt}\n",
                encoding="utf-8")
            print(f"[{name}] type={vtype}")

            if dry_run:
                entries.append({"name": name, "type": vtype, "status": "dry_run"})
                continue

            out = videos_dir / f"{name}.mp4"
            rel = f"assets/videos/{name}.mp4"
            if out.exists() and not force:
                print("  уже есть, skip")
                entries.append({"name": name, "status": "exists"})
                if rel not in videos:
                    videos.append(rel)
                    changed = True
                continue

            print(f"  генерим ({duration}s {aspect})...")
            try:
                provider.generate(prompt=prompt, duration_sec=duration,
                                  aspect_ratio=aspect, output_path=out)
                print(f"    ✓ {out.name}")
                entries.append({"name": name, "type": vtype, "status": "generated", "path": rel})
                if rel not in videos:
                    videos.append(rel)
                    changed = True
            except Exception as e:
                print(f"    ✗ ERROR: {e}", file=sys.stderr)
                entries.append({"name": name, "status": "failed", "error": str(e)})
            time.sleep(2)

        if videos:
            ca["videos"] = videos[:6]

    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("✓ 08_creatives.json обновлён (combined_ad.videos)")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"\nЛог: {log_path}")
    return 0


def main():
    # Кириллица и эмодзи в stdout/stderr на Windows-консолях (cp1251) иначе ломаются.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="Генератор видео для Директа (Replicate)")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--model", default=None, help="Slug модели Replicate (owner/name)")
    parser.add_argument("--concept", default=None, help="id концепции (например A)")
    parser.add_argument("--duration", type=int, default=5, help="Длительность, 5–60 c")
    parser.add_argument("--aspect", default="16:9", choices=["16:9", "1:1", "9:16"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    ws = Path(args.workspace)
    if not ws.exists():
        print(f"ERROR: {ws} не существует", file=sys.stderr)
        return 1
    return run_video_generation(ws, args.model, args.dry_run, args.force,
                                args.concept, args.duration, args.aspect)


if __name__ == "__main__":
    sys.exit(main())
