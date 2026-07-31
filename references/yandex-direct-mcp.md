# Yandex Direct MCP — справочник инструментов и подключения

**Единственный источник правды о том, что умеет MCP и как его звать.** Последовательность заливки кампании — в `mcp-account-integration.md` (Use case 5), здесь только контракты.

MCP-сервер `yandex-direct-mcp` (Bun/TypeScript) — мост к API Яндекс.Директа. Версия **0.5.0, 50 инструментов**, API **v501** по умолчанию (v5 не поддерживает ЕПК).

В сессии инструменты видны как `mcp__yandex-direct__<имя>`. Ниже везде указано короткое имя.

---

## Общие правила — прочти до первого вызова

### Деньги

- **На вход всегда валюта аккаунта** (рубли), не микроединицы. Конвертация внутри моста.
- **В ответах `keywordbids_get` — микроединицы**: делить на 1 000 000. То же для поля `Bid` в `keywords_get`: `300000` = 0.30 ₽.
- В отчётах суммы — в валюте (мост запрашивает `returnMoneyInMicros: false`).

### Конверт ответа

| Случай | Что приходит |
|---|---|
| Успех | `{success: true, data: <результат>, units: "потрачено/осталось/лимит"}` |
| Отказ | `{success: false, error_code?, error_message, error_detail?, units}` |
| Предпросмотр | `{success: true, dry_run: true, note, request: {url, service, method, params}}` |
| Отчёт не готов | `{success: false, status: "processing", retry_in: <сек>, error_message, units}` |

**Частичный отказ — главная ловушка.** Ответ может быть `success: true`, но внутри `data.*Results[].Errors` лежат отклонённые объекты. Мост такой ответ помечает ошибкой и перечисляет, что именно не создалось. **«Вернулось без ошибки» ≠ «всё создано»** — всегда смотри на текст ответа целиком, а не только на `success`.

### `dry_run` — предпросмотр без записи

Все инструменты, меняющие кабинет, принимают `dry_run: true`. Возвращается тело запроса, которое ушло бы в Директ, **ничего не создавая и не изменяя**. При этом все проверки выполняются полностью — то есть предпросмотр ловит ошибки данных до записи.

Используй на гейтах Шага 10: сначала весь конвейер в `dry_run`, показываешь маркетологу сводку, после «ОК» — реальная заливка.

Нет `dry_run` у читающих инструментов, отчётов и `forecast_bids` (они и так ничего не меняют).

### Баллы API

В каждом ответе поле `units` — потрачено / осталось / суточный лимит (~160k). Типичный пайплайн — 500–2000 баллов. Справочники в цикле не звать.

---

## Кампании

### `campaigns_get`

Обязательных параметров нет.

| Параметр | Тип | Смысл |
|---|---|---|
| `ids` | int[] | ID кампаний |
| `states` | string[] | `ON`, `OFF`, `SUSPENDED`, `ENDED`, `CONVERTED`, `ARCHIVED` |
| `types` | string[] | `TEXT_CAMPAIGN`, `UNIFIED_CAMPAIGN`, `MOBILE_APP_CAMPAIGN`, `DYNAMIC_TEXT_CAMPAIGN`, `CPM_BANNER_CAMPAIGN`, `SMART_CAMPAIGN` |
| `include_strategy` | bool | **Вернуть стратегию, счётчики Метрики, приоритетные цели, модель атрибуции.** По умолч. false |
| `limit` | int | По умолч. 100 |

Без фильтров возвращает все кампании. `include_strategy: true` — это способ прочитать `CounterIds` и `PriorityGoals` (отдельного параметра `Counters` не существует).

### `campaigns_add`

**Обязательно:** `name`, `start_date` (`YYYY-MM-DD`).

| Параметр | Тип | Смысл |
|---|---|---|
| `campaign_type` | `TEXT` \| `UNIFIED` | `UNIFIED` = ЕПК. По умолч. `TEXT` |
| `end_date` | string | `YYYY-MM-DD` |
| `daily_budget` | number | Дневной бюджет в валюте. **Только для ручных стратегий** |
| `daily_budget_mode` | `STANDARD` \| `DISTRIBUTED` | По умолч. `DISTRIBUTED` |
| `negative_keywords` | string[] | Минус-фразы кампании |
| `search_strategy` | object | Стратегия на поиске, см. ниже |
| `network_strategy` | object | Стратегия в сетях, см. ниже |
| `counter_ids` | int[] | Счётчики Метрики |
| `priority_goals` | object[] | `{goal_id, value, is_metrika_source_of_value?}` — `value` обязателен |
| `attribution_model` | `FCCD` \| `LC` \| `LSCCD` \| `AUTO` | По умолч. AUTO |
| `tracking_params` | string | UTM-метки, напр. `utm_source=yandex&utm_campaign={campaign_id}` |

**Для `UNIFIED` стратегия обязательна** — без `search_strategy` и `network_strategy` инструмент вернёт ошибку. Незаданная сторона автоматически выключается (`SERVING_OFF`).

**Недельный бюджет — это `weekly_spend_limit` внутри стратегии, а не `daily_budget`.** Автостратегии живут на недельном бюджете; `daily_budget` для них не применяется.

Создаёт одну кампанию за вызов.

### `campaigns_update`

**Обязательно:** `id`. Остальные параметры — те же, что у `campaigns_add`.

⚠️ **При смене стратегии передавай обе стороны** (`search_strategy` и `network_strategy`) — API заменяет стратегию целиком, инструмент проверяет это и вернёт ошибку, если задана только одна. Для выключенной стороны — `{type: "SERVING_OFF"}`.

Так же обновляются `counter_ids` и `priority_goals` (Шаг 7, привязка целей Метрики).

### `campaigns_delete` / `campaigns_suspend` / `campaigns_resume`

Принимают `ids` (int[]). `delete` = перенос в архив.

🚫 **`campaigns_resume` — активация кампании. Скилл её не вызывает никогда.** Активирует только маркетолог в интерфейсе Директа.

---

## Стратегии торгов

Объект `search_strategy` / `network_strategy` — обязательное поле `type` плюс параметры типа.

**Типы на поиске:** `HIGHEST_POSITION`, `WB_MAXIMUM_CLICKS`, `WB_MAXIMUM_CONVERSION_RATE`, `AVERAGE_CPC`, `AVERAGE_CPA`, `AVERAGE_CRR`, `PAY_FOR_CONVERSION`, `PAY_FOR_CONVERSION_CRR`, `WEEKLY_CLICK_PACKAGE`, `AVERAGE_CPA_MULTIPLE_GOALS`, `PAY_FOR_CONVERSION_MULTIPLE_GOALS`, `MAX_PROFIT`, `SERVING_OFF`.

**В сетях:** то же, но вместо `HIGHEST_POSITION` — `NETWORK_DEFAULT` и `MAXIMUM_COVERAGE`.

| Тип | Обязательные | Опциональные |
|---|---|---|
| `HIGHEST_POSITION` / `MAXIMUM_COVERAGE` / `SERVING_OFF` | — | — |
| `NETWORK_DEFAULT` | — | `limit_percent` (10–100) |
| `WB_MAXIMUM_CLICKS` | `weekly_spend_limit` | `bid_ceiling` |
| `WB_MAXIMUM_CONVERSION_RATE` | `weekly_spend_limit`, `goal_id` | `bid_ceiling` |
| `AVERAGE_CPC` | `average_cpc` | `weekly_spend_limit` |
| `AVERAGE_CPA` | `average_cpa`, `goal_id` | `weekly_spend_limit`, `bid_ceiling` |
| `AVERAGE_CRR` / `PAY_FOR_CONVERSION_CRR` | `crr` (%), `goal_id` | `weekly_spend_limit` |
| `PAY_FOR_CONVERSION` | `cpa`, `goal_id` | `weekly_spend_limit` |
| `WEEKLY_CLICK_PACKAGE` | `clicks_per_week` | `average_cpc`, `bid_ceiling` |
| `*_MULTIPLE_GOALS` / `MAX_PROFIT` | — (цели берутся из `priority_goals`, минимум 2) | `weekly_spend_limit`, `bid_ceiling` |

Пропуск обязательного параметра → ошибка вида «Стратегия WB_MAXIMUM_CLICKS: обязателен параметр weekly_spend_limit».

Деньги (`weekly_spend_limit`, `bid_ceiling`, `average_cpc`, `average_cpa`, `cpa`) — в валюте аккаунта. `crr`, `clicks_per_week`, `limit_percent`, `goal_id` — целые числа как есть.

Соответствие фаз скилла этим типам — в `bidding-strategy.md`, раздел «Маппинг в API».

---

## Группы объявлений

### `adgroups_add`

**Обязательно:** `campaign_id`, `name`, `region_ids` (int[]).

| Параметр | Тип | Смысл |
|---|---|---|
| `group_type` | `TEXT` \| `UNIFIED` | `UNIFIED` — группа ЕПК, в неё идут комбинаторные объявления |
| `offer_retargeting` | bool | Офферный ретаргетинг, только для `UNIFIED` |
| `negative_keywords` | string[] | Минус-фразы группы |
| `tracking_params` | string | UTM на уровне группы |

Одна группа за вызов. При `group_type: "TEXT"` параметр `offer_retargeting` молча игнорируется.

### `adgroups_get` / `adgroups_update` / `adgroups_delete`

`get`: `campaign_ids`, `ids`, `limit`. `update`: `id` + `name`, `region_ids`, `negative_keywords`, `tracking_params`. `delete`: `ids`.

---

## Объявления

### `ads_add_responsive` — комбинаторное объявление ЕПК

Основной инструмент заливки: именно эту модель производит Шаг 8.

**Обязательно:** `ad_group_id`, `titles`, `texts`. Плюс **`href` или `business_id`** — без одного из них инструмент вернёт ошибку.

| Параметр | Тип | Лимит |
|---|---|---|
| `titles` | string[] | 1–7 заголовков |
| `texts` | string[] | 1–3 текста |
| `href` | string | Ссылка на сайт |
| `business_id` | int | Профиль организации вместо ссылки |
| `image_hashes` | string[] | До 5, из `adimages_add` |
| `display_url_path` | string | Отображаемая ссылка, до 20 символов |
| `sitelink_set_id` | int | Набор быстрых ссылок из `sitelinks_add` |
| `ad_extension_ids` | int[] | Уточнения из `adextensions_add` |
| `video_extension_ids` | int[] | Видеодополнения — **ID взять негде**, см. «Чего MCP не умеет» |

Одно объявление за вызов. Длины заголовков и текстов мост **не проверяет** — это делает `scripts/preflight.py` до заливки.

### `ads_add` — текстово-графическое объявление

Для классических кампаний. **Обязательно:** `ad_group_id`, `title`, `text`, `href`. Опц.: `title2`, `mobile`, `ad_image_hash`, `display_url_path`, `sitelink_set_id`, `ad_extension_ids`.

Скилл его не использует: модель одна — комбинаторное в ЕПК.

### `ads_update`

**Обязательно:** `id`. `ad_type`: `TEXT` (по умолч.) или `RESPONSIVE`.

Поля разных типов не смешиваются: при `RESPONSIVE` нельзя `title`/`title2`/`text`/`ad_image_hash`, при `TEXT` нельзя `titles`/`texts`/`image_hashes`/`business_id` — инструмент вернёт ошибку с перечнем недопустимых полей.

Массивы `titles`, `texts`, `image_hashes` **заменяются целиком** — передавай полный новый состав.

Уточнения: `callout_ids` + `callout_operation` (`SET` — заменить набор, по умолч.; `ADD` — добавить; `REMOVE` — отвязать перечисленные), либо `detach_callouts: true` — отвязать все. Вместе не работают.

### `ads_delete` / `ads_suspend` / `ads_resume` / `ads_moderate`

Принимают `ids`. `ads_moderate` — отправка на модерацию, единственный способ сделать это из API.

---

## Быстрые ссылки

### `sitelinks_add`

**Обязательно:** `sitelinks` — массив 1–8 элементов. Элемент: `title` (обязателен) + **`href` или `turbo_page_id`**, опц. `description`.

Возвращает ID набора → подставляется в `sitelink_set_id` объявления.

⚠️ **Наборы неизменяемы.** Чтобы поправить одну ссылку, создаётся новый набор и объявление перепривязывается.

Лимиты Директа (мост не проверяет, проверяет `preflight.py`): заголовок ≤30 символов, описание ≤60, адрес ≤1024.

### `sitelinks_get` / `sitelinks_delete`

`get`: `ids` (обязательно) + `limit`. `delete`: `ids`.

---

## Уточнения

### `adextensions_add`

**Обязательно:** `callouts` — массив строк, **каждая ≤25 символов** (проверяется, вернёт ошибку со списком слишком длинных).

Возвращает ID → в `ad_extension_ids` объявления. Уточнения проходят модерацию и переиспользуются в любых объявлениях аккаунта. Одинаковые тексты повторно создать нельзя — API вернёт ошибку дубликата.

### `adextensions_get`

Всё опционально: `ids`, `statuses` (`ACCEPTED`, `DRAFT`, `MODERATION`, `REJECTED`), `include_deleted`, `limit`.

**Зови перед `adextensions_add`**: уже принятые модерацией уточнения переиспользуются, это экономит время на модерацию.

### `adextensions_delete`

`ids`.

---

## Ключевые фразы и ставки

### `keywords_add`

**Обязательно:** `keywords` — массив `{keyword, ad_group_id}`. Можно пачкой в разные группы.

⚠️ **Ставку здесь задать нельзя** — параметра `bid` не существует. Фразы добавляются с дефолтной ставкой стратегии; ставки выставляются отдельно через `keywordbids_set`.

### `keywords_get` / `keywords_update` / `keywords_delete` / `keywords_suspend` / `keywords_resume`

`get`: `campaign_ids`, `ad_group_ids`, `ids`, `limit` (по умолч. 500). Возвращает `Keyword`, `Bid` (**в микроединицах**), `State`, `Status`.
`update`: `keywords: [{id, keyword}]` — только текст фразы.
Остальные: `ids`.

Служебную запись `---autotargeting` в ответах игнорируй — это автоподбор Директа, не ключ.

### `keywordbids_set` — выставить ставки

**Обязательно:** `bids` — массив. В каждом элементе:

- **ровно один** из `keyword_id` / `ad_group_id` / `campaign_id` — иначе ошибка;
- **хотя бы одно** из `search_bid` / `network_bid` / `strategy_priority` — иначе ошибка.

`search_bid` и `network_bid` — в валюте аккаунта. `strategy_priority` — `LOW` \| `NORMAL` \| `HIGH`, используется вместо ставок при автостратегиях.

Лимиты вызова: до 10 кампаний, 1000 групп, 10000 фраз.

Уровень группы (`ad_group_id`) закрывает все её фразы одним элементом — удобнее, чем перечислять ключи.

### `keywordbids_get` — ставки и живой аукцион

Обязателен **хотя бы один** из `campaign_ids` / `ad_group_ids` / `keyword_ids`. Опц. `include_auction` (по умолч. true), `limit` (по умолч. 1000).

Возвращает `Search.Bid`, `Search.AuctionBids` (таблица аукциона: `TrafficVolume` / `Bid` / `Price`), `Network.Bid`, `Network.Coverage`. **Все суммы — микроединицы.**

Ответ объёмный (~44 позиции аукциона на ключ). Не парси вручную: сохрани в файл и прогони `python -m scripts.forecast_cpc --input <файл>`.

---

## Прогноз

### `forecast_bids` — прогноз по произвольным фразам

**Прогноз цены клика и трафика без создания кампании.** Нужен на Шаге 2, когда в аккаунте ещё ничего нет.

**Обязательно:** `phrases` — до 100 фраз за вызов. Опц.: `region_ids`, `currency` (по умолч. берётся из аккаунта), `wait_seconds` (по умолч. 120 — инструмент сам ждёт готовности отчёта).

Возвращает по каждой фразе: `shows_per_month`, `clicks_per_month`, `cpc_guarantee_min` / `cpc_guarantee_max` (вилка цены клика в гарантии), `cpc_premium_min` / `cpc_premium_max` (в спецразмещении), `ctr`, `ctr_first_place`, `ctr_premium`.

Плюс блок `total`: `shows_per_month`, `clicks_per_month` и `budget_guarantee_min/max`, `budget_premium_min/max` — здесь это **суммарный бюджет**, а не цена клика.

Все суммы — в валюте аккаунта, не в микроединицах.

🚫 **Недоступен в режиме прокси Click.ru** — прогноз живёт в Live API v4, которому нужен OAuth-токен Яндекса. Вернёт понятную ошибку; Шаг 2 в этом случае уходит на живой аукцион (`keywordbids_get`) или справочник ниш.

Это про деньги, не про спрос: частотность запросов — Wordstat (`scripts/wordstat_api.py`).

---

## Отчёты

Четыре инструмента: `report_campaign`, `report_ad`, `report_search_queries` (пресеты) и `report_custom` (произвольный).

Общие параметры у всех четырёх:

| Параметр | Смысл |
|---|---|
| `date_from` + `date_to` | Период `YYYY-MM-DD`. Заданы оба → период кастомный |
| `date_range` | `TODAY`, `YESTERDAY`, `LAST_7_DAYS`, `LAST_14_DAYS`, `LAST_30_DAYS`, `THIS_MONTH`, `LAST_MONTH`, `ALL_TIME`. По умолч. `LAST_7_DAYS` |
| `campaign_ids` | Фильтр по кампаниям |
| `fields` | Переопределить столбцы: `Date`, `CampaignName`, `Impressions`, `Clicks`, `Cost`, `Ctr`, `AvgCpc`, `Conversions`, `CostPerConversion`, `ConversionRate`, `Device`, `LocationOfPresenceName`, `Criteria`, `Query`, `Placement`, `Gender`, `Age` |
| `filters` | `[{field, operator, values}]`, операторы `EQUALS`, `NOT_EQUALS`, `IN`, `NOT_IN`, `LESS_THAN`, `GREATER_THAN`, `STARTS_WITH` |
| `goals` | ID целей Метрики — добавляет столбцы конверсий |
| `attribution_models` | `FC`, `LC`, `LSC`, `FCCD`, `LCCD`, `LSCCD`, `AUTO` |
| `include_vat` | По умолч. true |
| `page_limit` | Ограничить число строк |
| `wait_seconds` | Сколько ждать офлайн-очередь, по умолч. 90 |

`report_custom` дополнительно требует `report_type`: `ACCOUNT_PERFORMANCE_REPORT`, `CAMPAIGN_PERFORMANCE_REPORT`, `ADGROUP_PERFORMANCE_REPORT`, `AD_PERFORMANCE_REPORT`, `CRITERIA_PERFORMANCE_REPORT` (по фразам), `CUSTOM_REPORT`, `REACH_AND_FREQUENCY_PERFORMANCE_REPORT`, `SEARCH_QUERY_PERFORMANCE_REPORT` — и непустой `fields`.

Отчёт может уйти в офлайн-очередь: мост ждёт сам, при таймауте вернёт `status: "processing"` и `retry_in` — повтори вызов позже.

---

## Корректировки ставок

Во всех — **уровень задаётся ровно одним** из `campaign_id` / `ad_group_id`.

Коэффициент `bid_modifier` — **множитель в процентах, а не дельта**: `100` = без изменений, `90` = снизить на 10%, `200` = удвоить, `0` = отключить показы сегменту.

| Инструмент | Параметры | Диапазон |
|---|---|---|
| `bidmodifiers_devices` | `mobile`, `desktop`, `tablet`, `smart_tv` — каждый `{bid_modifier, os_type?}`; `os_type` (`IOS`/`ANDROID`) только для mobile и tablet | 0–1300 |
| `bidmodifiers_regional` | `adjustments: [{region_id, bid_modifier}]` | 10–1300 (0 недопустим — регион исключают из таргетинга группы) |
| `bidmodifiers_demographics` | `adjustments: [{gender?, age?, bid_modifier}]`; `gender`: `GENDER_MALE`/`GENDER_FEMALE`; `age`: `AGE_0_17`, `AGE_18_24`, `AGE_25_34`, `AGE_35_44`, `AGE_45_54`, `AGE_55` | 0–1300 |
| `bidmodifiers_retargeting` | `adjustments: [{retargeting_condition_id, bid_modifier}]` | 0–1300 |
| `bidmodifiers_set` | `adjustments: [{id, bid_modifier}]` — изменить существующую по ID | 0–1300 |
| `bidmodifiers_delete` | `ids` | — |
| `bidmodifiers_get` | `campaign_ids` / `ad_group_ids` / `ids` (хотя бы одно), `levels`, `types` | — |

⚠️ **Повторный вызов создающего инструмента для того же сегмента вернёт ошибку дубликата.** Директ не допускает двух корректировок одного типа на объекте. Чтобы поменять значение — `bidmodifiers_get` (взять `Id`) → `bidmodifiers_set`.

---

## Изображения

### `adimages_add`

**Обязательно:** `file_path` (абсолютный путь), `name` (до 255 символов).

Опц.: `crop` — `square` (1:1, минимум 450×450) или `wide` (16:9, минимум 1080×607); `crop_offset` — вертикальный сдвиг области обрезки (0 — верх, 50 — центр, по умолч., 100 — низ). По горизонтали всегда центр.

Если картинка меньше минимума, она добирается апскейлом, а не отвергается.

Возвращает `AdImageHash` → в `image_hashes` объявления. Файла нет на диске — ошибка «Файл не найден», поэтому существование картинок проверяется в pre-flight.

### `adimages_get`

Список загруженных изображений аккаунта — для переиспользования.

---

## Справочники

| Инструмент | Что отдаёт |
|---|---|
| `dictionaries_regions` | Регионы: `GeoRegionId`, `GeoRegionName`, `GeoRegionType`, `ParentId`. Ответ ~3 МБ — сохрани в `_regions_cache.json` и грепай, не читай целиком |
| `dictionaries_currencies` | Валюты с минимальными и максимальными ставками |
| `dictionaries_interests` | Интересы аудитории |
| `dictionaries_all` | Несколько справочников разом; `names`: `Currencies`, `GeoRegions`, `TimeZones`, `Constants`, `AdCategories`, `Interests`, `AudienceInterests`, `AudienceDemographicProfiles`. По умолчанию первые четыре |

Справочники не меняются — кэшируй на сессию.

---

## Чего MCP не умеет

Это не «сломано», а граница инструмента. Всё перечисленное уходит в `10_launch_log.md` списком ручной работы.

### Ломает автоматизацию — обязательно предупреди маркетолога

| Возможность | Почему важно |
|---|---|
| **Автотаргетинг (`RelevanceMatch`)** | В ЕПК на Поиске и в Картах он **обязателен** (нужна ≥1 категория запросов). MCP им не управляет → после заливки включается руками, иначе кампания не отработает как задумано |
| **Общие минус-листы (Библиотека минус-фраз)** | До 30 наборов на аккаунт, до 3 на кампанию. MCP не умеет → «аккаунт-уровень» минусов схлопывается в минус-фразы каждой кампании (см. `negative-keywords-builder.md`) |
| **Пакетные стратегии** | Общий пул обучения на несколько РК. Заводится только в интерфейсе |
| **Временной таргетинг** | Расписание показов и почасовые коэффициенты |

### Элементы объявления

Кнопка действия (№304), цена (№323), промоакция (№324), карусель (№306) — полей нет. Скилл их проектирует на Шаге 8, добавляются вручную.

**Видео:** `ads_add_responsive` принимает `video_extension_ids`, но создать видео нечем (`AdVideos` / `Creatives` не обёрнуты) — ID взять негде. Видео добавляются через интерфейс.

### Аудитории и сервисное

- `RetargetingLists` (создание условий подбора аудитории) и `AudienceTargets` — нет. `bidmodifiers_retargeting` работает только с условиями, созданными в кабинете.
- Профили организаций, Турбо-страницы, товарные фиды, смарт-креативы — не создаются; ID (`business_id`, `turbo_page_id`) принимаются, если получены иначе.
- Архивация / разархивация — нет (`campaigns_delete` = перенос в архив, это другое).
- Типы кампаний кроме `TEXT` и `UNIFIED` читаются, но не создаются.

### Вне зоны MCP по определению

Wordstat (частотность) — `scripts/wordstat_api.py`, отдельный API и токен. Создание целей Метрики — Metrika Management API, `metrika-goals-setup.md`. MCP нужен только на **привязке** счётчика и целей к кампании, и это он умеет.

---

## Подключение

### Проверка доступности

Позови любой читающий инструмент, например `campaigns_get` с `limit: 1`. Не отвечает — запусти установщик:

```bash
python -m scripts.setup_yandex_direct_mcp \
  --mcp-path "<путь к папке yandex-direct-mcp>" \
  --mode sandbox \
  --token <SANDBOX_TOKEN>
```

Скрипт сам найдёт `claude_desktop_config.json`, сделает бэкап и допишет блок `mcpServers.yandex-direct`. Скажи маркетологу: «закрой Claude Desktop полностью и открой заново, потом вернись и скажи "продолжаем"». **Сам MCP не запускай.**

### Режимы

**A. Sandbox** — рекомендуется на тесте.
`YANDEX_DIRECT_TOKEN=<sandbox_oauth>`, `YANDEX_DIRECT_SANDBOX=true`. Реальных списаний нет. Токен: https://oauth.yandex.ru → приложение → разрешение `direct:api`.

**B. Production по OAuth.**
`YANDEX_DIRECT_TOKEN=<production_oauth>`, `YANDEX_DIRECT_SANDBOX=false`. Требует одобренной заявки на API-доступ (1–3 рабочих дня для новых приложений).

**C. Прокси Click.ru** — без OAuth Яндекса.
`CLICK_RU_PROXY=true`, `CLICK_RU_TOKEN=<X-Auth-Token>`, `CLICK_RU_CLIENT_LOGIN=<логин Директа>`, опц. `CLICK_RU_USER_ID` для мастер-аккаунтов. Заявка на API не нужна.
⚠️ Работает только в production (песочница несовместима — сервер не стартует) и **`forecast_bids` недоступен**.

### Требования

Bun 1.1+ в PATH (Windows: `irm bun.sh/install.ps1 | iex`), папка MCP скачана, `bun install` выполнен, Claude Desktop 0.7+. Установщик проверит это до правки конфига.

### Безопасность

- **Никогда не сохраняй OAuth-токен в артефакты скилла.**
- Дефолт — sandbox. Production только с явным «да» от маркетолога.
- Кампании остаются в DRAFT. Активация — только руками маркетолога.

---

## Ссылки

- API Директа v5: https://yandex.ru/dev/direct/doc/ru/concepts/about
- OAuth: https://yandex.ru/dev/direct/doc/dg/concepts/auth-token-docpage/
- Click.ru API: https://api.click.ru/V0/docs/
- Bun: https://bun.sh
