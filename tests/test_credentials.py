"""Хранение ключей: env vs credentials.json, без записи в домашний каталог пользователя."""
from __future__ import annotations

import json
import os
import stat

import pytest

from scripts.credentials import (
    SERVICE_REGISTRY,
    CredentialNotFound,
    credentials_file,
    delete_api_key,
    list_stored_services,
    load_api_key,
    set_api_key,
)
from scripts.manage_credentials import mask


def test_env_beats_file(monkeypatch):
    set_api_key("openai", "sk-from-file-xxxx")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env-yyyy")
    assert load_api_key("openai") == "sk-from-env-yyyy"


def test_reads_from_credentials_file():
    set_api_key("replicate", "r8_stored_token")
    assert load_api_key("replicate") == "r8_stored_token"


def test_missing_key_names_env_var():
    with pytest.raises(CredentialNotFound) as exc:
        load_api_key("openai")
    assert "OPENAI_API_KEY" in str(exc.value)
    assert exc.value.service == "openai"


def test_unknown_service_raises_value_error():
    with pytest.raises(ValueError, match="Неизвестный сервис"):
        load_api_key("not-a-service")
    with pytest.raises(ValueError, match="Неизвестный сервис"):
        set_api_key("not-a-service", "x")


def test_set_list_delete_roundtrip():
    assert list_stored_services() == []
    set_api_key("clickru", "jwt-token")
    assert "clickru" in list_stored_services()
    assert delete_api_key("clickru") is True
    assert "clickru" not in list_stored_services()
    assert delete_api_key("clickru") is False


def test_broken_json_returns_empty():
    fp = credentials_file()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text("{not-json", encoding="utf-8")
    assert list_stored_services() == []


@pytest.mark.skipif(os.name != "posix", reason="chmod 600 только на POSIX")
def test_credentials_file_mode_600():
    set_api_key("yandex_direct", "y0_token")
    mode = credentials_file().stat().st_mode & 0o777
    assert mode == 0o600


def test_mask_hides_middle_and_short_keys():
    assert mask("sk-1234567890ab") == "sk-1...90ab"
    assert mask("short") == "***"
    assert mask("") == "***"


def test_registry_covers_expected_services():
    for name in ("openai", "replicate", "yandex_direct", "clickru", "clickru_login", "clickru_user_id"):
        assert name in SERVICE_REGISTRY
        assert "env" in SERVICE_REGISTRY[name]
