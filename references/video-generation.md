# Яндекс.Директ — генерация видео через AI (Replicate)

`scripts/generate_creative_videos.py` генерит видеодополнение для комбинаторного
объявления (ЕПК) через Replicate — один провайдер, модель задаётся флагом
`--model <owner/name>`. Один ролик = один сегмент 5–60 секунд, без склейки.
Видео — опциональная часть Шага 8.5, детали по гейтам и лимитам Директа см.
`references/rsya-creatives.md`.

## Когда

- После картинок (`generate_creative_images.py`), до заливки на Шаге 10 через MCP.
- **Видео опционально** — если его нет, комбинаторное объявление заливается без
  `VideoExtensionIds`.
- По умолчанию — 1 ролик на группу (первая концепция из `visual_concepts`, либо
  выбранная через `--concept`), длительность 5 секунд. Практичный диапазон для
  РСЯ — 5–10 секунд: длиннее — дороже генерация и меньше шанс, что досмотрят до
  конца на баннерном месте.

## Провайдер

Только **Replicate**. Ключ:

```bash
python -m scripts.manage_credentials set replicate
```

или env `REPLICATE_API_TOKEN`. Без `--model` (и без dry-run) скрипт завершится
ошибкой — модель обязательна.

Выбор модели — по каталогу `references/replicate-models.md`: там список
проверенных slug'ов (Kling, Bytedance Seedance, Wan, Minimax/Hailuo, Google Veo)
с ориентирами длительности и цены за секунду/клип. Для старта — что-то
недорогое и стабильное вроде `kwaivgi/kling-v1.6-standard` (~$0.05/сек);
для премиум-результата — `google/veo-3` (~$0.50/сек), если бюджет позволяет.
Цены — ориентировочные с сайта Replicate, актуальные смотри на странице модели.

## Архитектура

```
scripts/
├── generate_creative_videos.py    ← главный CLI
├── video_prompt_templates.py       ← 3 типа сценариев (без текста в кадре)
└── video_providers/
    ├── __init__.py                 ← factory get_provider()
    ├── base.py                     ← BaseVideoProvider
    └── replicate.py                ← единственная реализация, MODEL_INPUT_SCHEMAS
```

В рабочей папке кампании:

```
direct-campaigns/<slug>/
└── assets/
    ├── videos/                     ← готовые ролики: g{N}_{CID}_{ASPECT}.mp4
    ├── video_prompts/               ← сохранённые промпты (для аудита)
    └── video_generation_log.json    ← лог последнего запуска
```

`{ASPECT}` — соотношение сторон с заменой `:` на `x` (например `16x9`).

## 3 типа видео-сценариев

Определяются автоматически по `type` visual-концепции (`detect_video_type()` в
`video_prompt_templates.py`), все — без текста и логотипов в кадре (текст
добавляет само объявление):

| Тип видео | Из какого типа картиночной концепции | Суть сценария |
|---|---|---|
| `pain_reframe` | `pain_split` | «До/после»: стрессовая сцена → решение с продуктом |
| `product_showcase` | `product_offer`, `social_proof`, `ui_mockup` | Продукт/услуга крупным планом, плавная камера |
| `brand_motion` | `abstract_brand` | Абстрактная брендовая анимация, геометрия в цветах бренда |

## Workflow

### Шаг 1. Dry-run (бесплатно)

```bash
python -m scripts.generate_creative_videos --workspace <path> --dry-run
```

Промпты сохраняются в `assets/video_prompts/<name>.txt` — прочитай, оцени
соответствие сценарию, прежде чем платить за генерацию.

### Шаг 2. Выбор модели и ключ

```bash
python -m scripts.manage_credentials list
```

Если `replicate` не в списке — сохрани ключ (см. «Провайдер» выше). Модель
выбирается по `references/replicate-models.md`.

### Шаг 3. Тест на одной концепции

```bash
python -m scripts.generate_creative_videos \
  --workspace <path> --model kwaivgi/kling-v1.6-standard --concept A
```

Дефолт — `--duration 5 --aspect 16:9`. Длительность можно менять в пределах
5–60 секунд (`--duration`), соотношение — `--aspect 16:9|1:1|9:16`.

### Шаг 4. Другие концепции (по желанию)

```bash
python -m scripts.generate_creative_videos \
  --workspace <path> --model kwaivgi/kling-v1.6-standard --concept B
```

Каждый вызов с новым `--concept` добавляет ролик в `combined_ad.videos`
(до 6 видео на объявление — лимит ResponsiveAd).

### Шаг 5. A/B сравнение моделей

Перегенерировать тот же ролик другой моделью и сравнить:

```bash
# Вариант 1
python -m scripts.generate_creative_videos \
  --workspace <path> --concept A --model kwaivgi/kling-v1.6-standard
mv assets/videos/g1_A_16x9.mp4 assets/videos/g1_A_16x9_kling.mp4

# Вариант 2 (--force перезаписывает файл, который скрипт иначе бы пропустил)
python -m scripts.generate_creative_videos \
  --workspace <path> --concept A --model bytedance/seedance-1-pro --force
mv assets/videos/g1_A_16x9.mp4 assets/videos/g1_A_16x9_seedance.mp4

# Сравни → переименуй победителя обратно в g1_A_16x9.mp4 перед заливкой
```

### Шаг 6. Валидация

```bash
python -m scripts.validate_assets --workspace <path>
```

Проверяет расширение файла и вес каждого ролика в `assets/videos/`
(длительность 5–60 с проверяется на стороне API Директа при загрузке).

## Требования Директа и цепочка заливки

- Длительность: 5–60 секунд.
- Вес: ≤100 МБ.
- Формат: MP4, WebM, MOV, QT, FLV, AVI.
- Соотношение по умолчанию в этом скилле — **16:9** (можно `1:1` / `9:16`
  через `--aspect`).

Заливка видео в кампанию — на Шаге 10 через MCP (и связанные API-сервисы
`AdVideos` / `Creatives`), для каждого файла из `combined_ad.videos`:

1. `AdVideos.add` — загружает файл, получает `VideoId`.
2. Поллинг статуса видео (`AdVideos.get`) до `READY` (таймаут 600 c, интервал 15 c).
3. `Creatives.add` с `VideoExtensionCreative.VideoId` — получает `CreativeId`.
4. `CreativeId` кладётся в `ResponsiveAd.VideoExtensionIds` при создании объявления.

Если видео в `assets/videos/` нет — объявление уходит без `VideoExtensionIds`.

## Ограничения этой версии

- **Без склейки сегментов.** Каждый провайдер отдаёт один ролик до той
  длительности, которую попросили в `--duration` (в рамках возможностей модели);
  автоматической склейки нескольких сегментов в более длинное видео (как для
  роликов >10 секунд у некоторых моделей) в этой версии нет — генерируй сразу
  нужную длину через `--duration`, если модель это поддерживает, либо бери
  готовый 5–10-секундный ролик.
- **Без UGC с реальными людьми.** Шаблоны промптов (`video_prompt_templates.py`)
  явно исключают лица людей и текст в кадре — для UGC с живыми людьми этот
  инструмент не подходит, нужна реальная съёмка.
- **Один ролик на группу по умолчанию.** Если нужно несколько роликов —
  вызывай скрипт повторно с разными `--concept`.

## Чек-лист готовности к запуску

- [ ] Ключ Replicate сохранён (`python -m scripts.manage_credentials set replicate`
      или env `REPLICATE_API_TOKEN`)
- [ ] Модель выбрана по `references/replicate-models.md`
- [ ] Сделан `--dry-run` — промпты в `assets/video_prompts/` выглядят разумно
- [ ] Сделан тест на 1 концепции — результат устраивает
- [ ] `python -m scripts.validate_assets --workspace <path>` — 0 ошибок по видео
- [ ] Ручной ревью ролика (нет текста/лиц, соответствует сценарию, 5–60 с, ≤100 МБ)
