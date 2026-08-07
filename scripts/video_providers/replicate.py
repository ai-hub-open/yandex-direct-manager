"""
replicate.py — универсальный провайдер через Replicate (https://replicate.com).

Replicate — хаб для запуска ML-моделей. Через один API ключ доступны сотни
моделей видео-генерации, которые обновляются быстро (новые SOTA выходят
каждую неделю — Kling, Hunyuan, Seedance, Wan, Hailuo, Mochi, и т.д.).

Преимущество перед прямыми провайдерами:
- Один ключ для всех моделей
- Можно быстро тестировать новые модели без переписывания кода
- Pay-per-use, без подписок
- Стабильный единый API (POST prediction → polling → output URL)

Использование:
    from scripts.video_providers import get_provider
    provider = get_provider("replicate")
    provider.set_model("kwaivgi/kling-v1.6-standard")  # или version hash
    video = provider.generate(prompt="...", duration_sec=5, aspect_ratio="9:16",
                              output_path=Path("video.mp4"))

Каталог моделей: см. references/replicate-models.md
"""

import time
from pathlib import Path
from typing import Optional

from .base import BaseVideoProvider, VideoGenerationError


# Маппинг универсальных параметров на input-поля каждой модели.
# Если модель не в маппинге — используем дефолтную сигнатуру.
# Расширяйте этот словарь когда добавляете новые модели.
MODEL_INPUT_SCHEMAS = {
    # Kling v1.6 / v2 на Replicate
    "kwaivgi/kling-v1.6-standard": {
        "prompt": "prompt",
        "duration": ("duration", lambda d: str(d)),  # "5" or "10"
        "aspect_ratio": "aspect_ratio",
        "seed_image": "start_image",
        "extra": {"cfg_scale": 0.5},
    },
    "kwaivgi/kling-v1.6-pro": {
        "prompt": "prompt",
        "duration": ("duration", lambda d: str(d)),
        "aspect_ratio": "aspect_ratio",
        "seed_image": "start_image",
        "extra": {"cfg_scale": 0.5},
    },
    "kwaivgi/kling-v2-master": {
        "prompt": "prompt",
        "duration": ("duration", lambda d: str(d)),
        "aspect_ratio": "aspect_ratio",
        "seed_image": "start_image",
    },
    # Bytedance Seedance
    "bytedance/seedance-1-pro": {
        "prompt": "prompt",
        "duration": "duration",
        "aspect_ratio": "aspect_ratio",
        "seed_image": "image",
    },
    "bytedance/seedance-1-lite": {
        "prompt": "prompt",
        "duration": "duration",
        "aspect_ratio": "aspect_ratio",
        "seed_image": "image",
    },
    # Tencent Hunyuan
    "tencent/hunyuan-video": {
        "prompt": "prompt",
        "duration": ("video_length", lambda d: int(d * 24)),  # frames at 24fps
        "aspect_ratio": "aspect_ratio",
    },
    # Wan 2.1 / 2.2
    "wavespeedai/wan-2.1-i2v-720p": {
        "prompt": "prompt",
        "duration": ("num_frames", lambda d: int(d * 16)),  # 16 fps
        "seed_image": "image",
    },
    # Minimax Hailuo
    "minimax/video-01": {
        "prompt": "prompt",
        "seed_image": "first_frame_image",
    },
    "minimax/hailuo-02": {
        "prompt": "prompt",
        "duration": "duration",
        "aspect_ratio": "aspect_ratio",
        "seed_image": "first_frame_image",
    },
    # Google Veo через Replicate
    "google/veo-3": {
        "prompt": "prompt",
        "aspect_ratio": "aspect_ratio",
        "duration": "duration",
    },
}


# Дефолтная схема — если модель не в маппинге, пробуем эти ключи
DEFAULT_SCHEMA = {
    "prompt": "prompt",
    "duration": "duration",
    "aspect_ratio": "aspect_ratio",
    "seed_image": "image",
}


class ReplicateProvider(BaseVideoProvider):
    SERVICE_NAME = "replicate"
    # Универсальные значения — реальная модель решает что поддерживает
    SUPPORTED_DURATIONS = []  # пусто = не проверяем (модель сама решит)
    SUPPORTED_ASPECT_RATIOS = []  # пусто = не проверяем
    PRICE_PER_SECOND_USD = None  # зависит от модели — Replicate показывает на model page

    API_BASE = "https://api.replicate.com/v1"
    POLL_INTERVAL_SEC = 5
    MAX_POLL_ATTEMPTS = 180  # до 15 минут (некоторые модели медленные)

    def __init__(self, api_key: Optional[str] = None, model_id: Optional[str] = None):
        super().__init__(api_key=api_key)
        self.model_id = model_id  # например "kwaivgi/kling-v1.6-standard"

    def set_model(self, model_id: str):
        """Установить ID модели Replicate."""
        self.model_id = model_id

    def _build_input(self, prompt: str, duration_sec: int, aspect_ratio: str, seed_image_path: Optional[Path]) -> dict:
        """Конвертирует универсальные параметры в input для конкретной модели."""
        schema = MODEL_INPUT_SCHEMAS.get(self.model_id, DEFAULT_SCHEMA)
        input_dict = {}

        def apply(value, mapping):
            """mapping может быть строкой (имя поля) или (имя, transform_fn)."""
            if isinstance(mapping, tuple):
                key, fn = mapping
                input_dict[key] = fn(value)
            else:
                input_dict[mapping] = value

        if "prompt" in schema:
            apply(prompt, schema["prompt"])
        if "duration" in schema and duration_sec:
            apply(duration_sec, schema["duration"])
        if "aspect_ratio" in schema and aspect_ratio:
            apply(aspect_ratio, schema["aspect_ratio"])
        if "seed_image" in schema and seed_image_path:
            # Replicate принимает либо URL, либо data URI
            import base64
            mime = "image/png" if str(seed_image_path).endswith(".png") else "image/jpeg"
            with open(seed_image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            apply(f"data:{mime};base64,{b64}", schema["seed_image"])

        # Дополнительные параметры от схемы (cfg_scale и т.п.)
        if "extra" in schema:
            input_dict.update(schema["extra"])

        return input_dict

    def generate(
        self,
        prompt: str,
        duration_sec: int = 5,
        aspect_ratio: str = "9:16",
        output_path: Path = None,
        seed_image_path: Optional[Path] = None,
        model_id: Optional[str] = None,
        **kwargs,
    ) -> Path:
        if model_id:
            self.model_id = model_id
        if not self.model_id:
            raise VideoGenerationError(
                "ReplicateProvider: укажи модель через --model <owner>/<name> "
                "или provider.set_model(). См. references/replicate-models.md"
            )

        try:
            import requests
        except ImportError:
            raise VideoGenerationError("pip install requests")

        input_dict = self._build_input(prompt, duration_sec, aspect_ratio, seed_image_path)

        # Применяем kwargs как переопределения (если пользователь передал
        # специфичные параметры модели)
        for k, v in kwargs.items():
            if v is not None:
                input_dict[k] = v

        # Replicate API: POST /v1/predictions
        # Можно передать version hash или slug (owner/name)
        # Если slug — используем /v1/models/{owner}/{name}/predictions endpoint
        if "/" in self.model_id and ":" not in self.model_id:
            # Это slug формата owner/name (без версии)
            url = f"{self.API_BASE}/models/{self.model_id}/predictions"
            payload = {"input": input_dict}
        else:
            # Это version hash, передаём как version
            url = f"{self.API_BASE}/predictions"
            payload = {"version": self.model_id, "input": input_dict}

        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
            "Prefer": "wait=5",  # try sync first, fallback to async
        }

        try:
            r = requests.post(url, json=payload, headers=headers, timeout=60)
            if not r.ok:
                raise VideoGenerationError(f"Replicate POST {r.status_code}: {r.text[:500]}")
            pred = r.json()
        except requests.RequestException as e:
            raise VideoGenerationError(f"Replicate request error: {e}")

        pred_id = pred.get("id")
        if not pred_id:
            raise VideoGenerationError(f"Replicate не вернул id: {pred}")

        print(f"  Replicate prediction: {pred_id} (model {self.model_id})")

        # Polling
        video_url = None
        status = pred.get("status")
        # Если уже succeeded (Prefer: wait=5) — берём сразу
        if status == "succeeded":
            output = pred.get("output")
            video_url = _extract_video_url(output)
        else:
            for attempt in range(self.MAX_POLL_ATTEMPTS):
                time.sleep(self.POLL_INTERVAL_SEC)
                try:
                    r = requests.get(
                        f"{self.API_BASE}/predictions/{pred_id}",
                        headers={"Authorization": f"Token {self.api_key}"},
                        timeout=30,
                    )
                    r.raise_for_status()
                    pred = r.json()
                    status = pred.get("status")
                    if status == "succeeded":
                        video_url = _extract_video_url(pred.get("output"))
                        break
                    if status in ("failed", "canceled"):
                        err = pred.get("error") or "no error message"
                        raise VideoGenerationError(f"Replicate prediction {status}: {err}")
                    print(f"  …status={status} (attempt {attempt + 1}/{self.MAX_POLL_ATTEMPTS})")
                except requests.RequestException as e:
                    print(f"  poll error: {e}")

        if not video_url:
            raise VideoGenerationError(
                f"Replicate не вернул видео за {self.MAX_POLL_ATTEMPTS * self.POLL_INTERVAL_SEC}s"
            )

        # Download
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            r = requests.get(video_url, timeout=300)
            r.raise_for_status()
            output_path.write_bytes(r.content)
        except requests.RequestException as e:
            raise VideoGenerationError(f"Download failed: {e}")

        return output_path


def _extract_video_url(output) -> Optional[str]:
    """Replicate возвращает output в разных форматах: строка, список, dict."""
    if not output:
        return None
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        # Берём первый — обычно это видео-URL
        return output[0] if output else None
    if isinstance(output, dict):
        # Некоторые модели возвращают {"video": "url"}
        for key in ("video", "url", "output"):
            if key in output:
                v = output[key]
                if isinstance(v, str):
                    return v
                if isinstance(v, list) and v:
                    return v[0]
    return None
