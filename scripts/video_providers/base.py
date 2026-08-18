"""
base.py — базовый класс для провайдеров видео-генерации.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class VideoGenerationError(Exception):
    """Ошибка генерации видео — провайдер не смог."""


class BaseVideoProvider(ABC):
    """
    Базовый класс провайдера видео-генерации.

    Подклассы должны реализовать `generate()` и определить:
    - SERVICE_NAME — ключ сервиса в credentials.py (например "runway")
    - SUPPORTED_DURATIONS — список поддерживаемых длительностей в секундах
    - SUPPORTED_ASPECT_RATIOS — список поддерживаемых соотношений сторон
    """

    SERVICE_NAME: str = None
    SUPPORTED_DURATIONS: list = []
    SUPPORTED_ASPECT_RATIOS: list = []
    PRICE_PER_SECOND_USD: float = None  # для оценки стоимости

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or self._load_api_key()

    def _load_api_key(self) -> str:
        """Загружает API-ключ через scripts.credentials."""
        if not self.SERVICE_NAME:
            raise NotImplementedError(f"{self.__class__.__name__} не задан SERVICE_NAME")
        try:
            from scripts.credentials import load_api_key
        except ImportError:
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from scripts.credentials import load_api_key
        return load_api_key(self.SERVICE_NAME)

    @abstractmethod
    def generate(
        self,
        prompt: str,
        duration_sec: int,
        aspect_ratio: str,
        output_path: Path,
        seed_image_path: Optional[Path] = None,
        **kwargs,
    ) -> Path:
        """
        Генерирует видео по промпту и сохраняет в output_path.

        Args:
            prompt: текстовый промпт
            duration_sec: длительность в секундах
            aspect_ratio: "9:16", "1:1", "16:9"
            output_path: куда сохранить MP4
            seed_image_path: опционально — стартовая картинка (image-to-video)
            **kwargs: провайдер-специфичные опции

        Returns:
            Path к сохранённому видео-файлу

        Raises:
            VideoGenerationError: если генерация не удалась
        """

    def validate_params(self, duration_sec: int, aspect_ratio: str):
        """Проверяет что параметры поддерживаются провайдером."""
        if self.SUPPORTED_DURATIONS and duration_sec not in self.SUPPORTED_DURATIONS:
            nearest = min(self.SUPPORTED_DURATIONS, key=lambda x: abs(x - duration_sec))
            raise VideoGenerationError(
                f"{self.__class__.__name__} не поддерживает {duration_sec}s. "
                f"Поддерживает: {self.SUPPORTED_DURATIONS}. Ближайший: {nearest}s."
            )

        if self.SUPPORTED_ASPECT_RATIOS and aspect_ratio not in self.SUPPORTED_ASPECT_RATIOS:
            raise VideoGenerationError(
                f"{self.__class__.__name__} не поддерживает {aspect_ratio}. "
                f"Поддерживает: {self.SUPPORTED_ASPECT_RATIOS}."
            )

    def estimate_cost(self, duration_sec: int) -> float:
        """Оценка стоимости генерации в USD."""
        if self.PRICE_PER_SECOND_USD is None:
            return 0.0
        return duration_sec * self.PRICE_PER_SECOND_USD
