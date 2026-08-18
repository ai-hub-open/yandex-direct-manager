"""Общие фикстуры: изоляция HOME/env и запрет сети.

Тесты скилла не ходят в OpenAI, Replicate и Директ: любой реальный connect
падает AssertionError. Реальные ключи разработчика в ~/.yandex-direct-manager
не трогаем — HOME подменяется на tmp_path.
"""
from __future__ import annotations

import socket

import pytest

_SERVICE_ENV = (
    "OPENAI_API_KEY",
    "REPLICATE_API_TOKEN",
    "YANDEX_DIRECT_TOKEN",
    "CLICK_RU_TOKEN",
    "CLICK_RU_CLIENT_LOGIN",
    "CLICK_RU_USER_ID",
)


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


@pytest.fixture(autouse=True)
def _clear_service_env(monkeypatch):
    for name in _SERVICE_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def deny(*_a, **_kw):
        raise AssertionError("тест полез в сеть — нужен мок")

    monkeypatch.setattr(socket.socket, "connect", deny)


@pytest.fixture
def fast_sleep(monkeypatch):
    """Подмена time.sleep в модулях с задержками (retry/poll/throttle)."""
    import scripts.forecast_cpc as forecast_cpc
    import scripts.generate_creative_images as gen_images
    import scripts.generate_creative_videos as gen_videos
    import scripts.video_providers.replicate as replicate

    monkeypatch.setattr(forecast_cpc.time, "sleep", lambda *_a, **_kw: None)
    monkeypatch.setattr(gen_images.time, "sleep", lambda *_a, **_kw: None)
    monkeypatch.setattr(gen_videos.time, "sleep", lambda *_a, **_kw: None)
    monkeypatch.setattr(replicate.time, "sleep", lambda *_a, **_kw: None)
