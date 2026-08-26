# Yandex Direct MCP — справочник инструментов и подключения

**Единственный источник правды о том, что умеет MCP и как его звать.** Последовательность заливки кампании — в `mcp-account-integration.md` (Use case 5), здесь только контракты.

MCP-сервер `yandex-direct-mcp` (Bun/TypeScript) — мост к API Яндекс.Директа. Версия **0.5.0, 50 инструментов**, API **v501** по умолчанию (v5 не поддерживает ЕПК). Готовится 0.5.1 — состав инструментов тот же, меняется только поведение чтения без фильтров и с длинными списками кампаний (см. «Чтение: всегда передавай фильтр»).

Скилл ходит в **хостовый инстанс** `https://direct-mcp.aihub.click.ru/mcp` (авторизация — токен click.ru): локально ничего не запускается. Локальный stdio-запуск — фолбек для разработки сервера, см. «Подключение».

Ниже везде указано **короткое имя** инструмента (`campaigns_get`, `ads_add_responsive` и т.д.). Как оно выглядит в сессии — зависит от среды: в одной инструменты видны с префиксом `mcp__yandex-direct__`, в другой — иначе. Ищи по короткому имени.

**Способность вызывать MCP-инструменты необязательна.** Её нет — весь пакет работает по ветке без live-данных, см. «Что нужно от среды» в корневом `SKILL.md` и вводную часть `mcp-account-integration.md`.

---

## Общие правила — прочти до первого вызова

### Кабинет: `client_login` в каждом вызове

Инструменты, относящиеся к кабинету, принимают необязательный `client_login` — логин кабинета
Директа. Без него вызов уходит в кабинет по умолчанию текущего подключения, а их на одном токене
бывает несколько. **Выбор кабинета — Шаг 0.5**, `mcp-account-integration.md` → Use case 0.
Выбранный логин лежит в `_state.json` → `direct_client_login` и подставляется в каждый
вызов, включая читающие.

Исключение — три инструмента, не привязанные к конкретному кабинету (`accountAgnostic` в мосте),
`client_login` они не принимают: `accounts_get`, `forecast_bids` и справочники `dictionaries_*`.

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

⚠️ **Длинным ID нельзя доверять как точным.** На текущем коннекторе 19-значные ID объектов (`ad_id`, `campaign_id`, `adgroup_id` и т.п.) приходят **округлёнными**: коннектор обрабатывает их как число двойной точности (хранит ~16 значащих цифр), и хвост теряется — например, `1919477746730333000` с нулями на конце. Искажение стабильно и на чтении из кабинета. Следствие: по такому ID нельзя ни адресно обновить объект, ни надёжно сопоставить его с интерфейсом Директа. Пока баг не исправлен (`TASK-mcp-connector-fixes.md`, Баг 1) — фиксируй ID как «ориентировочный», сверяй с интерфейсом, а состояние заливки проверяй через `campaigns_get`, а не по записанному ID.

### `dry_run` — предпросмотр без записи

Все инструменты, меняющие кабинет, принимают `dry_run: true`. Возвращается тело запроса, которое ушло бы в Директ, **ничего не создавая и не изменяя**. При этом все проверки выполняются полностью — то есть предпросмотр ловит ошибки данных до записи.

Используй на гейтах Шага 10: сначала весь конвейер в `dry_run`, показываешь маркетологу сводку, после «ОК» — реальная заливка.

Нет `dry_run` у читающих инструментов, отчётов и `forecast_bids` (они и так ничего не меняют).

### Баллы API

В каждом ответе поле `units` — потрачено / осталось / суточный лимит (~160k). Типичный пайплайн — 500–2000 баллов. Справочники в цикле не звать.

### Чтение: всегда передавай фильтр, длинные списки кампаний режь по 10

Два правила, которые ломают чтение на реальном кабинете. Проверено живьём на кабинете из 17 кампаний (прогон через прокси Click.ru, 6 авг 2026).

**1. Хотя бы один фильтр обязателен.** У `adgroups_get`, `ads_get`, `keywords_get`, `keywordbids_get`, `bidmodifiers_get`, `adimages_get` вызов без единого фильтра формирует пустой `SelectionCriteria`, и API отвечает кодом 8000. Исключение — `campaigns_get`: у него внутри защита, без фильтров он сам подставляет все `States` и честно возвращает весь кабинет. **Порядок работы:** сначала `campaigns_get`, из него берёшь `campaign_ids`, дальше всё остальное читаешь по ним.

**Отчёты тоже.** `report_campaign`, `report_ad`, `report_search_queries`, `report_custom`
без `campaign_ids` на подключении в режиме прокси click.ru отвечают тем же кодом 8000
(`SelectionCriteria cannot contain an array`). На прямом OAuth проходят и без фильтра —
но полагаться на это нельзя: режим определяется подключением, а не кодом скилла. **Всегда
передавай `campaign_ids`**, взяв их из `campaigns_get`.

Исключения из правила — два: `campaigns_get` (внутри подставляет все `States`) и
`adextensions_get` (без фильтров отдаёт все активные уточнения).

**2. `CampaignIds` — не больше 10 за вызов.** Длиннее — код 4001. Читай порциями по 10 кампаний и склеивай результат сам.

Отдельный случай — `adimages_get`: единственный его фильтр это `ad_image_hashes`, а хеши заранее обычно неизвестны. На 0.5.0 инструмент поэтому пригоден только для проверки уже известных картинок — сохраняй хеши, которые вернул `adimages_add`, и не рассчитывай получить список аккаунта.

> **Статус 0.5.1 на хостовых инстансах: не выкачен.** Прогон 26.08.2026 показал прежнее
> поведение 0.5.0 — `keywords_get` и `report_campaign` без фильтра отвечают 8000, баллы
> при этом тратятся. Соблюдай правила вручную; когда 0.5.1 доедет, они останутся верными.

### Сбои шлюза

Ошибка вида `gateway 502 ... upstream ... EOF` — это шлюз aihub, а не API Директа и не
твои данные. Правило: **один** повтор тем же телом через 5 с. Не помогло — режь пачку
(ключи, фразы) пополам и повтори. Не помогло второй раз — уходи на фолбек шага и ставь
пометку о пропуске. Повторами не долби: у мутирующих вызовов слепой ретрай создаёт дубли.

Отличать от отказа API: у отказа есть `error_code` и `units` в конверте, у сбоя шлюза их нет.

---

## Аккаунты

### `accounts_get`

Список кабинетов, доступных подключению. Единственный параметр — `include_linked`
(по умолчанию `false`: кабинеты click.ru с `createdType=LINKED` скрыты, запросы к ним
отклоняются; при скрытии в ответ добавляются `hidden_linked` и `hidden_note`).

Возвращает `source` — по нему определяется режим подключения:
`"click.ru"` — прокси (нет `forecast_bids`, отчёты требуют `campaign_ids`),
`"yandex-direct"` / `"yandex-direct-agency"` — прямой OAuth (доступно всё; агентский токен
отдаёт список клиентов агентства).

Зови первым вызовом пайплайна. Он же — проверка связности. Сам `accountAgnostic`, `client_login`
не принимает.

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
| `daily_budget` | number | Дневной бюджет в валюте, **минимум 300 ₽**. **Только для ручных стратегий** |
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

**В сетях (для ЕПК/`UNIFIED`) — только автостратегии.** Допустимы `WB_MAXIMUM_CLICKS` (авто «Максимум кликов»), конверсионные (`PAY_FOR_CONVERSION`, `AVERAGE_CPA`, `AVERAGE_CRR`, `PAY_FOR_CONVERSION_CRR`, `*_MULTIPLE_GOALS`, `MAX_PROFIT`) и `SERVING_OFF`.

> ⚠️ **`MAXIMUM_COVERAGE` («максимальный охват»), `NETWORK_DEFAULT` и ручные ставки в сетях для ЕПК Директ отклоняет.** Яндекс отключил ручное управление ставками в РСЯ и поиск+РСЯ ещё в 2024 году (три этапа: с 22.04.2024 — запрет создавать/возобновлять/переключать, с 20.05.2024 — запрет редактировать ставки, июнь 2024 — остановка активных РК с ручным управлением). Для сетей остались ровно две автостратегии — «Максимум конверсий» и авто «Максимум кликов». Источник: [eLama — «Яндекс Директ отключает ручное управление ставками в РСЯ»](https://elama.ru/blog/yandeks-direkt-otklyuchaet-ruchnoe-upravlenie-stavkami-vrsya-kak-podgotovitsya-ichto-delat/). Значения `NETWORK_DEFAULT` / `MAXIMUM_COVERAGE` остаются для легаси-типов кампаний, но не для `UNIFIED`.

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

⚠️ **`network_bid` к сетевой стороне ЕПК/РСЯ неприменим** — ручные ставки в сетях Яндекс отключил в 2024 (см. врезку в «Стратегии торгов»). Сеть внутри ЕПК всегда ведёт автостратегия; в сетевой части управляй приоритетом (`strategy_priority`), а не ставкой.

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

Это про деньги, не про спрос: частотность запросов — Wordstat через MCP `yandex-wordstat` (`references/wordstat-mcp.md`; фолбек — `scripts/wordstat_api.py`).

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

⚠️ **На хостовом MCP картинки не заливаются.** `adimages_add` принимает только `file_path`
на диске сервера, а файлы маркетолога хосту недоступны; URL-параметра в схеме нет
(сверено 26.08.2026, MCP 0.5.0 — параметров ровно пять: `file_path`, `name`, `crop`,
`crop_offset`, `dry_run`). Поэтому: объявление заливается **без** `image_hashes`, а добавление
картинок уходит в `10_launch_log.md` списком ручной работы (интерфейс Директа или Коммандер).
Появится URL-параметр — вернуть сюда ветку загрузки по ссылке.

### `adimages_get`

Список загруженных изображений аккаунта — для переиспользования.

⚠️ На 0.5.0 работает только с `ad_image_hashes`: без них уходит пустой `SelectionCriteria` и API отвечает кодом 8000. Сохраняй хеши из `adimages_add`. С 0.5.1 вызов без хешей возвращает полный список.

---

## Справочники

| Инструмент | Что отдаёт |
|---|---|
| `dictionaries_regions` | Регионы: `GeoRegionId`, `GeoRegionName`, `GeoRegionType`, `ParentId`. Ответ **2,87 МБ / 104 072 строки** — в большинстве сред обрежется клиентом. Основной путь — шорт-лист регионов в `mcp-account-integration.md` → Use case 4 |
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

Wordstat (частотность) — отдельный контур: MCP `yandex-wordstat` (`references/wordstat-mcp.md`), фолбек `scripts/wordstat_api.py` со своим токеном Cloud. Создание целей Метрики — Metrika Management API, `metrika-goals-setup.md`. MCP нужен только на **привязке** счётчика и целей к кампании, и это он умеет.

---

## Подключение

### Проверка доступности

Позови `accounts_get({})` — он и связность проверит, и режим подключения покажет, и список кабинетов даст (Use case 0). Не отвечает или сервера `yandex-direct` нет в сессии — запусти установщик:

```bash
python -m scripts.setup_yandex_direct_mcp \
  --token <CLICK_RU_API_TOKEN> --client-login <ЛОГИН_ДИРЕКТА> --target all
```

**Установщик пишет хостовые серверы aihub.click.ru** в конфиги Cursor (`~/.cursor/mcp.json`), Claude Code (`.mcp.json`) и Claude Desktop (через stdio-мост `mcp-remote`). Ничего локально не запускается, Bun не нужен. Заодно подключается `yandex-wordstat` (нужен на Шагах 1 и 3). Скажи маркетологу: «перезапусти клиента, потом вернись и скажи "продолжаем"». **Сам MCP не запускай.**

URL, заголовки, форматы конфигов и проверка связи — `docs/hosted-mcp-setup.md` репозитория пакета. Если в среде нет запуска кода — скопируй блок из справочника в конфиг клиента руками. Нет и такой возможности — скажи прямо: «MCP `yandex-direct` не подключён — продолжаю без live-данных» и иди по ветке без MCP с пометкой о пропуске.

### Режим доступа на хосте

Хостовый инстанс работает **в режиме прокси Click.ru**:

- авторизация — API-токен click.ru в заголовке `Authorization: Bearer <токен>` (шлюз принимает и `X-Auth-Token`); токен создаётся в профиле https://click.ru/userinfo.html → «API Token»;
- аккаунт Директа — заголовок `X-Client-Login`; у мастер-аккаунтов click.ru добавляется `X-Click-Ru-User-Id`;
- заявка на API-доступ Яндекса не нужна, OAuth Яндекса не нужен;
- работает только production-кабинет (песочница через Click.ru несовместима);
- **`forecast_bids` недоступен** — Шаг 2 идёт через живой аукцион (`keywordbids_get`), справочник ниш или через второе подключение в прямом OAuth-режиме, если оно есть в сессии (Use case 3);
- **файлы маркетолога хосту недоступны** — см. предупреждение у `adimages_add`.

### Локальный stdio (фолбек для разработки сервера)

Свой инстанс (клон `ai-hub-open/yandex-direct-mcp`, Bun 1.1+, `bun install`, `bun run src/index.ts`) подключается тем же блоком `mcpServers`, но с `command`/`args`/`env` вместо `url`/`headers` — см. README репозитория сервера. Локально доступны режимы sandbox (`YANDEX_DIRECT_TOKEN` + `YANDEX_DIRECT_SANDBOX=true`, без реальных списаний; `forecast_bids` работает) и прямой OAuth. Для скилла разницы нет: он ищет сервер по имени `yandex-direct` и коротким именам инструментов.

### Безопасность

- **Никогда не сохраняй токены (click.ru, OAuth) в артефакты скилла.**
- Хостовый режим — всегда production. Действуй по гейтам и через `dry_run`.
- Кампании остаются в DRAFT. Активация — только руками маркетолога.

---

## Ссылки

- API Директа v5: https://yandex.ru/dev/direct/doc/ru/concepts/about
- OAuth: https://yandex.ru/dev/direct/doc/dg/concepts/auth-token-docpage/
- Click.ru API: https://api.click.ru/V0/docs/
- Bun: https://bun.sh
