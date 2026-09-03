"""Установщик MCP сохраняет токен click.ru в реестр ключей.

Проверяем, что после подключения коннектора (не dry-run, не remove) токен
click.ru оказывается в реестре — чтобы scripts/upload_creatives_to_storage.py
работал без отдельного `manage_credentials set clickru`.

Все кейсы без сети и без записи в настоящий HOME: conftest изолирует
HOME/USERPROFILE в tmp_path и запрещает connect. Пишем в цель `cursor`
(→ ~/.cursor/mcp.json, т.е. в изолированный HOME), чтобы не трогать конфиги
разработчика.
"""
from __future__ import annotations

import json
import sys

import pytest

import scripts.setup_yandex_direct_mcp as setup
from scripts.credentials import CredentialNotFound, load_api_key, set_api_key


def _run(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["setup_yandex_direct_mcp", *args])
    setup.main()


def _cursor_servers() -> dict:
    return json.loads(setup.cursor_user_config().read_text(encoding="utf-8"))["mcpServers"]


def test_installer_saves_clickru_token(monkeypatch):
    _run(monkeypatch, "--token", "JWT-TEST-TOKEN",
         "--client-login", "acme", "--server", "direct", "--target", "cursor")
    assert load_api_key("clickru") == "JWT-TEST-TOKEN"


def test_installer_saves_user_id(monkeypatch):
    _run(monkeypatch, "--token", "JWT-TEST-TOKEN", "--client-login", "acme",
         "--click-ru-user-id", "42", "--server", "direct", "--target", "cursor")
    assert load_api_key("clickru") == "JWT-TEST-TOKEN"
    assert load_api_key("clickru_user_id") == "42"


def test_user_id_from_env(monkeypatch):
    monkeypatch.setenv("CLICK_RU_USER_ID", "777")
    _run(monkeypatch, "--token", "JWT-TEST-TOKEN", "--client-login", "acme",
         "--server", "direct", "--target", "cursor")
    assert load_api_key("clickru_user_id") == "777"


def test_dry_run_does_not_touch_registry(monkeypatch, capsys):
    _run(monkeypatch, "--token", "JWT-TEST-TOKEN", "--client-login", "acme",
         "--server", "direct", "--target", "cursor", "--dry-run")
    with pytest.raises(CredentialNotFound):
        load_api_key("clickru")
    out = capsys.readouterr().out
    assert "dry-run" in out.lower()
    assert "clickru" in out


def test_remove_does_not_touch_registry(monkeypatch):
    set_api_key("clickru", "PRESET-TOKEN")
    _run(monkeypatch, "--server", "direct", "--target", "cursor", "--remove")
    # удаление коннектора не чистит реестр — ключ мог быть нужен другим скриптам
    assert load_api_key("clickru") == "PRESET-TOKEN"


def test_token_never_printed_in_full(monkeypatch, capsys):
    token = "JWT-SECRET-1234567890"
    _run(monkeypatch, "--token", token, "--client-login", "acme",
         "--server", "direct", "--target", "cursor")
    out = capsys.readouterr().out
    assert token not in out
    assert "сохранён в реестр" in out


def test_keepimage_connected_by_default(monkeypatch):
    # без --server → default all → KeepImage прописывается автоматически
    _run(monkeypatch, "--token", "JWT-TEST-TOKEN", "--client-login", "acme", "--target", "cursor")
    servers = _cursor_servers()
    assert "KeepImage" in servers
    assert servers["KeepImage"]["url"] == "https://storage.aihub.click.ru/mcp"
    assert servers["KeepImage"]["headers"]["X-Auth-Token"] == "JWT-TEST-TOKEN"
    # user-id не задан → заголовка нет
    assert "X-Auth-UserId" not in servers["KeepImage"]["headers"]


def test_keepimage_user_id_header(monkeypatch):
    _run(monkeypatch, "--token", "JWT-TEST-TOKEN", "--client-login", "acme",
         "--click-ru-user-id", "42", "--target", "cursor")
    headers = _cursor_servers()["KeepImage"]["headers"]
    assert headers["X-Auth-Token"] == "JWT-TEST-TOKEN"
    assert headers["X-Auth-UserId"] == "42"


def test_keepimage_token_not_in_url(monkeypatch):
    # токен идёт заголовком, а не в путь /c/<token>/mcp
    _run(monkeypatch, "--token", "SECRET-TOKEN-123", "--client-login", "acme", "--target", "cursor")
    ki = _cursor_servers()["KeepImage"]
    assert ki["url"] == "https://storage.aihub.click.ru/mcp"
    assert "SECRET-TOKEN-123" not in ki["url"]


def test_server_direct_excludes_keepimage(monkeypatch):
    _run(monkeypatch, "--token", "JWT-TEST-TOKEN", "--client-login", "acme",
         "--server", "direct", "--target", "cursor")
    servers = _cursor_servers()
    assert "yandex-direct" in servers
    assert "KeepImage" not in servers
    assert "yandex-wordstat" not in servers


def test_registry_error_does_not_break_install(monkeypatch, capsys):
    def boom(*_a, **_kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(setup, "set_api_key", boom)
    # не должно бросить: подключение MCP важнее записи в реестр
    _run(monkeypatch, "--token", "JWT-TEST-TOKEN", "--client-login", "acme",
         "--server", "direct", "--target", "cursor")
    out = capsys.readouterr().out
    assert "не сохранён в реестр" in out
    # конфиг клиента при этом записан
    assert (setup.cursor_user_config()).exists()
