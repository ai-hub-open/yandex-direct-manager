"""
video_providers — провайдер-абстракция генерации видео.
В этой итерации поддержан только Replicate (один ключ → десятки моделей).
Каталог моделей: references/replicate-models.md.
"""

from .base import BaseVideoProvider, VideoGenerationError
from .replicate import ReplicateProvider

PROVIDER_REGISTRY = {
    "replicate": ReplicateProvider,
}


def get_provider(name: str, api_key: str = None, model_id: str = None) -> BaseVideoProvider:
    if name not in PROVIDER_REGISTRY:
        available = ", ".join(PROVIDER_REGISTRY.keys())
        raise ValueError(f"Неизвестный провайдер '{name}'. Доступны: {available}")
    return PROVIDER_REGISTRY[name](api_key=api_key, model_id=model_id)


__all__ = ["BaseVideoProvider", "VideoGenerationError", "ReplicateProvider",
           "PROVIDER_REGISTRY", "get_provider"]
