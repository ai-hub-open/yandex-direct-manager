"""Replicate-провайдер: схемы входа, разбор URL, generate с моком requests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.video_providers import get_provider
from scripts.video_providers.base import BaseVideoProvider, VideoGenerationError
from scripts.video_providers.replicate import (
    ReplicateProvider,
    _extract_video_url,
)


def test_get_provider_unknown_raises():
    with pytest.raises(ValueError, match="replicate") as exc:
        get_provider("runway")
    assert "Неизвестный провайдер" in str(exc.value)


def test_get_provider_with_explicit_key():
    p = get_provider("replicate", api_key="r8_test", model_id="kwaivgi/kling-v1.6-standard")
    assert isinstance(p, ReplicateProvider)
    assert p.api_key == "r8_test"
    assert p.model_id == "kwaivgi/kling-v1.6-standard"


def test_build_input_kling_duration_string_and_cfg():
    p = ReplicateProvider(api_key="k", model_id="kwaivgi/kling-v1.6-standard")
    out = p._build_input("hello", 5, "16:9", None)
    assert out["prompt"] == "hello"
    assert out["duration"] == "5"
    assert out["aspect_ratio"] == "16:9"
    assert out["cfg_scale"] == 0.5


def test_build_input_hunyuan_and_wan_frame_math():
    hun = ReplicateProvider(api_key="k", model_id="tencent/hunyuan-video")
    assert hun._build_input("p", 5, "16:9", None)["video_length"] == 120
    wan = ReplicateProvider(api_key="k", model_id="wavespeedai/wan-2.1-i2v-720p")
    assert wan._build_input("p", 5, "16:9", None)["num_frames"] == 80


def test_build_input_minimax_without_duration():
    p = ReplicateProvider(api_key="k", model_id="minimax/video-01")
    out = p._build_input("p", 5, "16:9", None)
    assert "duration" not in out
    assert out["prompt"] == "p"


def test_build_input_unknown_slug_uses_default_schema():
    p = ReplicateProvider(api_key="k", model_id="someone/new-model")
    out = p._build_input("p", 8, "1:1", None)
    assert out == {"prompt": "p", "duration": 8, "aspect_ratio": "1:1"}


def test_build_input_seed_image_data_uri(tmp_path):
    png = tmp_path / "seed.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    p = ReplicateProvider(api_key="k", model_id="kwaivgi/kling-v1.6-standard")
    out = p._build_input("p", 5, "16:9", png)
    assert out["start_image"].startswith("data:image/png;base64,")


@pytest.mark.parametrize(
    "output, expected",
    [
        ("https://v.mp4", "https://v.mp4"),
        (["https://a.mp4", "https://b.mp4"], "https://a.mp4"),
        ({"video": "https://v.mp4"}, "https://v.mp4"),
        ({"url": ["https://u.mp4"]}, "https://u.mp4"),
        (None, None),
        ([], None),
        ({}, None),
    ],
)
def test_extract_video_url_shapes(output, expected):
    assert _extract_video_url(output) == expected


def test_validate_params_empty_lists_are_noop():
    p = ReplicateProvider(api_key="k", model_id="x")
    p.validate_params(99, "99:1")  # не бросает


def test_validate_params_reports_nearest_duration():
    class Fixed(BaseVideoProvider):
        SERVICE_NAME = "replicate"
        SUPPORTED_DURATIONS = [5, 10]
        SUPPORTED_ASPECT_RATIOS = ["16:9"]

        def generate(self, *a, **kw):
            raise NotImplementedError

    p = Fixed(api_key="k")
    with pytest.raises(VideoGenerationError, match="Ближайший: 5s"):
        p.validate_params(6, "16:9")
    with pytest.raises(VideoGenerationError, match="1:1"):
        p.validate_params(5, "1:1")


def test_estimate_cost_none_price():
    assert ReplicateProvider(api_key="k").estimate_cost(10) == 0.0


def _mock_response(payload, ok=True, status=200, content=b"video-bytes"):
    r = MagicMock()
    r.ok = ok
    r.status_code = status
    r.text = str(payload)
    r.json.return_value = payload
    r.content = content
    r.raise_for_status = MagicMock()
    return r


def _fake_requests(post, get):
    """Мок requests: RequestException — отдельный класс, не Exception."""
    import sys
    from unittest.mock import MagicMock

    class RequestException(Exception):
        pass

    fake = MagicMock()
    fake.post = post
    fake.get = get
    fake.RequestException = RequestException
    return fake


def test_generate_slug_endpoint_and_immediate_success(tmp_path, monkeypatch, fast_sleep):
    import sys

    posts = []
    gets = []

    def fake_post(url, json=None, headers=None, timeout=None):
        posts.append((url, json))
        return _mock_response({"id": "pred1", "status": "succeeded", "output": "https://v.mp4"})

    def fake_get(url, headers=None, timeout=None):
        gets.append(url)
        return _mock_response({}, content=b"MP4DATA")

    monkeypatch.setitem(sys.modules, "requests", _fake_requests(fake_post, fake_get))

    out = tmp_path / "out.mp4"
    p = ReplicateProvider(api_key="r8", model_id="kwaivgi/kling-v1.6-standard")
    path = p.generate("prompt", 5, "16:9", out)
    assert path == out
    assert out.read_bytes() == b"MP4DATA"
    assert posts[0][0].endswith("/models/kwaivgi/kling-v1.6-standard/predictions")
    assert "input" in posts[0][1]
    assert "version" not in posts[0][1]
    assert gets == ["https://v.mp4"]  # только скачивание, без polling


def test_generate_version_hash_endpoint(tmp_path, monkeypatch, fast_sleep):
    import sys

    posts = []

    def fake_post(url, json=None, headers=None, timeout=None):
        posts.append((url, json))
        return _mock_response({"id": "p2", "status": "succeeded", "output": "https://v.mp4"})

    def fake_get(url, headers=None, timeout=None):
        return _mock_response({}, content=b"X")

    monkeypatch.setitem(sys.modules, "requests", _fake_requests(fake_post, fake_get))

    p = ReplicateProvider(api_key="r8", model_id="abc123hash")
    p.generate("p", 5, "16:9", tmp_path / "v.mp4")
    assert posts[0][0].endswith("/predictions")
    assert posts[0][1]["version"] == "abc123hash"


def test_generate_failed_status(tmp_path, monkeypatch, fast_sleep):
    import sys

    def fake_post(url, json=None, headers=None, timeout=None):
        return _mock_response({"id": "p3", "status": "starting"})

    def fake_get(url, headers=None, timeout=None):
        return _mock_response({"status": "failed", "error": "bad prompt"})

    monkeypatch.setitem(sys.modules, "requests", _fake_requests(fake_post, fake_get))

    p = ReplicateProvider(api_key="r8", model_id="kwaivgi/kling-v1.6-standard")
    with pytest.raises(VideoGenerationError, match="failed"):
        p.generate("p", 5, "16:9", tmp_path / "v.mp4")


def test_generate_missing_id(tmp_path, monkeypatch, fast_sleep):
    import sys

    monkeypatch.setitem(
        sys.modules, "requests",
        _fake_requests(
            lambda *a, **k: _mock_response({"status": "starting"}),
            lambda *a, **k: _mock_response({}),
        ),
    )

    p = ReplicateProvider(api_key="r8", model_id="kwaivgi/kling-v1.6-standard")
    with pytest.raises(VideoGenerationError, match="не вернул id"):
        p.generate("p", 5, "16:9", tmp_path / "v.mp4")


def test_generate_poll_timeout(tmp_path, monkeypatch, fast_sleep):
    import sys

    def fake_post(url, json=None, headers=None, timeout=None):
        return _mock_response({"id": "slow", "status": "starting"})

    def fake_get(url, headers=None, timeout=None):
        return _mock_response({"status": "processing"})

    monkeypatch.setitem(sys.modules, "requests", _fake_requests(fake_post, fake_get))

    p = ReplicateProvider(api_key="r8", model_id="kwaivgi/kling-v1.6-standard")
    p.MAX_POLL_ATTEMPTS = 2
    with pytest.raises(VideoGenerationError, match="не вернул видео"):
        p.generate("p", 5, "16:9", tmp_path / "v.mp4")


def test_generate_requires_model():
    p = ReplicateProvider(api_key="r8")
    with pytest.raises(VideoGenerationError, match="укажи модель"):
        p.generate("p", 5, "16:9", Path("x.mp4"))
