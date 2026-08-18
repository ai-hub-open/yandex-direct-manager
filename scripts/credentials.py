"""
credentials.py — универсальная система хранения и чтения API-ключей для скилла.

Используется скриптами скилла (generate_creative_images, generate_creative_videos,
forecast_cpc и т.д.) для получения ключей без жёсткой привязки к env-переменным.

Стратегия поиска ключа:
1. Если задана env-переменная (например OPENAI_API_KEY) — берём её.
2. Иначе читаем из ~/.yandex-direct-manager/credentials.json
3. Если и там нет — raises CredentialNotFound с инструкцией.

Файл credentials.json создаётся при первом вызове `set_api_key()` или через
CLI `python -m scripts.manage_credentials set <service>`.

Поддерживаемые сервисы (`SERVICE_REGISTRY`):
- openai         — OpenAI API (DALL-E, GPT-image, ChatGPT)
- replicate      — Replicate hub видео-моделей (Kling, Seedance, Hailuo и др.)
- yandex_direct  — OAuth-токен Яндекс.Директа для прямой заливки через API
- clickru        — Click.ru токен прокси-доступа к API Яндекс.Директа
- clickru_login  — Click.ru логин аккаунта Яндекс.Директа (заголовок Client-Login)
- clickru_user_id — Click.ru ID пользователя для мастер-токена

Безопасность:
- Файл credentials.json сохраняется с правами 600 (только владелец) на POSIX
  (`os.chmod` вызывается только при `os.name == "posix"`).
- На Windows права файла не сужаются отдельно — защита только правами
  домашней папки пользователя.
- Файл лежит вне рабочей папки проекта — не попадёт в git/share.
"""

import json
import os
import stat
import sys
from pathlib import Path


class CredentialNotFound(Exception):
    """Ключ для сервиса не найден ни в env, ни в credentials.json."""

    def __init__(self, service: str):
        self.service = service
        msg = (
            f"\nКлюч для сервиса '{service}' не найден.\n\n"
            f"Чтобы добавить:\n"
            f"  python -m scripts.manage_credentials set {service}\n\n"
            f"Или установи env-переменную {SERVICE_REGISTRY.get(service, {}).get('env', service.upper() + '_API_KEY')}.\n"
        )
        super().__init__(msg)


# Реестр поддерживаемых сервисов: какие env-переменные и инструкции по получению.
SERVICE_REGISTRY = {
    "openai": {
        "env": "OPENAI_API_KEY",
        "description": "OpenAI API key для генерации картинок (gpt-image-1 / dall-e-3)",
        "how_to_get": "https://platform.openai.com/api-keys (нужен аккаунт + платёжный метод)",
        "format_hint": "sk-...",
    },
    "replicate": {
        "env": "REPLICATE_API_TOKEN",
        "description": "Replicate — hub видео-моделей (Kling, Seedance, Hailuo и др.)",
        "how_to_get": "https://replicate.com/account/api-tokens",
        "format_hint": "r8_...",
    },
    "yandex_direct": {
        "env": "YANDEX_DIRECT_TOKEN",
        "description": "OAuth-токен Яндекс.Директа для прямой заливки через API v501",
        "how_to_get": "https://yandex.ru/dev/direct/doc/ru/concepts/auth-token",
        "format_hint": "y0_...",
    },
    "clickru": {
        "env": "CLICK_RU_TOKEN",
        "description": "Click.ru — токен прокси-доступа к API Яндекс.Директа (режим без прямого токена Яндекса)",
        "how_to_get": "https://help.click.ru/6634 (личный кабинет Click.ru → API)",
        "format_hint": "JWT-токен",
    },
    "clickru_login": {
        "env": "CLICK_RU_CLIENT_LOGIN",
        "description": "Click.ru — логин аккаунта Яндекс.Директа (заголовок Client-Login)",
        "how_to_get": "Логин из интерфейса Яндекс.Директа, подключённый к Click.ru",
        "format_hint": "login-na-yandex",
    },
    "clickru_user_id": {
        "env": "CLICK_RU_USER_ID",
        "description": "Click.ru — ID пользователя (X-Auth-UserId, для мастер-токена; опционально)",
        "how_to_get": "Личный кабинет Click.ru",
        "format_hint": "число",
    },
}


def credentials_dir() -> Path:
    """Возвращает путь к директории credentials (создаёт если нет)."""
    base = Path.home() / ".yandex-direct-manager"
    base.mkdir(parents=True, exist_ok=True)
    return base


def credentials_file() -> Path:
    return credentials_dir() / "credentials.json"


def _read_all() -> dict:
    """Читает весь credentials.json. Возвращает {} если файла нет."""
    fp = credentials_file()
    if not fp.exists():
        return {}
    try:
        with fp.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"WARN: не смог прочитать credentials.json: {e}", file=sys.stderr)
        return {}


def _write_all(data: dict):
    """Записывает credentials.json с безопасными правами."""
    fp = credentials_file()
    with fp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # На Unix-системах ставим 600 (только владелец читает и пишет)
    if hasattr(os, "chmod") and os.name == "posix":
        try:
            os.chmod(fp, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass


def load_api_key(service: str) -> str:
    """
    Возвращает ключ для сервиса. Сначала env, потом credentials.json.

    Raises:
        CredentialNotFound: если ключа нет ни в env, ни в credentials.json.
    """
    if service not in SERVICE_REGISTRY:
        raise ValueError(f"Неизвестный сервис '{service}'. Зарегистрированные: {list(SERVICE_REGISTRY.keys())}")

    # 1. Env-переменная
    env_name = SERVICE_REGISTRY[service]["env"]
    val = os.environ.get(env_name)
    if val:
        return val

    # 2. credentials.json
    creds = _read_all()
    if service in creds and creds[service]:
        return creds[service]

    # 3. Не нашли
    raise CredentialNotFound(service)


def set_api_key(service: str, key: str):
    """Сохраняет ключ для сервиса в credentials.json."""
    if service not in SERVICE_REGISTRY:
        raise ValueError(f"Неизвестный сервис '{service}'. Зарегистрированные: {list(SERVICE_REGISTRY.keys())}")

    creds = _read_all()
    creds[service] = key
    _write_all(creds)


def delete_api_key(service: str) -> bool:
    """Удаляет ключ из credentials.json. Возвращает True если был."""
    creds = _read_all()
    if service in creds:
        del creds[service]
        _write_all(creds)
        return True
    return False


def list_stored_services() -> list:
    """Возвращает список сервисов с сохранёнными ключами (без самих значений)."""
    return sorted(_read_all().keys())


def get_service_info(service: str) -> dict:
    """Возвращает метаинформацию о сервисе."""
    return SERVICE_REGISTRY.get(service, {})
