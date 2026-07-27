# ЕПК + комбинаторное объявление: двойная модель РК — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать скиллу `yandex-direct-create-pipeline` две ветки структуры/объявлений — ЕПК с комбинаторным объявлением (рекомендованная) и классика — с гейтом выбора «плюсы/минусы» на Шаге 5, и снять жёсткий потолок на число кампаний.

**Architecture:** Изменения почти целиком в markdown-референсах и `SKILL.md` (правит поведение агента) плюс один Python-скрипт `generate_ads_xlsx.py` с юнит-тестами и новый пример JSON-схемы. Выбор модели хранится в `_state.json` как `ad_model` и ветвит Шаги 5, 8, 8.5, 9, 10. Классическая ветка сохраняется без изменений поведения — она просто становится одним из двух путей.

**Tech Stack:** Markdown (референсы скилла), Python 3.9+ (stdlib + опциональный `openpyxl`), pytest для тестов скрипта.

## Global Constraints

- **Комбинаторное объявление (ЕПК), лимиты:** до **7 заголовков** (каждый ≤56 симв., одно слово ≤22), до **3 текстов** (каждый ≤81 симв., одно слово ≤23), до **5 изображений**, до **6 видео**. Рекомендуется 2 коротких заголовка ≤35 симв. Крутится на Поиске, в РСЯ, Товарной галерее и Картах.
- **Значения `ad_model`:** ровно `"epk_combined"` или `"classic"`. Строки — именно эти, дословно.
- **Термин:** используем «комбинаторное объявление» (официальный термин Яндекса); в пользовательских формулировках можно пояснять «(комбинированное)».
- **Ограничение MCP:** обёртка умеет только `TextCampaign` + классический `TextAd`. Комбинаторное объявление через `ads_add` НЕ создаётся — заливается руками (Директ Коммандер/UI) или через passthrough `yandex_direct_api_call` (в коде MCP пока нет). Скилл не делает вид, что зальёт его автоматически; всё недоделанное — в `10_launch_log.md`.
- **Классическую ветку не меняем по сути** — только изолируем под `ad_model = "classic"`.
- **Весь текст — на русском**, в тон существующим референсам.
- **Python:** `openpyxl` остаётся опциональным (CSV-фолбек). Тесты — pytest, запуск из корня репозитория.
- **Официальные источники лимитов** (для сверки в тексте):
  - https://yandex.ru/support/direct/ru/unified-performance-campaign/about
  - https://yandex.ru/support/direct/ru/moderation/technical-restrictions

---

### Task 1: Лимиты комбинаторного объявления в `yandex-direct-specs.md`

**Files:**
- Modify: `references/yandex-direct-specs.md` (вставить новый раздел после блока «Изображения и видео», перед «## Ключевые слова — операторы соответствия»)

**Interfaces:**
- Produces: раздел «## Комбинаторное объявление (ЕПК)» — единый источник числовых лимитов, на который ссылаются `ad-copywriting.md`, `SKILL.md` и `generate_ads_xlsx.py`.

- [ ] **Step 1: Вставить раздел про комбинаторное объявление**

Найти в `references/yandex-direct-specs.md` строку-заголовок:

```
## Ключевые слова — операторы соответствия
```

Вставить ПЕРЕД ней следующий блок:

```markdown
## Комбинаторное объявление (ЕПК) — новый формат

Используется в **Единой перфоманс-кампании (ЕПК)** при `ad_model = "epk_combined"`. Одно объявление содержит несколько вариантов заголовков, текстов, картинок и видео; Директ сам собирает из них баннеры и крутит на Поиске, в РСЯ, Товарной галерее и Картах.

| Элемент | Лимит количества | Посимвольный лимит |
|---|---|---|
| Заголовки | до **7** | каждый ≤ 56 символов (одно слово ≤ 22) |
| Тексты | до **3** | каждый ≤ 81 символ (одно слово ≤ 23) |
| Изображения | до **5** | требования как для РСЯ-картинок (см. ниже) |
| Видео | до **6** | 10-60 сек, MP4 (см. ниже) |

- **Рекомендация:** хотя бы 2 заголовка сделать короткими (≤ 35 символов) — под мобильные и компактные площадки.
- **Обязательное вхождение ключа** хотя бы в один заголовок.
- Быстрые ссылки, уточнения, отображаемая ссылка — те же лимиты, что у ТГО (см. выше).
- Источник правды по лимитам: https://yandex.ru/support/direct/ru/unified-performance-campaign/about и https://yandex.ru/support/direct/ru/moderation/technical-restrictions

> ⚠️ **Заливка:** текущий MCP создаёт только классический `TextAd`, комбинаторное объявление через `ads_add` не создаётся. Его заливают руками (Директ Коммандер/UI) или через passthrough-API. См. Шаг 10 в `SKILL.md`.
```

- [ ] **Step 2: Проверить вставку**

Run: `grep -n "Комбинаторное объявление (ЕПК)" references/yandex-direct-specs.md`
Expected: одна строка с номером (заголовок раздела найден).

- [ ] **Step 3: Commit**

```bash
git add references/yandex-direct-specs.md
git commit -m "specs: add ЕПК combinatorial ad limits (7 titles/3 texts/5 img/6 video)"
```

---

### Task 2: Ветка ЕПК и снятие потолка в `campaign-structure.md`

**Files:**
- Modify: `references/campaign-structure.md` (добавить раздел про модели; смягчить потолок в разделе «Особые случаи»)

**Interfaces:**
- Consumes: понятие `ad_model` (см. Task 8).
- Produces: раздел «## Две модели структуры (ЕПК vs классика)» и правило «1 РК = 1 угол = 1 комбинаторное объявление» для ЕПК-ветки; мягкая подсказка вместо жёсткого потолка.

- [ ] **Step 1: Добавить раздел про две модели**

Найти в `references/campaign-structure.md` строку:

```
## Жёсткие правила агентства
```

Вставить ПЕРЕД ней блок:

```markdown
## Две модели структуры (ЕПК vs классика)

На Шаге 5 маркетолог выбирает модель (гейт в `SKILL.md`). Результат — в `_state.json` поле `ad_model`.

### Модель `epk_combined` (рекомендованная)

- **1 угол / сегмент / лендинг → 1 РК.** Внутри — **1 группа, 1 комбинаторное объявление** (несколько заголовков/текстов/картинок/видео — лимиты в `yandex-direct-specs.md`).
- **Поиск и РСЯ НЕ разделяются на отдельные кампании** — одна РК обслуживает оба размещения (плюс Галерею и Карты).
- Ключи Шага 4 идут в эту же РК: НЧ/СЧ/ВЧ как ключевые фразы + автотаргетинг для сети. **CSV Шага 4 не меняются** — меняется только сборка структуры здесь.
- Разделы «Жёсткие правила агентства» 1 (Поиск vs РСЯ раздельно) и 6 (РСЯ отдельной кампанией) в этой модели **не применяются**. Углы/сегменты (Премиум, Срочно, Бренд, B2B) по-прежнему разносятся по отдельным РК — правила 2, 4, 5 действуют.
- В `05_campaign_structure.json` каждая кампания получает `"combined": true`, а корень — `"ad_model": "epk_combined"`.

### Модель `classic`

- Всё, что описано ниже в «Жёсткие правила агентства» и «Группы внутри кампании», применяется как есть (Поиск/РСЯ раздельно, тест-матрица 3-5 объявлений).
- В `05_campaign_structure.json` корень получает `"ad_model": "classic"`.
```

- [ ] **Step 2: Смягчить потолок на число кампаний**

Найти блок:

```markdown
### Слишком много кампаний (>6 на Поиске)

Если получилось 7+ Поиск-кампаний — скорее всего, сужающие слов слишком много или они слишком близкие. Маркетологу: «получилось 7 кампаний, это много — обычно 2-4. Возможно, угла 2 (+премиум и +авторский слишком близки)? Объединяем?»
```

Заменить на:

```markdown
### Много кампаний — мягкая подсказка (потолка нет)

**Жёсткого лимита на число кампаний в запуске нет** — их столько, сколько углов / сегментов / лендингов. Если кампаний много и близкие по смыслу — это не запрет, а повод переспросить: «получилось {N} кампаний; пара углов близки (+премиум и +авторский). Оставляем раздельно или объединяем?» Маркетолог решает; при отказе объединять — оставляем как есть.
```

- [ ] **Step 3: Проверить обе правки**

Run: `grep -n "epk_combined\|потолка нет" references/campaign-structure.md`
Expected: минимум две строки — раздел про модели и смягчённая подсказка. Прежней формулировки «это много — обычно 2-4» быть не должно (`grep -n "обычно 2-4" references/campaign-structure.md` → пусто).

- [ ] **Step 4: Commit**

```bash
git add references/campaign-structure.md
git commit -m "campaign-structure: add ЕПК model branch, drop hard campaign cap"
```

---

### Task 3: Правила копирайтинга комбинаторного объявления в `ad-copywriting.md`

**Files:**
- Modify: `references/ad-copywriting.md` (добавить раздел про комбинаторное объявление; отметить, что тест-матрица — только для классики)

**Interfaces:**
- Consumes: лимиты из `yandex-direct-specs.md` (Task 1).
- Produces: раздел «## Комбинаторное объявление (ветка ЕПК)» и оговорку у «Тестовой матрицы».

- [ ] **Step 1: Пометить тест-матрицу как классическую**

Найти:

```markdown
## Тестовая матрица: 3 варианта на группу

Минимум 3 объявления на группу, различие в одной оси (заголовок vs текст vs CTA).
```

Заменить на:

```markdown
## Тестовая матрица: 3 варианта на группу (только `ad_model = classic`)

Минимум 3 объявления на группу, различие в одной оси (заголовок vs текст vs CTA).

> В ветке `ad_model = "epk_combined"` тест-матрицы нет: мультивариантность живёт внутри одного комбинаторного объявления (см. раздел ниже).
```

- [ ] **Step 2: Добавить раздел про комбинаторное объявление**

Найти строку-заголовок:

```
## Поиск vs РСЯ
```

Вставить ПЕРЕД ней блок:

```markdown
## Комбинаторное объявление (ветка ЕПК)

Если `ad_model = "epk_combined"` — на РК готовим **одно комбинаторное объявление** вместо тест-матрицы. Лимиты — в `yandex-direct-specs.md` (до 7 заголовков ≤56, до 3 текстов ≤81, до 5 картинок, до 6 видео).

Как наполнять:

- **Заголовки (3-7 штук):** разные углы одной идеи — триггер из запроса, главное УТП, цифра/цена, снятие возражения, короткий бренд-заголовок. Минимум 2 сделать короткими (≤35 символов). Обязательное вхождение ключа хотя бы в один заголовок.
- **Тексты (2-3 штуки):** разные акценты — выгода+CTA, снятие возражения+CTA, соц.доказательство+CTA. Каждый самодостаточен: Директ показывает их вперемешку с заголовками.
- **Картинки/видео:** из ассетов брифа (см. `rsya-creatives.md`). Нет ассетов — объявление заливается без них, фиксируем в `08_5_rsya_creatives_TODO.md`.
- **Быстрые ссылки, уточнения, отображаемая ссылка** — как у ТГО.

Правила модерации и закона о рекламе (ниже) действуют для каждого заголовка и текста.
```

- [ ] **Step 3: Обновить чек-лист под обе ветки**

Найти последний пункт чек-листа:

```
- [ ] На группу — минимум 3 разных объявления
```

Заменить на:

```
- [ ] classic: на группу — минимум 3 разных объявления; epk_combined: одно комбинаторное объявление (3-7 заголовков, 2-3 текста, ≥2 заголовка ≤35 симв.)
```

- [ ] **Step 4: Проверить правки**

Run: `grep -n "Комбинаторное объявление (ветка ЕПК)\|только .ad_model = classic" references/ad-copywriting.md`
Expected: две строки.

- [ ] **Step 5: Commit**

```bash
git add references/ad-copywriting.md
git commit -m "ad-copywriting: add combinatorial ad rules for ЕПК branch"
```

---

### Task 4: Врезка «стратегия для ЕПК» в `bidding-strategy.md`

**Files:**
- Modify: `references/bidding-strategy.md` (добавить короткую врезку про единую кампанию ЕПК)

**Interfaces:**
- Consumes: `ad_model` из `_state.json` / `05_campaign_structure.json`.
- Produces: подраздел «### ЕПК (`ad_model = epk_combined`)» в «Особые случаи».

- [ ] **Step 1: Добавить подраздел в «Особые случаи»**

Найти строку:

```
## Особые случаи
```

Вставить СРАЗУ ПОСЛЕ неё (перед «### Один кампания всего»):

```markdown
### ЕПК (`ad_model = epk_combined`)

В ЕПК Поиск и РСЯ живут в **одной** кампании, поэтому раздельных Поиск/РСЯ-стратегий нет — **одна стратегия на РК**. Стартовая логика та же по духу: не начинать с «Оптимизации конверсий». Практика для ЕПК:

- **Старт:** «Максимум кликов» с недельным бюджетом и лимитом CPC (или пакетная стратегия аккаунта, если ведёте несколько ЕПК).
- **После накопления 10+ конверсий/нед стабильно** — «Оплата за конверсию» / «Максимум конверсий» с CPA-лимитом по цели из `07_metrika_goals.json`.
- Отдельной «РСЯ нельзя на ручных» оговорки не требуется — сеть внутри той же кампании ведёт автостратегия.
- В `09_bidding_strategy.json` для ЕПК-кампаний поле `"channel": "epk"`.

Всё остальное (триггеры фаз, коллтрекинг как gate для Фазы 3, ниши) применяется как для Поиска.
```

- [ ] **Step 2: Проверить вставку**

Run: `grep -n "ЕПК (.ad_model = epk_combined.)" references/bidding-strategy.md`
Expected: одна строка.

- [ ] **Step 3: Commit**

```bash
git add references/bidding-strategy.md
git commit -m "bidding-strategy: add single-strategy note for ЕПК campaigns"
```

---

### Task 5: Картинки/видео как часть комбинаторного объявления в `rsya-creatives.md`

**Files:**
- Modify: `references/rsya-creatives.md` (добавить оговорку про ЕПК в шапку)

**Interfaces:**
- Produces: врезка вверху файла, связывающая ассеты с комбинаторным объявлением при `ad_model = epk_combined`.

- [ ] **Step 1: Добавить врезку про ЕПК в начало файла**

Найти самую первую строку файла:

```
# РСЯ-визуалы — заглушка с ТЗ дизайнеру
```

Вставить СРАЗУ ПОСЛЕ строки-заголовка (перед строкой «⚠️ **Этот этап...**») блок:

```markdown

> 🧩 **В ветке `ad_model = "epk_combined"`** картинки и видео — это ассеты **комбинаторного объявления** (до 5 изображений, до 6 видео на объявление), а не отдельная РСЯ-кампания. Собранные здесь форматы и ТЗ дизайнеру используются те же; разница в том, что ассеты прикладываются к единственному объявлению РК, а не к отдельной РСЯ-РК. Если ассетов нет — объявление заливается без них, TODO остаётся. В ветке `classic` всё работает как ниже (отдельная РСЯ-кампания).
```

- [ ] **Step 2: Проверить вставку**

Run: `grep -n "В ветке .ad_model = .epk_combined." references/rsya-creatives.md`
Expected: одна строка.

- [ ] **Step 3: Commit**

```bash
git add references/rsya-creatives.md
git commit -m "rsya-creatives: note assets feed the ЕПК combinatorial ad"
```

---

### Task 6: Пример JSON-схемы комбинаторного объявления

**Files:**
- Create: `assets/creatives_schema_combined_example.json`

**Interfaces:**
- Produces: файл-пример формы `creatives.json` при `ad_model = "epk_combined"` — читается людьми и служит фикстурой-ориентиром для скрипта (Task 7). Ключевые поля: корень `"ad_model": "epk_combined"`; в каждой группе объект `"combined_ad"` с `titles[]`, `texts[]`, `display_url_path`, `images[]`, `videos[]`, `sitelinks[]`, `callouts[]`.

- [ ] **Step 1: Создать файл-пример**

Создать `assets/creatives_schema_combined_example.json` с содержимым:

```json
{
  "_schema_note": "Пример creatives.json для ЕПК (ad_model=epk_combined). Одна группа = одно комбинаторное объявление в объекте combined_ad. generate_ads_xlsx читает этот формат при ad_model=epk_combined. Лимиты: до 7 заголовков ≤56, до 3 текстов ≤81, до 5 изображений, до 6 видео.",
  "ad_model": "epk_combined",
  "campaign_name": "ЕПК — AiSMM Pro — Фрилансер — RU",
  "default_url": "https://aismm.pro/?utm_source=yandex&utm_medium=cpc&utm_campaign=aismm-epk&utm_term={keyword}",
  "negative_keywords": ["бесплатно", "торрент", "скачать", "вакансия", "работа"],
  "groups": [
    {
      "name": "SMM-фрилансер — автогенерация контента",
      "url": "https://aismm.pro/dlya-frilancera",
      "keywords": [
        "\"автоматизация смм\"",
        "\"нейросеть для смм\"",
        "\"генерация постов\"",
        "\"ai контент для соцсетей\""
      ],
      "negative_keywords": ["обучение", "курс", "школа"],
      "combined_ad": {
        "titles": [
          "Сервис для контента в соцсетях с ИИ",
          "Автогенерация постов — неделя за вечер",
          "SMM на ИИ от 990 ₽",
          "Триал 7 дней без карты",
          "Посты и видео под стиль клиента"
        ],
        "texts": [
          "Генерация постов и видео под стиль клиента. Триал 7 дней без карты. Начать.",
          "Тариф соло от 990 ₽. Видео, статичные посты, заголовки. Попробовать.",
          "Берите больше клиентов: контент готов за вечер. Отмена в 1 клик."
        ],
        "display_url_path": "dlya-frilancera",
        "images": ["assets/img/epk_1080x1080.jpg", "assets/img/epk_1080x607.jpg"],
        "videos": [],
        "sitelinks": [
          {"title": "Тарифы", "description": "От 990 ₽/мес для соло", "url": "https://aismm.pro/pricing"},
          {"title": "Демо генерации", "description": "Без регистрации, сейчас", "url": "https://aismm.pro/demo"},
          {"title": "Кейсы фрилансеров", "description": "Как берут больше клиентов", "url": "https://aismm.pro/cases"},
          {"title": "FAQ", "description": "Частые вопросы", "url": "https://aismm.pro/faq"}
        ],
        "callouts": ["Без карты", "Триал 7 дней", "Поддержка 24/7", "Отмена в 1 клик"]
      }
    }
  ]
}
```

- [ ] **Step 2: Проверить валидность JSON**

Run: `python -c "import json; json.load(open('assets/creatives_schema_combined_example.json', encoding='utf-8')); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add assets/creatives_schema_combined_example.json
git commit -m "assets: add combinatorial ad (ЕПК) creatives.json example"
```

---

### Task 7: Поддержка комбинаторного объявления в `generate_ads_xlsx.py` (TDD)

**Files:**
- Modify: `scripts/generate_ads_xlsx.py`
- Create: `tests/test_generate_ads_xlsx.py`

**Interfaces:**
- Consumes: формат из Task 6 (`creatives["ad_model"]`, `group["combined_ad"]`).
- Produces:
  - `COMBINED_LIMITS: dict` — числовые и посимвольные лимиты.
  - `COMBINED_HEADERS: list[str]` — 32 колонки.
  - `validate_combined_ad(ad: dict, group_name: str) -> list[str]`
  - `assemble_combined_ad_rows(creatives: dict) -> tuple[list[list], list[str]]`
  - `select_assembler(creatives: dict) -> tuple[list[list], list[str], list[str]]` — возвращает `(rows, warnings, headers)` по `ad_model`.
  - Изменённые сигнатуры: `write_xlsx(ad_rows, keyword_rows, output_dir, headers)` и `write_csv(ad_rows, keyword_rows, output_dir, headers)` (добавлен параметр `headers`).

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_generate_ads_xlsx.py`:

```python
from scripts.generate_ads_xlsx import (
    COMBINED_HEADERS,
    validate_combined_ad,
    assemble_combined_ad_rows,
    select_assembler,
    HEADERS,
)


def _ok_combined_ad():
    return {
        "titles": ["Заголовок один", "Короткий", "Ещё вариант"],
        "texts": ["Текст выгоды и призыв к действию.", "Второй текст с другим акцентом."],
        "display_url_path": "path",
        "images": ["a.jpg", "b.jpg"],
        "videos": [],
        "sitelinks": [{"title": "Цены", "description": "от 990", "url": "u"}],
        "callouts": ["Без карты"],
    }


def test_validate_combined_ad_ok():
    assert validate_combined_ad(_ok_combined_ad(), "G") == []


def test_validate_combined_ad_flags_too_many_titles():
    ad = _ok_combined_ad()
    ad["titles"] = [f"t{i}" for i in range(8)]  # 8 > 7
    warns = validate_combined_ad(ad, "G")
    assert any("заголовк" in w and "> 7" in w for w in warns)


def test_validate_combined_ad_flags_too_many_texts():
    ad = _ok_combined_ad()
    ad["texts"] = ["a", "b", "c", "d"]  # 4 > 3
    warns = validate_combined_ad(ad, "G")
    assert any("текст" in w and "> 3" in w for w in warns)


def test_validate_combined_ad_flags_long_title():
    ad = _ok_combined_ad()
    ad["titles"] = ["Я" * 57]  # 57 > 56
    warns = validate_combined_ad(ad, "G")
    assert any("заголовок 1" in w and "> 56" in w for w in warns)


def test_validate_combined_ad_flags_no_titles():
    ad = _ok_combined_ad()
    ad["titles"] = []
    warns = validate_combined_ad(ad, "G")
    assert any("нет ни одного заголовка" in w for w in warns)


def test_assemble_combined_ad_rows_shape_and_placement():
    creatives = {
        "ad_model": "epk_combined",
        "campaign_name": "C",
        "groups": [{"name": "G", "url": "https://x", "combined_ad": _ok_combined_ad()}],
    }
    rows, warnings = assemble_combined_ad_rows(creatives)
    assert warnings == []
    assert len(rows) == 1
    row = rows[0]
    assert len(row) == len(COMBINED_HEADERS) == 32
    assert row[0] == "C"          # Campaign
    assert row[1] == "G"          # Group
    assert row[2] == "Заголовок один"  # Title1
    assert row[8] == ""           # Title7 пусто (было 3 заголовка)
    assert row[9] == "Текст выгоды и призыв к действию."  # Text1
    assert row[14] == "a.jpg | b.jpg"  # Images (join через " | ")


def test_select_assembler_picks_combined():
    creatives = {
        "ad_model": "epk_combined",
        "campaign_name": "C",
        "groups": [{"name": "G", "url": "https://x", "combined_ad": _ok_combined_ad()}],
    }
    rows, warnings, headers = select_assembler(creatives)
    assert headers == COMBINED_HEADERS
    assert len(rows) == 1


def test_select_assembler_defaults_to_classic():
    creatives = {
        "campaign_name": "C",
        "groups": [{"name": "G", "url": "https://x", "ads": [{"title": "t", "text": "x"}]}],
    }
    rows, warnings, headers = select_assembler(creatives)
    assert headers == HEADERS
    assert len(rows) == 1
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `python -m pytest tests/test_generate_ads_xlsx.py -q`
Expected: FAIL / ImportError — `COMBINED_HEADERS`, `validate_combined_ad`, `assemble_combined_ad_rows`, `select_assembler` ещё не существуют.
(Если pytest не установлен: `pip install pytest` и повторить.)

- [ ] **Step 3: Добавить лимиты и заголовки комбинаторного объявления**

В `scripts/generate_ads_xlsx.py` СРАЗУ ПОСЛЕ блока `HEADERS = [ ... ]` (после строки `]`, закрывающей `HEADERS`) добавить:

```python
COMBINED_LIMITS = {
    "titles_max": 7,
    "texts_max": 3,
    "images_max": 5,
    "videos_max": 6,
    "title": 56,
    "text": 81,
    "display_url_path": 20,
    "sitelink_title": 30,
    "sitelink_description": 60,
    "callout": 25,
}


COMBINED_HEADERS = [
    "Campaign", "Group",
    "Title1", "Title2", "Title3", "Title4", "Title5", "Title6", "Title7",
    "Text1", "Text2", "Text3",
    "Href", "DisplayUrlPath", "Images", "Videos",
    "Sitelink1_Title", "Sitelink1_Desc", "Sitelink1_Url",
    "Sitelink2_Title", "Sitelink2_Desc", "Sitelink2_Url",
    "Sitelink3_Title", "Sitelink3_Desc", "Sitelink3_Url",
    "Sitelink4_Title", "Sitelink4_Desc", "Sitelink4_Url",
    "Callout1", "Callout2", "Callout3", "Callout4",
]
```

- [ ] **Step 4: Добавить `validate_combined_ad` и `assemble_combined_ad_rows`**

В `scripts/generate_ads_xlsx.py` СРАЗУ ПОСЛЕ функции `assemble_ad_rows` (после её `return rows, all_warnings`) добавить:

```python
def validate_combined_ad(ad: dict, group_name: str) -> list[str]:
    warnings = []
    titles = ad.get("titles", [])
    texts = ad.get("texts", [])
    images = ad.get("images", [])
    videos = ad.get("videos", [])

    if not titles:
        warnings.append(f"[{group_name}] нет ни одного заголовка")
    if len(titles) > COMBINED_LIMITS["titles_max"]:
        warnings.append(f"[{group_name}] заголовков {len(titles)} > {COMBINED_LIMITS['titles_max']}")
    if len(texts) > COMBINED_LIMITS["texts_max"]:
        warnings.append(f"[{group_name}] текстов {len(texts)} > {COMBINED_LIMITS['texts_max']}")
    if len(images) > COMBINED_LIMITS["images_max"]:
        warnings.append(f"[{group_name}] изображений {len(images)} > {COMBINED_LIMITS['images_max']}")
    if len(videos) > COMBINED_LIMITS["videos_max"]:
        warnings.append(f"[{group_name}] видео {len(videos)} > {COMBINED_LIMITS['videos_max']}")

    for i, t in enumerate(titles, 1):
        if len(t) > COMBINED_LIMITS["title"]:
            warnings.append(f"[{group_name}] заголовок {i}={t!r} > {COMBINED_LIMITS['title']} ({len(t)} симв)")
    for i, t in enumerate(texts, 1):
        if len(t) > COMBINED_LIMITS["text"]:
            warnings.append(f"[{group_name}] текст {i}={t!r} > {COMBINED_LIMITS['text']} ({len(t)} симв)")

    if ad.get("display_url_path") and len(ad["display_url_path"]) > COMBINED_LIMITS["display_url_path"]:
        warnings.append(
            f"[{group_name}] display_url_path={ad['display_url_path']!r} > {COMBINED_LIMITS['display_url_path']}"
        )
    for i, sl in enumerate(ad.get("sitelinks", []), 1):
        if len(sl.get("title", "")) > COMBINED_LIMITS["sitelink_title"]:
            warnings.append(f"[{group_name}] sitelink{i}.title={sl['title']!r} длиннее {COMBINED_LIMITS['sitelink_title']}")
        if len(sl.get("description", "")) > COMBINED_LIMITS["sitelink_description"]:
            warnings.append(f"[{group_name}] sitelink{i}.description={sl['description']!r} длиннее {COMBINED_LIMITS['sitelink_description']}")
    for i, callout in enumerate(ad.get("callouts", []), 1):
        if len(callout) > COMBINED_LIMITS["callout"]:
            warnings.append(f"[{group_name}] callout{i}={callout!r} длиннее {COMBINED_LIMITS['callout']}")
    return warnings


def assemble_combined_ad_rows(creatives: dict) -> tuple[list[list], list[str]]:
    rows: list[list] = []
    all_warnings: list[str] = []
    campaign_name = creatives.get("campaign_name", "")
    default_url = creatives.get("default_url", "")

    for group in creatives.get("groups", []):
        ad = group.get("combined_ad")
        if not ad:
            continue
        all_warnings.extend(validate_combined_ad(ad, group["name"]))
        titles = ad.get("titles", [])[:COMBINED_LIMITS["titles_max"]]
        texts = ad.get("texts", [])[:COMBINED_LIMITS["texts_max"]]

        row = [campaign_name, group["name"]]
        for i in range(COMBINED_LIMITS["titles_max"]):
            row.append(titles[i] if i < len(titles) else "")
        for i in range(COMBINED_LIMITS["texts_max"]):
            row.append(texts[i] if i < len(texts) else "")
        row.append(ad.get("href") or group.get("url") or default_url)
        row.append(ad.get("display_url_path", ""))
        row.append(" | ".join(ad.get("images", [])))
        row.append(" | ".join(ad.get("videos", [])))

        sitelinks = ad.get("sitelinks", [])[:4]
        for i in range(4):
            if i < len(sitelinks):
                row.extend([
                    sitelinks[i].get("title", ""),
                    sitelinks[i].get("description", ""),
                    sitelinks[i].get("url", ""),
                ])
            else:
                row.extend(["", "", ""])
        callouts = ad.get("callouts", [])[:4]
        for i in range(4):
            row.append(callouts[i] if i < len(callouts) else "")
        rows.append(row)
    return rows, all_warnings


def select_assembler(creatives: dict) -> tuple[list[list], list[str], list[str]]:
    if creatives.get("ad_model") == "epk_combined":
        rows, warnings = assemble_combined_ad_rows(creatives)
        return rows, warnings, COMBINED_HEADERS
    rows, warnings = assemble_ad_rows(creatives)
    return rows, warnings, HEADERS
```

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

Run: `python -m pytest tests/test_generate_ads_xlsx.py -q`
Expected: PASS (все тесты зелёные).

- [ ] **Step 6: Прокинуть `headers` в запись файлов и `main`**

В `write_xlsx` заменить сигнатуру и обе строки записи заголовка. Найти:

```python
def write_xlsx(ad_rows: list[list], keyword_rows: list[list], output_dir: Path) -> tuple[Path, Path]:
    import openpyxl

    output_dir.mkdir(parents=True, exist_ok=True)

    ads_path = output_dir / "ads.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ads"
    ws.append(HEADERS)
```

Заменить на:

```python
def write_xlsx(ad_rows: list[list], keyword_rows: list[list], output_dir: Path, headers: list[str]) -> tuple[Path, Path]:
    import openpyxl

    output_dir.mkdir(parents=True, exist_ok=True)

    ads_path = output_dir / "ads.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ads"
    ws.append(headers)
```

В `write_csv` найти:

```python
def write_csv(ad_rows: list[list], keyword_rows: list[list], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    ads_path = output_dir / "ads.csv"
    with ads_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(HEADERS)
```

Заменить на:

```python
def write_csv(ad_rows: list[list], keyword_rows: list[list], output_dir: Path, headers: list[str]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    ads_path = output_dir / "ads.csv"
    with ads_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
```

В `main` найти:

```python
    creatives = json.loads(creatives_json.read_text(encoding="utf-8"))
    ad_rows, warnings = assemble_ad_rows(creatives)
    keyword_rows = assemble_keyword_rows(creatives)
```

Заменить на:

```python
    creatives = json.loads(creatives_json.read_text(encoding="utf-8"))
    ad_rows, warnings, headers = select_assembler(creatives)
    keyword_rows = assemble_keyword_rows(creatives)
```

В `main` найти:

```python
    if chosen_format == "xlsx":
        try:
            ads_path, keywords_path = write_xlsx(ad_rows, keyword_rows, output_dir)
        except ImportError:
            raise SystemExit(
                "openpyxl недоступен. Установи: pip install openpyxl --break-system-packages "
                "ИЛИ запусти скрипт с --format csv"
            )
    else:
        ads_path, keywords_path = write_csv(ad_rows, keyword_rows, output_dir)
```

Заменить на:

```python
    if chosen_format == "xlsx":
        try:
            ads_path, keywords_path = write_xlsx(ad_rows, keyword_rows, output_dir, headers)
        except ImportError:
            raise SystemExit(
                "openpyxl недоступен. Установи: pip install openpyxl --break-system-packages "
                "ИЛИ запусти скрипт с --format csv"
            )
    else:
        ads_path, keywords_path = write_csv(ad_rows, keyword_rows, output_dir, headers)
```

- [ ] **Step 7: Прогнать скрипт end-to-end на примере ЕПК (CSV)**

Run:
```bash
python -m scripts.generate_ads_xlsx --workspace assets --creatives-json assets/creatives_schema_combined_example.json --output-dir "$TMPDIR/epk_out" --format csv
```
(на Windows PowerShell вместо `$TMPDIR/epk_out` используйте `$env:TEMP\epk_out`)
Expected: печатает `Формат: csv`, пути к `ads.csv`/`keywords.csv`/`warnings.txt`, и `OK — все объявления и поля в пределах лимитов Директа.` Первая строка `ads.csv` — это `COMBINED_HEADERS` (Title1…Title7,Text1…Text3,…).

- [ ] **Step 8: Прогнать тесты повторно + классический пример не сломан**

Run: `python -m pytest tests/test_generate_ads_xlsx.py -q`
Expected: PASS.

Run: `python -m scripts.generate_ads_xlsx --workspace assets --creatives-json assets/creatives_schema_example.json --output-dir "$TMPDIR/classic_out" --format csv`
Expected: работает как раньше, заголовок `ads.csv` — классический `HEADERS` (Title,Title2,Text,…).

- [ ] **Step 9: Commit**

```bash
git add scripts/generate_ads_xlsx.py tests/test_generate_ads_xlsx.py
git commit -m "generate_ads_xlsx: support ЕПК combinatorial ad output + tests"
```

---

### Task 8: Гейт выбора модели, `_state.json`, ветвление Шага 5, снятие потолка в `SKILL.md`

**Files:**
- Modify: `SKILL.md` (Шаг 0 `_state.json`; новый гейт в начале Шага 5; `ad_model`)

**Interfaces:**
- Produces: поле `ad_model` в `_state.json`; гейт выбора модели в начале Шага 5, читаемый Шагами 8/8.5/9/10 (Task 9).

- [ ] **Step 1: Добавить `ad_model` в артефакт Шага 0**

Найти в `SKILL.md`:

```
**Артефакт:** `direct-campaigns/<slug>/00_brief.md` + `_state.json` (current_step, slug, product_name, wordstat_api_available).
```

Заменить на:

```
**Артефакт:** `direct-campaigns/<slug>/00_brief.md` + `_state.json` (current_step, slug, product_name, wordstat_api_available, ad_model). Поле `ad_model` заполняется на гейте в начале Шага 5 (`epk_combined` | `classic`); до этого — `null`.
```

- [ ] **Step 2: Вставить гейт выбора модели в начало Шага 5**

Найти:

```
## Шаг 5. Структура кампаний

**Прочти `references/campaign-structure.md`.**
```

Заменить на:

```
## Шаг 5. Структура кампаний

**Прочти `references/campaign-structure.md`.**

### Шаг 5.0. Гейт: выбор модели объявлений [GATE: маркетолог]

До построения структуры покажи маркетологу выбор с плюсами и минусами и **рекомендацией ЕПК**. Запиши ответ в `_state.json` как `ad_model` (`epk_combined` | `classic`). При возобновлении, если `ad_model` уже задан, — не спрашивай заново.

| | 🟢 ЕПК + комбинаторное объявление (рекомендуем) | ⚪ Классическая |
|---|---|---|
| Структура | 1 РК = 1 угол, одно объявление на Поиск+РСЯ+Галерею+Карты | Поиск и РСЯ — отдельные РК, 3-5 объявлений/группа |
| Плюсы | меньше сущностей; Яндекс сам подбирает связку заголовков/картинок; быстрый старт; единый бюджет на угол | полный раздельный контроль текстов под Поиск и под РСЯ; раздельная статистика; привычно |
| Минусы | меньше ручного контроля где что покажется; статистика Поиск/РСЯ смешана; **MCP не зальёт комбинаторное — руками** | больше кампаний и объявлений вести; медленнее; тест-матрицу придумываешь сам |
| Кому | большинству запусков, особенно при ограниченном времени | когда нужна тонкая раздельная настройка Поиск vs РСЯ |

Прямой вопрос: «Рекомендую ЕПК с комбинаторным объявлением. Берём ЕПК или классику?»

### Шаг 5.1. Построение структуры

Дальше строй структуру по выбранной модели (раздел «Две модели структуры» в `references/campaign-structure.md`):
- **`epk_combined`:** 1 угол/сегмент/лендинг → 1 РК (1 группа, 1 комбинаторное объявление); Поиск/РСЯ не разделяем. В `05_campaign_structure.json` — `"ad_model": "epk_combined"` и `"combined": true` у кампаний.
- **`classic`:** как раньше (Поиск/РСЯ раздельно). В `05_campaign_structure.json` — `"ad_model": "classic"`.

Жёсткого потолка на число кампаний нет — см. «Много кампаний — мягкая подсказка» в референсе.
```

- [ ] **Step 3: Обновить упоминание архитектуры в шапке Шага 5 (гейт)**

Найти в конце описания Шага 5 строку гейта:

```
**[GATE: маркетолог]** «Эту схему берём? Не объединять ли что?»
```

Заменить на:

```
**[GATE: маркетолог]** «Эту схему берём? Не объединять ли что?» (модель уже выбрана на Шаге 5.0.)
```

- [ ] **Step 4: Проверить правки**

Run: `grep -n "Шаг 5.0. Гейт: выбор модели\|ad_model" SKILL.md`
Expected: несколько строк (гейт + упоминания `ad_model`).

- [ ] **Step 5: Commit**

```bash
git add SKILL.md
git commit -m "SKILL: add ad-model choice gate at Step 5 + ad_model in state"
```

---

### Task 9: Ветвление Шагов 8/8.5/9/10, карта артефактов и возобновление в `SKILL.md`

**Files:**
- Modify: `SKILL.md` (Шаг 8, Шаг 8.5, Шаг 9, Шаг 10, карта артефактов, блок «Возобновление»)

**Interfaces:**
- Consumes: `ad_model` из Task 8; функции/схема из Task 6-7.
- Produces: поведение генерации объявлений и заливки, ветвлённое по `ad_model`.

- [ ] **Step 1: Ветвить Шаг 8 (объявления)**

Найти начало Шага 8:

```
## Шаг 8. Объявления (Поиск)

**Обязательно прочитай** `references/yandex-direct-specs.md` и `references/ad-copywriting.md` **до** написания.

Для каждой группы из `05_campaign_structure.json`:
```

Заменить на:

```
## Шаг 8. Объявления

**Обязательно прочитай** `references/yandex-direct-specs.md` и `references/ad-copywriting.md` **до** написания.

**Ветка зависит от `ad_model` из `_state.json`.**

### Если `ad_model = "epk_combined"` — одно комбинаторное объявление на РК

Для каждой РК (1 группа) готовь **одно** комбинаторное объявление (см. `ad-copywriting.md` → «Комбинаторное объявление» и лимиты в `yandex-direct-specs.md`):
- **3-7 заголовков** (≤56 симв., минимум 2 коротких ≤35), обязательное вхождение ключа хотя бы в один;
- **2-3 текста** (≤81 симв.), каждый самодостаточен;
- картинки (до 5) и видео (до 6) из ассетов брифа — нет ассетов — без них, TODO в Шаг 8.5;
- быстрые ссылки, уточнения, отображаемая ссылка.

Артефакт `08_creatives.json` в форме ЕПК (корень `"ad_model": "epk_combined"`, в группе объект `combined_ad`) — схема `assets/creatives_schema_combined_example.json`.

### Если `ad_model = "classic"` — тест-матрица (как раньше)

Для каждой группы из `05_campaign_structure.json`:
```

- [ ] **Step 2: Обновить блок генерации xlsx и гейт в конце Шага 8**

Найти:

```
**Артефакты:** `08_creatives.md` (для маркетолога) + `08_creatives.json` (machine-readable; схема — `assets/creatives_schema_example.json`).

После — `python -m scripts.generate_ads_xlsx --workspace <path>` → xlsx/csv + `warnings.txt` со списком превышений лимитов.

**[GATE: маркетолог]** «Объявления принимаешь?»
```

Заменить на:

```
**Артефакты:** `08_creatives.md` (для маркетолога) + `08_creatives.json` (machine-readable). Схема: `assets/creatives_schema_example.json` для `classic`, `assets/creatives_schema_combined_example.json` для `epk_combined`.

После — `python -m scripts.generate_ads_xlsx --workspace <path>` → xlsx/csv + `warnings.txt`. Скрипт сам определяет ветку по полю `ad_model` в `creatives.json` (для ЕПК валидирует лимиты: ≤7 заголовков, ≤3 текстов, ≤5 картинок, ≤6 видео).

**[GATE: маркетолог]** «Объявления принимаешь?»
```

- [ ] **Step 3: Оговорка про ЕПК в Шаге 8.5**

Найти начало Шага 8.5:

```
## Шаг 8.5. РСЯ-визуалы (заглушка)

⚠️ **Эта часть пайплайна пока не проработана.** Скилл оставляет в рабочей папке плейсхолдер `08_5_rsya_creatives_TODO.md` со списком того, что нужно подготовить, и **не задерживает на этом запуск**.
```

Заменить на:

```
## Шаг 8.5. Визуалы (РСЯ / комбинаторное объявление) (заглушка)

⚠️ **Эта часть пайплайна пока не проработана.** Скилл оставляет в рабочей папке плейсхолдер `08_5_rsya_creatives_TODO.md` со списком того, что нужно подготовить, и **не задерживает на этом запуск**.

**При `ad_model = "epk_combined"`** картинки/видео — это ассеты комбинаторного объявления Шага 8 (до 5 картинок, до 6 видео на объявление), а не отдельная РСЯ-кампания. Если ассеты есть — прикладываем к `combined_ad`; нет — объявление без них, здесь остаётся TODO. При `ad_model = "classic"` — как ниже (отдельная РСЯ-кампания).
```

- [ ] **Step 4: Оговорка про ЕПК в Шаге 9**

Найти начало Шага 9:

```
## Шаг 9. Стратегия торгов

**Прочти `references/bidding-strategy.md` целиком.**
```

Заменить на:

```
## Шаг 9. Стратегия торгов

**Прочти `references/bidding-strategy.md` целиком** (для ЕПК — обязательно подраздел «ЕПК (`ad_model = epk_combined`)»).

При `ad_model = "epk_combined"` Поиск и РСЯ — одна кампания, поэтому **одна стратегия на РК** (без раздельных Поиск/РСЯ-стратегий); в `09_bidding_strategy.json` у таких кампаний `"channel": "epk"`. При `ad_model = "classic"` — как раньше.
```

- [ ] **Step 5: Честность про заливку комбинаторного объявления в Шаге 10Б**

Найти в Шаге 10Б пункт:

```
4. **`ads_add`** — заливка объявлений из `08_creatives.json`
```

Заменить на:

```
4. **`ads_add`** — заливка объявлений из `08_creatives.json`.
   - `ad_model = "classic"`: `ads_add` создаёт `TextAd` — работает.
   - `ad_model = "epk_combined"`: **комбинаторное объявление через `ads_add` НЕ создаётся** (MCP умеет только `TextAd`). Заливаем его руками через Директ Коммандер/UI по `08_creatives.json`, либо через passthrough `yandex_direct_api_call`, если он появится. Фиксируем как «доделать руками» в `10_launch_log.md`.
```

- [ ] **Step 6: Обновить карту артефактов и возобновление**

Найти в карте артефактов строку:

```
08_creatives.json ──→ Шаг 10 (заливка объявлений)
```

Заменить на:

```
_state.json.ad_model ──→ Шаг 5 (структура) · Шаг 8 (форма объявления) · Шаг 9 (стратегия) · Шаг 10 (способ заливки)

08_creatives.json ──→ Шаг 10 (заливка объявлений; для epk_combined объявление заливается руками)
```

Найти блок «# Возобновление»:

```
«Продолжаем по Директу» → найди `direct-campaigns/*/`, прочитай `_state.json`, продолжай с того места. Не начинай сначала. Если кампания уже залита через MCP — этот скилл закончил работу; дальнейшие изменения — другая задача.
```

Заменить на:

```
«Продолжаем по Директу» → найди `direct-campaigns/*/`, прочитай `_state.json` (включая `ad_model`), продолжай с того места. Если `ad_model` уже задан — не переспрашивай модель на Шаге 5.0. Не начинай сначала. Если кампания уже залита — этот скилл закончил работу; дальнейшие изменения — другая задача.
```

- [ ] **Step 7: Проверить все правки**

Run: `grep -n "ad_model = .epk_combined.\|комбинаторное объявление через .ads_add. НЕ создаётся\|Шаг 8. Объявления$" SKILL.md`
Expected: несколько строк, включая честную оговорку про `ads_add`.

- [ ] **Step 8: Commit**

```bash
git add SKILL.md
git commit -m "SKILL: branch Steps 8/8.5/9/10 by ad_model; honest ЕПК upload note"
```

---

### Task 10: Обновить README и финальная сверка

**Files:**
- Modify: `README.md` (раздел 7 «Как проходит работа» — упомянуть выбор модели)

**Interfaces:**
- Consumes: всё выше.
- Produces: пользовательское описание выбора модели.

- [ ] **Step 1: Упомянуть выбор модели в README, раздел 7**

Найти в `README.md`:

```
6. **Структура кампаний** — как разбить всё на кампании и группы.
```

Заменить на:

```
6. **Структура кампаний** — сначала выбор модели (🟢 ЕПК с одним комбинаторным объявлением на кампанию — рекомендуем; или ⚪ классика с раздельными Поиск/РСЯ-кампаниями), затем разбивка на кампании и группы. Число кампаний в запуске не ограничено.
```

- [ ] **Step 2: Проверить**

Run: `grep -n "комбинаторным объявлением\|не ограничено" README.md`
Expected: одна строка.

- [ ] **Step 3: Финальная сверка всего скилла**

Run: `python -m pytest tests/ -q`
Expected: PASS.

Run: `grep -rn "обычно 2-4\|это много" references/campaign-structure.md`
Expected: пусто (жёсткий потолок убран).

Run: `grep -rn "epk_combined" SKILL.md references/ scripts/ assets/`
Expected: совпадения во всех ключевых файлах (SKILL.md, campaign-structure.md, ad-copywriting.md, bidding-strategy.md, yandex-direct-specs.md, rsya-creatives.md, generate_ads_xlsx.py, creatives_schema_combined_example.json).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "README: mention ad-model choice and unlimited campaigns"
```

---

## Self-Review

**1. Spec coverage:**
- Две ветки + гейт с плюсами/минусами → Task 8 (гейт), Task 2 (структура), Task 3 (копирайтинг). ✅
- Рекомендация ЕПК → Task 8 (в таблице гейта). ✅
- `ad_model` в `_state.json` → Task 8. ✅
- Ветвление Шагов 5/8/8.5/9/10 → Task 8 (5), Task 9 (8/8.5/9/10). ✅
- ЕПК-структура (1 РК=1 комбинаторное) → Task 2. ✅
- Классика без изменений → сохранена во всех задачах (ветвление, не замена). ✅
- Честная заливка (MCP только TextAd) → Task 1 (врезка), Task 9 Step 5. ✅
- Снятие потолка → Task 2 Step 2, Task 8 Step 2, Task 10 Step 3. ✅
- Схема комбинаторного объявления → Task 6. ✅
- `generate_ads_xlsx` + валидация + тесты → Task 7. ✅
- Лимиты комбинаторного объявления → Task 1 (specs единый источник), Task 7 (`COMBINED_LIMITS`). ✅
- Врезка стратегии ЕПК → Task 4. ✅
- Ассеты в комбинаторном объявлении → Task 5, Task 9 Step 3. ✅

**2. Placeholder scan:** плейсхолдеров нет — весь вставляемый текст и код приведён дословно; числовые лимиты подтверждены по докам Яндекса.

**3. Type consistency:** `ad_model` значения `"epk_combined"`/`"classic"` едины во всех задачах. Функции `validate_combined_ad`, `assemble_combined_ad_rows`, `select_assembler`, константы `COMBINED_LIMITS`/`COMBINED_HEADERS` — имена совпадают между Task 7 (реализация), тестами (Task 7 Step 1) и вызовом в `main`. `select_assembler` возвращает `(rows, warnings, headers)` — согласовано с `main`. `write_xlsx`/`write_csv` получают доп. параметр `headers` — обновлены обе сигнатуры и оба вызова.
