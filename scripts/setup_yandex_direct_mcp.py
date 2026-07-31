"""
setup_yandex_direct_mcp.py — Установщик MCP yandex-direct в Claude Desktop.

Берёт локальную копию MCP-сервера (Bun + TS), проверяет окружение,
прописывает блок mcpServers.yandex-direct в claude_desktop_config.json
с правильным абсолютным путём, токеном и режимом (sandbox/production/Click.ru).

После выполнения нужно перезапустить Claude Desktop — после этого в новой сессии
скилл сможет вызывать MCP-инструменты напрямую (mcp__yandex-direct__yandex_direct_*,
всего 50 штук).

Использование:
    python -m scripts.setup_yandex_direct_mcp \
        --mcp-path D:\\yandex-direct-mcp \
        [--mode direct|sandbox|clickru] \
        [--token <OAUTH_TOKEN>] \
        [--click-ru-token <X-Auth-Token>] \
        [--click-ru-user-id <UserId>] \
        [--client-login <login>] \
        [--config-path <path-to-claude_desktop_config.json>] \
        [--dry-run]

Скрипт ничего не отправляет наружу и маскирует токен в логах.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path


def default_config_path() -> Path | None:
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Linux":
        xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        return Path(xdg) / "Claude" / "claude_desktop_config.json"
    return None


def check_bun() -> str | None:
    return shutil.which("bun")


def bun_install_hint() -> str:
    if platform.system() == "Windows":
        return 'Установить Bun: открой PowerShell и выполни\n  powershell -c "irm bun.sh/install.ps1 | iex"'
    return "Установить Bun:\n  curl -fsSL https://bun.sh/install | bash"


def verify_mcp_path(mcp_path: Path) -> tuple[bool, str]:
    if not mcp_path.exists():
        return False, f"Папка {mcp_path} не найдена"
    if not (mcp_path / "package.json").exists():
        return False, f"В {mcp_path} нет package.json"
    if not (mcp_path / "src" / "index.ts").exists():
        return False, f"В {mcp_path}/src/index.ts нет точки входа"
    if not (mcp_path / "node_modules").exists():
        return False, f"В {mcp_path} не установлены зависимости. Запусти: cd \"{mcp_path}\" && bun install"
    return True, "OK"


def build_server_block(
    mcp_path: Path,
    mode: str,
    token: str | None,
    click_ru_token: str | None,
    click_ru_user_id: str | None,
    client_login: str | None,
) -> dict:
    args_path = str(mcp_path / "src" / "index.ts").replace("\\", "/")
    env: dict[str, str] = {}
    if mode == "direct":
        if not token:
            raise ValueError("Для режима direct нужен --token (OAuth Яндекс.Директа)")
        env["YANDEX_DIRECT_TOKEN"] = token
        env["YANDEX_DIRECT_SANDBOX"] = "false"
    elif mode == "sandbox":
        if not token:
            raise ValueError("Для режима sandbox нужен --token (sandbox-токен)")
        env["YANDEX_DIRECT_TOKEN"] = token
        env["YANDEX_DIRECT_SANDBOX"] = "true"
    elif mode == "clickru":
        if not click_ru_token or not client_login:
            raise ValueError(
                "Для clickru нужны --click-ru-token и --client-login. "
                "Опционально --click-ru-user-id для мастер-аккаунтов."
            )
        env["CLICK_RU_PROXY"] = "true"
        env["CLICK_RU_TOKEN"] = click_ru_token
        env["CLICK_RU_CLIENT_LOGIN"] = client_login
        if click_ru_user_id:
            env["CLICK_RU_USER_ID"] = click_ru_user_id
    else:
        raise ValueError(f"Неизвестный режим: {mode}")

    return {
        "command": "bun",
        "args": ["run", args_path],
        "env": env,
    }


def update_config(config_path: Path, server_block: dict, server_name: str = "yandex-direct") -> tuple[dict, dict | None]:
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise SystemExit(f"Не смог распарсить {config_path}: {e}")
    else:
        config = {}

    if not isinstance(config.get("mcpServers"), dict):
        config["mcpServers"] = {}

    previous = config["mcpServers"].get(server_name)
    config["mcpServers"][server_name] = server_block
    return config, previous


def mask_env(env: dict) -> dict:
    masked = {}
    secrets = {"YANDEX_DIRECT_TOKEN", "CLICK_RU_TOKEN"}
    for k, v in env.items():
        if k in secrets and v:
            masked[k] = f"{v[:4]}...{v[-2:]}" if len(v) > 6 else "***"
        else:
            masked[k] = v
    return masked


def main() -> None:
    parser = argparse.ArgumentParser(description="Установить yandex-direct MCP в Claude Desktop")
    parser.add_argument("--mcp-path", required=True, help="Путь к локальной папке MCP")
    parser.add_argument(
        "--mode", choices=["direct", "sandbox", "clickru"], default="sandbox",
        help="Режим: direct/sandbox/clickru",
    )
    parser.add_argument("--token", help="OAuth-токен Yandex Direct")
    parser.add_argument("--click-ru-token", help="X-Auth-Token из api.click.ru")
    parser.add_argument("--click-ru-user-id", help="X-Auth-UserId")
    parser.add_argument("--client-login", help="Client-Login Яндекс.Директа")
    parser.add_argument("--server-name", default="yandex-direct")
    parser.add_argument("--config-path", help="Путь к claude_desktop_config.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    mcp_path = Path(args.mcp_path).resolve()
    config_path = Path(args.config_path).resolve() if args.config_path else default_config_path()
    if not config_path:
        raise SystemExit(f"Не нашёл стандартный путь к Claude Desktop config для {platform.system()}. Передай --config-path.")

    print(f"=== yandex-direct MCP setup ===")
    print(f"MCP path:    {mcp_path}")
    print(f"Config:      {config_path}")
    print(f"Mode:        {args.mode}")
    print(f"Server name: {args.server_name}")
    print()

    bun = check_bun()
    if not bun:
        print("Bun не найден в PATH. " + bun_install_hint())
        print("MCP не запустится без Bun.")
    else:
        print(f"Bun: {bun}")
        try:
            ver = subprocess.run([bun, "--version"], capture_output=True, text=True, timeout=5)
            print(f"  Версия: {ver.stdout.strip()}")
        except Exception:
            pass

    ok, msg = verify_mcp_path(mcp_path)
    if not ok:
        print(f"MCP: {msg}")
        raise SystemExit(1)
    print(f"MCP: {msg}")

    try:
        server_block = build_server_block(
            mcp_path=mcp_path, mode=args.mode, token=args.token,
            click_ru_token=args.click_ru_token, click_ru_user_id=args.click_ru_user_id,
            client_login=args.client_login,
        )
    except ValueError as e:
        raise SystemExit(f"Параметры: {e}")

    print()
    print(f"Будет записан блок mcpServers.{args.server_name}:")
    print(json.dumps({
        "command": server_block["command"],
        "args": server_block["args"],
        "env": mask_env(server_block["env"]),
    }, indent=2, ensure_ascii=False))

    new_config, previous = update_config(config_path, server_block, args.server_name)
    if previous:
        print(f"\nВ конфиге уже был блок '{args.server_name}'. Перезаписываю.")

    if args.dry_run:
        print(f"\n[dry-run] Не пишу в {config_path}.")
        return

    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        backup = config_path.with_suffix(config_path.suffix + ".bak")
        shutil.copy2(config_path, backup)
        print(f"\nБэкап старого конфига: {backup}")

    config_path.write_text(json.dumps(new_config, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Записал в {config_path}")
    print()
    print("=== Дальше ===")
    print("1. Полностью закрой Claude Desktop (в трее тоже).")
    print("2. Открой заново.")
    print(f"3. В новой сессии появятся инструменты mcp__{args.server_name}__yandex_direct_*")
    print("   (всего 50: campaigns, adgroups, ads, adimages, sitelinks, adextensions,")
    print("    keywords, keywordbids, bidmodifiers, forecast, reports, dictionaries).")
    print("4. Скажи скиллу 'запусти кампанию через MCP' — он использует их напрямую.")


if __name__ == "__main__":
    main()
