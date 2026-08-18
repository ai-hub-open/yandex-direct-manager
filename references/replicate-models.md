# Каталог Replicate моделей для генерации видео

Replicate — хаб с десятками видео-моделей под одним API. Используется через провайдер `replicate` с параметром `--model <slug>`.

## Где смотреть актуальный каталог

Полный список: https://replicate.com/explore (фильтр «video»)

Топ-листы:
- https://replicate.com/collections/text-to-video
- https://replicate.com/collections/image-to-video

Каждая модель имеет страницу с примерами, ценой и точной сигнатурой input. Перед использованием новой модели — глянь её page чтобы понять какие параметры она принимает.

## Поддерживаемые модели (с готовыми input-маппингами)

Скилл умеет автоматически маппить универсальные параметры (prompt / duration / aspect_ratio / seed_image) на input для следующих моделей. Если модель не в этом списке — будет использован дефолтный маппинг (с риском неточностей в параметрах).

### Kling

| Slug | Длительность | Цена ориент. | Сильная сторона |
|---|---|---|---|
| `kwaivgi/kling-v1.6-standard` | 5/10s | ~$0.05/sec | Доступный, стабильный |
| `kwaivgi/kling-v1.6-pro` | 5/10s | ~$0.10/sec | Лучше качество, дороже |
| `kwaivgi/kling-v2-master` | 5/10s | ~$0.28/sec | Текущий флагман Kling, хорошо для UGC-style |

**Ключевая особенность Kling:** хорошие переходы при image-to-video (сильная сторона, даже если наш CLI пока не делает автосклейку сегментов — см. «Ограничения» в `references/video-generation.md`).

### Bytedance Seedance

| Slug | Длительность | Цена ориент. | Сильная сторона |
|---|---|---|---|
| `bytedance/seedance-1-pro` | 5/10s | ~$0.15/sec | Высокое качество motion |
| `bytedance/seedance-1-lite` | 5/10s | ~$0.04/sec | Дёшево, для теста |

### Tencent Hunyuan

| Slug | Длительность | Цена ориент. | Сильная сторона |
|---|---|---|---|
| `tencent/hunyuan-video` | 2-6s (через num_frames) | ~$0.20/sec | Open-source модель в облаке |

### Wan Video

| Slug | Длительность | Цена ориент. | Сильная сторона |
|---|---|---|---|
| `wavespeedai/wan-2.1-i2v-720p` | до 5s | ~$0.02-0.04/sec | Дешёвая image-to-video, быстрая |

### Minimax / Hailuo

| Slug | Длительность | Цена ориент. | Сильная сторона |
|---|---|---|---|
| `minimax/video-01` | 6s (фикс) | ~$0.50/clip | Очень реалистичные лица для UGC |
| `minimax/hailuo-02` | 6/10s | ~$0.45-0.75/clip | Hailuo 2 — лучшая physics simulation |

### Google Veo (если доступно через Replicate)

| Slug | Длительность | Цена ориент. | Сильная сторона |
|---|---|---|---|
| `google/veo-3` | 5-8s | ~$0.50/sec | Премиум SOTA, есть audio |

## Как использовать новую модель (которой нет в списке)

1. Зайди на страницу модели на replicate.com
2. Возьми slug (формат `owner/name`)
3. Запусти:
   ```bash
   python -m scripts.generate_creative_videos \
     --workspace <path> \
     --model owner/new-model-name \
     --concept A
   ```
4. Если получится — модель работает с дефолтным маппингом (prompt, duration, aspect_ratio, seed_image как стандартные имена).
5. Если ошибка типа `unexpected input parameter` — посмотри на странице модели какие точно поля она ждёт, и добавь маппинг в `scripts/video_providers/replicate.py:MODEL_INPUT_SCHEMAS`.

## Версия модели vs slug

Replicate принимает 2 формата идентификатора:

**Slug (рекомендуется):** `owner/name` — всегда последняя версия. Удобно для тестирования.
```
--model kwaivgi/kling-v1.6-standard
```

**Version hash:** конкретная замороженная версия, не меняется со временем. Используй для production-стабильности.
```
--model kwaivgi/kling-v1.6-standard:abc123def456...
```

Hash берётся со страницы модели → «Use as production» или через API.

## Стратегия выбора модели под задачу

| Тип креатива | Рекомендуемые модели |
|---|---|
| Pain reframe (split-screen, без людей) | `kwaivgi/kling-v1.6-standard` (универсал) |
| UGC с реальным человеком | `minimax/hailuo-02` (лучшие лица) или `kwaivgi/kling-v2-master` |
| Product demo (UI скринкаст) | `bytedance/seedance-1-pro` (стабильное motion) |
| Брендовая абстрактная анимация | `bytedance/seedance-1-lite` (дёшево, для перебора вариантов) |
| Премиум финал | `google/veo-3` (если в бюджете) |

## A/B тестирование моделей

Наш CLI не умеет `--variants` — генерит один файл на концепцию/формат и молча пропускает его, если он уже существует (если не передан `--force`). Поэтому паттерн для сравнения моделей — перегенерировать один и тот же ролик с разными `--model`, каждый раз переименовывая результат перед следующим прогоном:

```bash
# Вариант 1: Kling
python -m scripts.generate_creative_videos \
  --workspace <path> --concept A \
  --model kwaivgi/kling-v1.6-standard
mv assets/videos/g1_A_16x9.mp4 assets/videos/g1_A_16x9_kling.mp4

# Вариант 2: Seedance Pro (--force обязателен, иначе скрипт увидит
# отсутствующий g1_A_16x9.mp4 и просто сгенерит его — это ОК, но если
# файл ещё остался от предыдущего прогона, --force его перезапишет)
python -m scripts.generate_creative_videos \
  --workspace <path> --concept A --force \
  --model bytedance/seedance-1-pro
mv assets/videos/g1_A_16x9.mp4 assets/videos/g1_A_16x9_seedance.mp4

# Сравни — какой больше нравится → переименуй победителя обратно
# в g1_A_16x9.mp4 (или пропиши путь вручную в combined_ad.videos
# в 08_creatives.json) перед заливкой на Шаге 10
```

## Сравнение стоимости (цена 5s ролика)

| Модель | Цена 5s |
|---|---|
| `wavespeedai/wan-2.1-i2v-720p` | $0.20 |
| `bytedance/seedance-1-lite` | $0.20 |
| `kwaivgi/kling-v1.6-standard` | $0.25 |
| `bytedance/seedance-1-pro` | $0.75 |
| `kwaivgi/kling-v1.6-pro` | $0.50 |
| `kwaivgi/kling-v2-master` | $1.40 |
| `google/veo-3` | $2.50 |

Цены ориентировочные на 2026 май — реальные смотри на странице модели.
Ролики длиннее 10 с текущая версия скилла не собирает (нет склейки сегментов) — см. references/video-generation.md → Ограничения.

## Расширение MODEL_INPUT_SCHEMAS

Если хочешь использовать модель с особыми параметрами, отредактируй `scripts/video_providers/replicate.py`:

```python
MODEL_INPUT_SCHEMAS = {
    ...
    "owner/new-model": {
        "prompt": "prompt",                       # как маппится prompt
        "duration": ("duration_sec", lambda d: d), # с трансформацией
        "aspect_ratio": "ratio",
        "seed_image": "init_image",
        "extra": {                                # дополнительные параметры
            "fps": 24,
            "quality": "hd",
        },
    },
}
```

Формат:
- Ключ → имя поля в модели Replicate
- Значение строкой → прямое соответствие
- Значение кортежем `(field_name, transform_fn)` → с преобразованием
- `extra` → словарь фиксированных параметров (всегда добавляется)
