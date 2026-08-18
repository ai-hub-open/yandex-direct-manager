#!/usr/bin/env python3
"""
manage_credentials.py — CLI для управления API-ключами скилла.

Usage:
    # Установить ключ (запрос интерактивно, не светится в shell history)
    python -m scripts.manage_credentials set openai

    # Установить ключ из аргумента (опасно — попадает в shell history)
    python -m scripts.manage_credentials set openai --key sk-...

    # Получить (только маска, для проверки что сохранено)
    python -m scripts.manage_credentials get openai

    # Удалить
    python -m scripts.manage_credentials delete openai

    # Список сохранённых
    python -m scripts.manage_credentials list

    # Информация о сервисе (без значения ключа)
    python -m scripts.manage_credentials info openai

Где хранится: ~/.yandex-direct-manager/credentials.json (с правами 600 на Unix).
"""

import argparse
import getpass
import sys

try:
    from scripts.credentials import (
        SERVICE_REGISTRY,
        credentials_file,
        delete_api_key,
        get_service_info,
        list_stored_services,
        load_api_key,
        set_api_key,
    )
except ImportError:
    # При запуске напрямую
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.credentials import (
        SERVICE_REGISTRY,
        credentials_file,
        delete_api_key,
        get_service_info,
        list_stored_services,
        load_api_key,
        set_api_key,
    )


def mask(key: str) -> str:
    """Маска ключа для безопасного вывода. sk-1234567890 → sk-1...90 (последние 4)."""
    if not key or len(key) < 8:
        return "***"
    return key[:4] + "..." + key[-4:]


def cmd_set(args):
    service = args.service
    if service not in SERVICE_REGISTRY:
        print(f"ERROR: неизвестный сервис '{service}'.", file=sys.stderr)
        print(f"Зарегистрированные: {', '.join(sorted(SERVICE_REGISTRY.keys()))}", file=sys.stderr)
        return 1

    info = SERVICE_REGISTRY[service]
    print(f"Сервис: {service}")
    print(f"Описание: {info['description']}")
    print(f"Где взять: {info['how_to_get']}")
    print(f"Формат: {info['format_hint']}")
    print()

    if args.key:
        key = args.key
    else:
        # getpass не светится в терминале и не пишется в history
        key = getpass.getpass(f"Введите ключ для '{service}' (ввод скрыт): ").strip()

    if not key:
        print("ERROR: пустой ключ не сохраняем.", file=sys.stderr)
        return 1

    set_api_key(service, key)
    print(f"✓ Сохранено: {mask(key)} → {credentials_file()}")
    return 0


def cmd_get(args):
    service = args.service
    try:
        key = load_api_key(service)
        print(f"{service}: {mask(key)}")
        if args.show:
            print(f"(полностью: {key})")
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_delete(args):
    service = args.service
    if delete_api_key(service):
        print(f"✓ Удалён ключ для '{service}'")
    else:
        print(f"Ключ для '{service}' не был сохранён.")
    return 0


def cmd_list(args):
    stored = list_stored_services()
    print(f"Файл: {credentials_file()}")
    print()
    if not stored:
        print("Нет сохранённых ключей.")
        print()
        print("Зарегистрированные сервисы:")
        for s, info in sorted(SERVICE_REGISTRY.items()):
            print(f"  {s:12} — {info['description']}")
        return 0

    print("Сохранённые ключи:")
    for s in stored:
        try:
            key = load_api_key(s)
            print(f"  {s:12} — {mask(key)}")
        except Exception:
            print(f"  {s:12} — ?")

    not_stored = [s for s in SERVICE_REGISTRY if s not in stored]
    if not_stored:
        print()
        print("Не сохранены (можно добавить через `set`):")
        for s in not_stored:
            print(f"  {s:12} — {SERVICE_REGISTRY[s]['description']}")
    return 0


def cmd_info(args):
    service = args.service
    info = get_service_info(service)
    if not info:
        print(f"ERROR: неизвестный сервис '{service}'.", file=sys.stderr)
        return 1
    print(f"Сервис: {service}")
    for k, v in info.items():
        print(f"  {k}: {v}")

    try:
        load_api_key(service)
        print(f"  status: ✓ ключ сохранён")
    except Exception:
        print(f"  status: ✗ ключа нет")
    return 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="Управление API-ключами для скилла yandex-direct-manager")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_set = sub.add_parser("set", help="Сохранить ключ (интерактивно или через --key)")
    p_set.add_argument("service", choices=sorted(SERVICE_REGISTRY.keys()))
    p_set.add_argument("--key", help="Ключ (если не указан — спросит интерактивно)")
    p_set.set_defaults(func=cmd_set)

    p_get = sub.add_parser("get", help="Показать ключ (по умолчанию маска)")
    p_get.add_argument("service", choices=sorted(SERVICE_REGISTRY.keys()))
    p_get.add_argument("--show", action="store_true", help="Показать полностью (НЕ безопасно)")
    p_get.set_defaults(func=cmd_get)

    p_del = sub.add_parser("delete", help="Удалить сохранённый ключ")
    p_del.add_argument("service", choices=sorted(SERVICE_REGISTRY.keys()))
    p_del.set_defaults(func=cmd_delete)

    p_list = sub.add_parser("list", help="Список сохранённых и доступных сервисов")
    p_list.set_defaults(func=cmd_list)

    p_info = sub.add_parser("info", help="Информация о сервисе")
    p_info.add_argument("service", choices=sorted(SERVICE_REGISTRY.keys()))
    p_info.set_defaults(func=cmd_info)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
