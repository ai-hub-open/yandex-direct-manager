"""
setup_yandex_direct_mcp.py — подключает хостовые MCP aihub.click.ru к MCP-клиентам.

Серверы уже подняты на стороне aihub — клонировать репозитории и ставить Bun
НЕ нужно. Скрипт только дописывает блоки `mcpServers` в конфиги клиентов
(с бэкапом; существующие серверы сохраняются).

Подключаемые серверы (--server, по умолчанию both):
- yandex-direct    → https://direct-mcp.aihub.click.ru/mcp    (50 инструментов Direct API)
- yandex-wordstat  → https://wordstat-mcp.aihub.click.ru/mcp  (частотность и семантика Wordstat)

Авторизация у обоих — API-токен click.ru
(https://click.ru/userinfo.html → «API Token» → «Создать»).

Цели (--target, можно несколько):
- cursor          ~/.cursor/mcp.json (глобально для Cursor)
- cursor-project  .cursor/mcp.json в текущей папке
- claude-code     .mcp.json в текущей папке
- claude-desktop  claude_desktop_config.json (через stdio-мост mcp-remote, нужен Node.js)
- all             cursor + claude-code + claude-desktop

Использование:
    python -m scripts.setup_yandex_direct_mcp \
        --token <CLICK_RU_TOKEN> --client-login <ЛОГИН_ДИРЕКТА> \
        [--click-ru-user-id <ID>] \
        [--target all] [--server both] [--dry-run] [--remove]

Токен/логин можно не передавать, если они сохранены:
    python -m scripts.manage_credentials set clickru
    python -m scripts.manage_credentials set clickru_login

Скрипт ничего не запускает и не отправляет наружу; токен в логах маскируется.
После записи — перезапусти клиента и проверь связь (см. вывод «Дальше»).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from pathlib import Path

try:
    from scripts.credentials import load_api_key, CredentialNotFound
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    try:
        from scripts.credentials import load_api_key, CredentialNotFound
    except ImportError:
        load_api_key = None

        class CredentialNotFound(Exception):
            pass


DIRECT_URL = "https://direct-mcp.aihub.click.ru/mcp"
WORDSTAT_URL = "https://wordstat-mcp.aihub.click.ru/mcp"

DIRECT_SERVER = "yandex-direct"
WORDSTAT_SERVER = "yandex-wordstat"


# ---------- пути конфигов ----------

def cursor_user_config() -> Path:
    return Path.home() / ".cursor" / "mcp.json"


def cursor_project_config() -> Path:
    return Path.cwd() / ".cursor" / "mcp.json"


def claude_code_config() -> Path:
    return Path.cwd() / ".mcp.json"


def claude_desktop_config() -> Path | None:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "Claude" / "claude_desktop_config.json" if appdata else None
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "Claude" / "claude_desktop_config.json"


TARGETS = {
    "cursor": cursor_user_config,
    "cursor-project": cursor_project_config,
    "claude-code": claude_code_config,
    "claude-desktop": claude_desktop_config,
}


# ---------- заголовки и блоки ----------

def direct_headers(token: str, client_login: str | None, user_id: str | None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if client_login:
        headers["X-Client-Login"] = client_login
    if user_id:
        headers["X-Click-Ru-User-Id"] = user_id
    return headers


def wordstat_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def http_entry(url: str, headers: dict, *, with_type: bool) -> dict:
    entry = {"url": url, "headers": headers}
    if with_type:
        entry = {"type": "http", **entry}
    return entry


def desktop_bridge_entry(url: str, headers: dict) -> dict:
    args = ["-y", "mcp-remote", url]
    for key, value in headers.items():
        args += ["--header", f"{key}: {value}"]
    return {"command": "npx", "args": args}


def build_entry(target: str, url: str, headers: dict) -> dict:
    if target == "claude-desktop":
        return desktop_bridge_entry(url, headers)
    return http_entry(url, headers, with_type=(target == "claude-code"))


# ---------- запись конфигов ----------

def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"Не смог распарсить {path}: {e}")


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        print(f"  Бэкап: {backup}")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mask(value: str) -> str:
    return f"{value[:4]}...{value[-2:]}" if len(value) > 6 else "***"


def mask_entry(entry: dict) -> dict:
    entry = json.loads(json.dumps(entry))
    headers = entry.get("headers")
    if headers:
        for key in headers:
            if key.lower() in {"authorization", "x-click-ru-token", "x-auth-token"}:
                headers[key] = mask(headers[key])
    if entry.get("args"):
        entry["args"] = [
            arg.split(": ", 1)[0] + ": " + mask(arg.split(": ", 1)[1])
            if ": " in arg and arg.split(": ", 1)[0].lower() in {"authorization", "x-click-ru-token"}
            else arg
            for arg in entry["args"]
        ]
    return entry


def apply_entries(config_path: Path, entries: dict[str, dict], *, remove: bool, dry_run: bool) -> None:
    config = load_json(config_path)
    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise SystemExit(f"{config_path}: поле mcpServers не объект, правлю вручную не буду")

    for name, entry in entries.items():
        if remove:
            if servers.pop(name, None) is not None:
                print(f"  - {name}: удалён")
            else:
                print(f"  - {name}: не был записан, пропускаю")
        else:
            replaced = name in servers
            servers[name] = entry
            print(f"  - {name}: {'перезаписан' if replaced else 'добавлен'}")
            print(f"    {json.dumps(mask_entry(entry), ensure_ascii=False)}")

    if not servers and remove:
        config.pop("mcpServers", None)

    if dry_run:
        print(f"[dry-run] Не пишу в {config_path}.")
        return
    save_json(config_path, config)
    print(f"  Записано: {config_path}")


# ---------- креды ----------

def resolve_credential(arg_value: str | None, env_name: str, service: str, *, required: bool) -> str | None:
    if arg_value:
        return arg_value
    if os.environ.get(env_name):
        return os.environ[env_name]
    if load_api_key:
        try:
            return load_api_key(service)
        except CredentialNotFound:
            pass
        except Exception:
            pass
    if required:
        raise SystemExit(
            f"Нужен {env_name}. Варианты:\n"
            f"  --token <...> (аргумент) или env {env_name}\n"
            f"  python -m scripts.manage_credentials set {service}\n"
            f"Токен создаётся в профиле click.ru: https://click.ru/userinfo.html → «API Token»."
        )
    return None


# ---------- main ----------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Подключить хостовые MCP (yandex-direct / yandex-wordstat) к Cursor, Claude Code, Claude Desktop",
    )
    parser.add_argument("--token", help="API-токен click.ru (или env CLICK_RU_TOKEN, или manage_credentials clickru)")
    parser.add_argument("--client-login", help="Логин аккаунта Яндекс.Директа (env CLICK_RU_CLIENT_LOGIN, manage_credentials clickru_login)")
    parser.add_argument("--click-ru-user-id", help="ID пользователя click.ru — только для мастер-аккаунта")
    parser.add_argument(
        "--server", choices=["direct", "wordstat", "both"], default="both",
        help="Какой сервер подключать (по умолчанию both — скиллу нужны оба)",
    )
    parser.add_argument(
        "--target", action="append",
        choices=["cursor", "cursor-project", "claude-code", "claude-desktop", "all"],
        help="Куда писать конфиг. Можно несколько раз. По умолчанию: cursor",
    )
    parser.add_argument("--remove", action="store_true", help="Удалить записи серверов из конфигов")
    parser.add_argument("--dry-run", action="store_true", help="Показать, что будет записано, без записи")
    args = parser.parse_args()

    targets = args.target or ["cursor"]
    if "all" in targets:
        targets = ["cursor", "claude-code", "claude-desktop"]

    server_names = {
        "direct": [DIRECT_SERVER],
        "wordstat": [WORDSTAT_SERVER],
        "both": [DIRECT_SERVER, WORDSTAT_SERVER],
    }[args.server]

    token = None
    client_login = None
    if not args.remove:
        token = resolve_credential(args.token, "CLICK_RU_TOKEN", "clickru", required=True)
        if DIRECT_SERVER in server_names:
            client_login = resolve_credential(
                args.client_login, "CLICK_RU_CLIENT_LOGIN", "clickru_login", required=False,
            )
            if not client_login:
                print("⚠️  --client-login не задан: запишу только Authorization. "
                      "Если Direct ответит 401/ошибкой доступа — перезапусти с --client-login.")

    all_headers: dict[str, dict] = {}
    if token:
        if DIRECT_SERVER in server_names:
            all_headers[DIRECT_SERVER] = direct_headers(token, client_login, args.click_ru_user_id)
        if WORDSTAT_SERVER in server_names:
            all_headers[WORDSTAT_SERVER] = wordstat_headers(token)

    urls = {DIRECT_SERVER: DIRECT_URL, WORDSTAT_SERVER: WORDSTAT_URL}

    print("=== Хостовые MCP aihub.click.ru ===")
    print(f"Серверы: {', '.join(server_names)}")
    print(f"Цели:    {', '.join(targets)}")
    print()

    for target in targets:
        path = TARGETS[target]()
        if path is None:
            print(f"[{target}] Не нашёл стандартный путь конфига для {platform.system()}, пропускаю.")
            continue
        print(f"[{target}] {path}")
        if target == "claude-desktop" and not args.remove:
            print("  Формат: stdio-мост npx mcp-remote (нужен Node.js в PATH)")
        entries = {
            name: build_entry(target, urls[name], all_headers.get(name, {}))
            for name in server_names
        }
        apply_entries(path, entries, remove=args.remove, dry_run=args.dry_run)
        print()

    if args.remove or args.dry_run:
        return

    print("=== Дальше ===")
    if "claude-desktop" in targets:
        print("1. Полностью закрой Claude Desktop (в трее тоже) и открой заново.")
    if "cursor" in targets or "cursor-project" in targets:
        print("1. Cursor: Settings → MCP — серверы должны стать зелёными (или перезапусти Cursor).")
    if "claude-code" in targets:
        print("1. Claude Code: новая сессия подхватит .mcp.json автоматически.")
    print("2. Проверь связь читающими вызовами:")
    if DIRECT_SERVER in server_names:
        print("   - Direct:   campaigns_get с limit=1")
    if WORDSTAT_SERVER in server_names:
        print("   - Wordstat: «пробей частотность фразы „кофеварка“»")
    print("3. Ошибка 401 = токен click.ru недействителен или не хватает --client-login.")
    print()
    print("Справочник подключения: docs/hosted-mcp-setup.md")


if __name__ == "__main__":
    main()
