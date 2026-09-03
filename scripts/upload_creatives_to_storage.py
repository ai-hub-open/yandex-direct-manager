#!/usr/bin/env python3
"""
upload_creatives_to_storage.py — публикация локальных креативов во временном
файловом хранилище KeepImage (aihub) и получение публичных ссылок для заливки
картинок в Яндекс.Директ через `adimages_add(image_url=...)`.

Зачем это нужно
---------------
Хостовый MCP Директа сам не видит локальные файлы маркетолога, но `adimages_add`
теперь принимает `image_url` (публичную ссылку http/https — сервер скачает файл
сам). KeepImage превращает локальный файл в такую ссылку: POST/PUT файла →
публичный `/f/<id>/<имя>` без авторизации, живёт до 2 часов. Ссылка нужна живой
только в момент вызова `adimages_add`: Директ скачивает картинку и сохраняет её
у себя, дальше ссылка не нужна.

Почему скрипт, а не MCP `storage_publish_image(data_base64)`
-----------------------------------------------------------
РСЯ-креатив бывает до 10 МБ. Через MCP `data_base64` весь файл пришлось бы гнать
строкой в контексте модели — дорого и ненадёжно (base64 рвётся). Скрипт постит
байты напрямую по HTTP. MCP-путь остаётся фолбеком для сред без запуска кода
и для мелких картинок (см. SKILL.md → Шаг 10Б).

Авторизация
-----------
Тот же токен click.ru, что и у Директа (сервис `clickru` в реестре ключей или
env `CLICK_RU_TOKEN`). Мастер-аккаунту click.ru нужен ещё `X-Auth-UserId`
(сервис `clickru_user_id` / env `CLICK_RU_USER_ID`) — иначе объекты подпользователей
считаются по неверному ключу владельца. Токен НИКОГДА не пишется в артефакты
рабочей папки.

Что делает
----------
1. Собирает список локальных картинок:
   - по умолчанию — пути `combined_ad.images` из `08_creatives.json` (все группы);
   - `--all-assets` — всё из `assets/images/*.{png,jpg,jpeg,gif}`;
   - `--files a.png b.jpg` — явный список.
   Пути из `08_creatives.json` считаются относительно `--workspace`.
2. Каждый файл заливает в KeepImage (PUT /v1/objects/<имя>, сырое тело) и
   получает публичную ссылку.
3. Пишет манифест `assets/storage_manifest.json`: соответствие локальный путь →
   ссылка (+ id, срок, размер). Оркестратор читает его на Шаге 10Б и передаёт
   `url` в `adimages_add`.

Публичные ссылки в манифесте временные (TTL ≤ 2 ч) — это не артефакт для git,
а рабочий проброс на время заливки.

Usage
-----
    # проверить доступность и токен
    python -m scripts.upload_creatives_to_storage --check

    # предпросмотр: что и куда зальётся, без сети
    python -m scripts.upload_creatives_to_storage --workspace <dir> --dry-run

    # реальная заливка картинок из 08_creatives.json
    python -m scripts.upload_creatives_to_storage --workspace <dir>

    # залить всё из assets/images
    python -m scripts.upload_creatives_to_storage --workspace <dir> --all-assets
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from pathlib import Path
from urllib.parse import quote

import requests

try:
    from scripts.credentials import CredentialNotFound, load_api_key
except ImportError:  # запуск напрямую, не как модуль пакета
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.credentials import CredentialNotFound, load_api_key

DEFAULT_BASE_URL = "https://storage.aihub.click.ru"
DEFAULT_TTL = 7200  # максимум хранилища
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
REQUEST_TIMEOUT = 120


def base_url() -> str:
    """Боевой домен KeepImage; можно переопределить env KEEPIMAGE_BASE_URL."""
    import os

    return os.environ.get("KEEPIMAGE_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _token() -> str:
    """Токен click.ru: env CLICK_RU_TOKEN → реестр ключей (сервис clickru)."""
    return load_api_key("clickru")


def _user_id() -> str | None:
    """ID пользователя click.ru для мастер-аккаунта (опционально)."""
    try:
        return load_api_key("clickru_user_id")
    except CredentialNotFound:
        return None


def _headers(token: str, content_type: str | None, ttl: int) -> dict:
    h = {"X-Auth-Token": token, "X-Ttl-Seconds": str(ttl)}
    if content_type:
        h["Content-Type"] = content_type
    uid = _user_id()
    if uid:
        h["X-Auth-UserId"] = uid
    return h


def collect_images(ws: Path, all_assets: bool, explicit: list[str] | None) -> list[Path]:
    """Возвращает список локальных картинок к заливке (уникальные, существующие)."""
    if explicit:
        paths = [Path(f) if Path(f).is_absolute() else ws / f for f in explicit]
    elif all_assets:
        img_dir = ws / "assets" / "images"
        paths = sorted(p for p in img_dir.glob("*.*") if p.suffix.lower() in ALLOWED_SUFFIXES) if img_dir.exists() else []
    else:
        paths = _images_from_creatives(ws)

    seen: dict[str, Path] = {}
    for p in paths:
        key = str(p.resolve())
        if key not in seen:
            seen[key] = p
    return list(seen.values())


def _images_from_creatives(ws: Path) -> list[Path]:
    """Собирает пути картинок из combined_ad.images всех групп 08_creatives.json."""
    creatives = ws / "08_creatives.json"
    if not creatives.exists():
        return []
    data = json.loads(creatives.read_text(encoding="utf-8"))
    out: list[Path] = []
    for group in data.get("groups", []):
        for rel in (group.get("combined_ad") or {}).get("images", []) or []:
            p = Path(rel)
            out.append(p if p.is_absolute() else ws / rel)
    return out


def upload_one(path: Path, token: str, ttl: int) -> dict:
    """Заливает один файл в KeepImage. Возвращает запись манифеста."""
    path = Path(path)
    rec: dict = {"local": str(path)}
    if not path.exists():
        return {**rec, "status": "fail", "error": "файл не найден"}
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        return {**rec, "status": "fail", "error": f"формат {path.suffix} не поддерживается (PNG/JPEG/GIF/WebP)"}

    content_type = mimetypes.guess_type(path.name)[0]
    url = f"{base_url()}/v1/objects/{quote(path.name)}"
    try:
        with path.open("rb") as f:
            resp = requests.put(url, data=f, headers=_headers(token, content_type, ttl), timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        return {**rec, "status": "fail", "error": f"сеть: {e}"}

    if resp.status_code >= 400:
        detail = resp.text[:300] if resp.text else ""
        return {**rec, "status": "fail", "error": f"HTTP {resp.status_code}: {detail}"}

    try:
        body = resp.json()
    except ValueError:
        return {**rec, "status": "fail", "error": "ответ не JSON"}

    if not body.get("url"):
        return {**rec, "status": "fail", "error": f"нет url в ответе: {body}"}

    return {
        **rec,
        "status": "ok",
        "url": body["url"],
        "id": body.get("id"),
        "content_type": body.get("content_type"),
        "size": body.get("size"),
        "expires_at": body.get("expires_at"),
    }


def run_check() -> int:
    """Проверяет наличие токена и доступность хранилища."""
    try:
        _token()
    except CredentialNotFound as e:
        print(f"✗ токен click.ru не найден.\n{e}", file=sys.stderr)
        return 1
    try:
        resp = requests.get(f"{base_url()}/healthz", timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        print(f"✗ хранилище недоступно: {e}", file=sys.stderr)
        return 1
    ok = resp.status_code < 400
    print(f"{'✓' if ok else '✗'} KeepImage {base_url()} → HTTP {resp.status_code}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="Заливка локальных креативов в KeepImage → публичные ссылки для adimages_add")
    parser.add_argument("--workspace", help="Рабочая папка кампании direct-campaigns/<slug>/")
    parser.add_argument("--all-assets", action="store_true", help="Залить всё из assets/images вместо путей из 08_creatives.json")
    parser.add_argument("--files", nargs="+", help="Явный список файлов (перекрывает --workspace/--all-assets как источник)")
    parser.add_argument("--ttl", type=int, default=DEFAULT_TTL, help=f"Срок жизни ссылок, сек (по умолч. {DEFAULT_TTL}, максимум хранилища)")
    parser.add_argument("--dry-run", action="store_true", help="Только показать план, без сети и без записи манифеста")
    parser.add_argument("--check", action="store_true", help="Проверить токен и доступность хранилища")
    args = parser.parse_args(argv)

    if args.check:
        return run_check()

    if not args.workspace and not args.files:
        print("ERROR: нужен --workspace или --files.", file=sys.stderr)
        return 2

    ws = Path(args.workspace) if args.workspace else Path.cwd()
    images = collect_images(ws, args.all_assets, args.files)

    if not images:
        print("Картинок для заливки не найдено (проверь 08_creatives.json → combined_ad.images или --all-assets).")
        return 0

    if args.dry_run:
        print(f"[dry-run] залил бы {len(images)} файл(ов) в {base_url()} (TTL {args.ttl} c):")
        for p in images:
            mark = "" if p.exists() else "  ⚠️ НЕ НАЙДЕН"
            print(f"  {p}{mark}")
        return 0

    try:
        token = _token()
    except CredentialNotFound as e:
        print(f"ERROR: токен click.ru не найден.\n{e}", file=sys.stderr)
        print("Сохрани: python -m scripts.manage_credentials set clickru", file=sys.stderr)
        return 1

    manifest = [upload_one(p, token, args.ttl) for p in images]

    out = ws / "assets" / "storage_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    fails = [r for r in manifest if r["status"] != "ok"]
    oks = [r for r in manifest if r["status"] == "ok"]
    print(f"Залито: {len(oks)}/{len(manifest)}. Манифест: {out}")
    for r in oks:
        print(f"  ✓ {Path(r['local']).name} → {r['url']}")
    for r in fails:
        print(f"  ✗ {Path(r['local']).name}: {r['error']}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
