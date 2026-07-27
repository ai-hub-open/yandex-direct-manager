# Интеграция MCP yandex-direct в пайплайн создания кампании

Этот reference — про use cases для работы с MCP yandex-direct во время прохождения шагов пайплайна. Не путать с `yandex-direct-mcp.md`, который описывает установку MCP-сервера и режимы запуска (sandbox/direct/clickru).

## Когда применять

Перед тем как опираться на эти инструкции — **проверь**, доступны ли `mcp__yandex-direct__*` инструменты в текущей сессии. Если их нет, скилл всё равно работает — просто без live-данных.

Безопасные read-only тулы:
- `mcp__yandex-direct__yandex_direct_campaigns_get`
- `mcp__yandex-direct__yandex_direct_keywords_get`
- `mcp__yandex-direct__yandex_direct_dictionaries_regions`
- `mcp__yandex-direct__yandex_direct_report_search_queries`
- `mcp__yandex-direct__yandex_direct_report_campaign`
- `mcp__yandex-direct__yandex_direct_report_ad`

Эти вызовы **ничего не меняют** в кампаниях.

---

## Use case 1: Аудит аккаунта (Шаг 2)

**Когда:** на Шаге 2 параллельно с прогнозом частотности. Этот use case встроен в `frequency-calculator` — отдельным шагом скилла не выделяется.

**Зачем:** понять есть ли в аккаунте кампании, семантически пересекающиеся с новой. Это нужно, чтобы:
- На Шагах 3-4 не дублировать ключи (каннибализация в Директе — ты конкурируешь сам с собой за показ).
- На Шаге 2 использовать реальные ставки и CPC из похожих кампаний как ground-truth прогноз.

**Как:**

```
mcp__yandex-direct__yandex_direct_campaigns_get({ limit: 100 })
```

Сохрани в `<workspace>/_account_audit.md`:

```markdown
# Аудит аккаунта (на момент запуска пайплайна)

Всего кампаний: N
Активных (State=ON): K
Драфтов (State=OFF, Status=DRAFT): M
Архив: L

## Возможно семантически близкие к новой
- Id 709899154 «KM-Search-P1-SMM-Freelancer» — DRAFT, бюджет 1700 ₽/день
- Id 709899157 «KM-Search-P2-Expert» — DRAFT, бюджет 1000 ₽/день
- ...

## Прочие (учитываем для общего контекста)
- Id 709833190 «LD | Поиск | Мск | Панно» — другой бизнес
```

Покажи пользователю: «Я вижу N кампаний, из них K похожи на новую (`<имена>`). Учитываем их при подборе ключей и прогнозе CPC?» — сохрани ответ.

---

## Use case 2: Расширение и дедупликация ключей (Шаги 3 и 8)

### А. Расширение через `keywords_get`

```
mcp__yandex-direct__yandex_direct_keywords_get({
  campaign_ids: [709899154, 709899157, 709899161],
  limit: 500
})
```

Ответ:
```json
{
  "Keywords": [
    {"Id": ..., "Keyword": "\"нейросеть для смм\"", "AdGroupId": 5750683411, "Bid": 300000, "State": "ON"},
    {"Id": ..., "Keyword": "---autotargeting", ...},
    ...
  ]
}
```

Что делать:
1. **Игнорируй `---autotargeting`** — служебная запись Директа для автоподборов.
2. **`Bid` в микро-валюте** — 300000 = 0.30 ₽. Дефолт стратегии «макс кликов». Если все ключи на одной ставке 0.30 — ставки ещё не оптимизированы, прогноз CPC по ним брать нельзя.
3. **Сравни с твоим новым списком из Шага 3-4.** Найди:
   - **Дубли** (после нормализации: lowercase, убрать кавычки/операторы, trim). Не добавлять.
   - **Близкие варианты** — можно добавить оба.
   - **Что у юзера есть, чего нет у тебя** — потенциально хорошие новые ключи.

### Б. Оценка CPC (история → живой аукцион)

⚠️ Метода `Forecast.GetForecast` (прогноз по произвольным фразам) в API v5 **нет** — закрыт вместе с API v4. CPC оцениваем по реальным данным аккаунта в порядке достоверности.

**1. Историческая AvgCpc.** Если у похожих кампаний был открученный трафик (`Statistics.Clicks > 0`):
```
mcp__yandex-direct__yandex_direct_report_campaign({
  campaign_ids: [...],
  date_range: "LAST_30_DAYS"
})
```
Отчёт даст AvgCpc. В медиаплан: «На основе твоих кампаний по этой тематике средний CPC = X ₽».

**2. Живой аукцион (`KeywordBids.get`).** Если трафика нет (кампании DRAFT/OFF) — берём реальные цены аукциона по их ключам, расход не нужен:
```
mcp__yandex-direct__yandex_direct_api_call({
  service: "keywordbids", method: "get",
  params: {
    SelectionCriteria: { KeywordIds: [<из keywords_get>] },
    FieldNames: ["KeywordId", "CampaignId"],
    SearchFieldNames: ["Bid", "AuctionBids"]
  }
})
```
Ответ большой (~44 позиции на ключ) — сохрани в `_keywordbids_raw.json` и прогони `python -m scripts.forecast_cpc --input _keywordbids_raw.json --region-factor <…>`. Скрипт вернёт base/optimistic/pessimistic CPC (медиана `Price` по ключам на TrafficVolume 75/100/62). Подробности — `frequency-calculator.md` Фаза 1, приоритет 2.

Если ни истории, ни ключей в аккаунте нет — **честно** пиши: «CPC по справочнику ниш (defaults-table). Точные данные после первой недели открутки» и бери из `frequency-calculator.md`.

---

## Use case 3: Точные region_ids (Шаг 10)

**Шорт-лист популярных (без вызова MCP):**

| Регион | ID |
|---|---|
| Россия (вся) | 225 |
| Москва (город) | 213 |
| Москва и Московская область | 1 |
| Санкт-Петербург (город) | 2 |
| Санкт-Петербург и Ленинградская область | 10174 |
| Екатеринбург | 54 |
| Новосибирск | 65 |
| Нижний Новгород | 47 |
| Казань | 43 |
| Самара | 51 |
| Пермь | 50 |
| Краснодар | 35 |
| Челябинск | 56 |
| Уфа | 172 |
| Воронеж | 193 |
| Ростов-на-Дону | 39 |
| Сочи | 239 |

**Если нужного города нет** или сомневаешься:

```
mcp__yandex-direct__yandex_direct_dictionaries_regions({})
```

⚠️ Ответ — ~3 МБ JSON. Не пытайся читать целиком. Сохрани в `<workspace>/_regions_cache.json` и грепай по имени. Структура:
```json
{
  "GeoRegionId": 50,
  "GeoRegionName": "Пермь",
  "GeoRegionType": "City",
  "ParentId": 11108
}
```

Справочник не меняется — кэшируй на сессию.

В `10_launch_log.md` фиксируй: «Регион: <название>, region_id: <ID>». В `08_creatives.json` — `"region_ids": [<ID>]`.

---

## Use case 5: Полный запуск кампании через MCP (Шаг 10)

**Когда:** Шаги 0-9 пайплайна пройдены, `08_creatives.json` готов, чек-лист Шага 10А пройден. Юзер говорит «залей»/«запусти через API».

**Что MCP умеет:** создание кампаний/групп/объявлений/ключей, базовые корректировки ставок через `bidmodifiers_demographics`, управление статусами.

**Что MCP НЕ умеет в текущей версии:**
- `display_url_path` в `ads_add` — параметр игнорируется
- `sitelinks` (быстрые ссылки) — не в схеме
- `callouts` (уточнения) — не в схеме
- `Bid` (точная ставка) в `keywords_update` — обёртка принимает только новый текст
- Расширенные параметры стратегии в `campaigns_update`

**Стратегия:** делаем что можем, остальное помечаем в `10_launch_log.md` как «доделать руками или через прямой API».

### Последовательность

1. **Создай кампанию** (по каждой кампании из `05_campaign_structure.json`):
   ```
   campaigns_add({
     name: "<из 05_campaign_structure.json>",
     start_date: "<YYYY-MM-DD>",
     daily_budget: <из месячного бюджета ÷ 30>,
     negative_keywords: [<минусы аккаунт-уровня из 06_negative_keywords.json>]
   })
   ```
   Кампания создаётся в **DRAFT/OFF** — нормально.

2. **Группы** (по каждой группе из `05_campaign_structure.json`):
   ```
   adgroups_add({
     adgroups: [{
       name: "<имя>",
       campaign_id: <ID>,
       region_ids: [<из брифа поле 3 и Use case 3>]
     }]
   })
   ```

3. **Объявления.** MCP примет только базовые поля. Sitelinks/callouts/display_url_path пропадут, и MCP вернёт `Code: 10165 "Parameter will not be applied"` — **штатное** поведение, не ошибка:
   ```
   ads_add({
     ads: [{
       ad_group_id: <ID>,
       title: "...",
       title2: "...",
       text: "...",
       href: "..."
     }]
   })
   ```

4. **Ключи группы:**
   ```
   keywords_add({
     keywords: [
       {keyword: "\"ключ\"", ad_group_id: <ID>},
       ...
     ]
   })
   ```
   Ключи добавляются с дефолтной ставкой стратегии (часто 0.30 ₽). Это **временно** — ставки нужно поднять через прямой API.

5. **Корректировки ставок** (пресет для B2C SaaS):
   ```
   bidmodifiers_demographics({
     campaign_id: <ID>,
     mobile_adjustment: -10,
     age_adjustments: [
       {age: "AGE_0_17", adjustment: -100},
       {age: "AGE_18_24", adjustment: -20}
     ]
   })
   ```
   Для каждой кампании. Для P3 (блогеры) мобайл не корректируем.

6. **Зафиксируй `10_launch_log.md`** со списком ID и **что не долилось через MCP**:

   ```markdown
   # Лог запуска через MCP

   ## Кампании (3, все DRAFT/OFF)
   - KM-Search-P1 — id 709899154 — бюджет 1700 ₽/день
   - ...

   ## Группы, объявления, ключи (id-диапазоны)

   ## Корректировки ставок
   - P1, P2: мобайл -10%, <18 -100%, 18-24 -20% — залиты
   - P3: только мобайл -10% или не залиты

   ## ⚠️ Что MCP НЕ залил, нужно доделать
   - Display URL Path на 9 объявлениях
   - Sitelinks (4 × 9 = 36 шт.)
   - Callouts (4 × 9 = 36 шт.)
   - Поднять ставку с 0.30 до целевой (например 25 ₽) — UI или прямой API
   - Bidding strategy — проверить и при необходимости поправить
   - РСЯ-визуалы (если РСЯ есть) — см. 08_5_rsya_creatives_TODO.md, добавить через UI или отдельной итерацией скилла

   ## ID-сводка
   ```
   P1: campaign 709899154 → adgroup 5750683411 → ads 17718478043, 17718478051, 17718478054
   P2: campaign 709899157 → adgroup 5750683414 → ads ...
   P3: campaign 709899161 → adgroup 5750683417 → ads ...
   ```
   ```

7. **Активацию (`campaigns_resume`) НЕ делай.** Дай юзеру короткий предзапусковой чек-лист: Метрика, цели, ОРД-маркировка, sitelinks/callouts, баланс, посадочные открываются, коллтрекинг (если применимо). Юзер сам активирует в UI Директа.

### Фолбек на прямой API для sitelinks/callouts

Если юзер не хочет выставлять 36+36 sitelinks/callouts руками в UI — через `scripts/yandex_direct_api.py` (принимает полную схему). В текущей версии скрипта это **частично** реализовано (создание кампании, групп, объявлений, ключей — есть; sitelinks/callouts/DisplayUrlPath — расширения нужны). На 9 объявлений руками в UI Директа 15-20 минут.

---

## Карта вызовов по шагам

| Шаг | MCP-вызов | Цель | Записать в |
|---|---|---|---|
| 2 | `campaigns_get` | Аудит существующих кампаний | `_account_audit.md` |
| 2 | `report_campaign(campaign_ids=..., LAST_30_DAYS)` | Историческая AvgCpc похожих кампаний | `02_frequency.md` |
| 2 | `api_call(keywordbids, get)` + `scripts/forecast_cpc.py` | CPC по живому аукциону (ключи аккаунта/temp-группы) | `02_frequency.json` |
| 8 | `keywords_get` (повторно для дедупликации) + `report_campaign` для CPC | Финальный аудит ставок | `08_creatives.md`, `08_creatives.json` |
| 10 | `dictionaries_regions` (один раз) | Точные region_ids | `10_launch_log.md` |
| 10 | `campaigns_add` / `adgroups_add` / `keywords_add` / `ads_add` / `bidmodifiers_demographics` | Заливка кампаний в DRAFT | `10_launch_log.md` |

## Ошибки и фолбеки

- **MCP не отвечает или {success: false}** — обработай ошибку по месту: на Шаге 2 фолбек на справочник CPC; на Шагах 8, 10 — стоп и сообщи маркетологу, что MCP нужно подключить (см. `yandex-direct-mcp.md`).
- **`campaigns_get` пуст** — свежий аккаунт, Use case 1 пропускаем.
- **`dictionaries_regions` слишком большой** — кэшируй в файл `_regions_cache.json`.

## Бюджет квот

MCP-сервер тратит `units` Direct API (~160k в день). Типичный пайплайн (campaigns_get + keywords_get × 2 + report_campaign/keywordbids + dictionaries_regions + заливка) — ~500-2000 units. Можно сделать 50-100+ пайплайнов в день. Не звать справочники в цикле.
