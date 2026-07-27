# Чего не хватает в MCP `yandex-direct` (gap-анализ против API Яндекс.Директа v5)

> Дата анализа: 2026-06-26. Сверено с живой документацией Яндекс.Директа.
> Источник по MCP: код в `E:\AI\yandex-direct-mcp` (30 инструментов).
> Обзор API: https://yandex.ru/dev/direct/doc/ru/concepts/about (RU) · https://yandex.com/dev/direct/doc/en/concepts/overview (EN).

---

## TL;DR — главное за 30 секунд

1. **Три вещи, про которые вы спросили, действительно недоступны** через MCP: быстрые ссылки, уточнения и отображаемая ссылка. Подтверждено по коду — в обёртке объявления ([`ads.ts`](../../yandex-direct-mcp/src/tools/ads.ts)) этих полей нет, а отдельных сервисов для быстрых ссылок и уточнений MCP вообще не регистрирует.

2. **Но «труба» уже всё умеет.** HTTP-клиент MCP ([`client.ts`](../../yandex-direct-mcp/src/client.ts), метод `call(service, method, params)`) может дёрнуть **любой** метод API v5, и Click.ru-прокси пропускает весь API. То есть проблема не в доступе к Яндексу, а в том, что для нужных сущностей просто **не написаны инструменты-обёртки**. Это дописываемо.

3. **Кроме ваших трёх пунктов не хватает ещё ~20 сервисов API** — включая критичные для вашего же пайплайна: установку ставок (`KeywordBids`), выбор стратегии и привязку целей Метрики к кампании, общие минус-листы аккаунта (`NegativeKeywordSharedSets`), аудитории РСЯ (`AudienceTargets`/`RetargetingLists`) и оценку охвата (`KeywordsResearch`).

4. **Нестыковка в ваших reference-файлах.** В [`mcp-account-integration.md`](mcp-account-integration.md) (Use case 2) предполагается универсальный тул `yandex_direct_api_call` для вызова `keywordbids` и т.п. — **в реальном MCP такого тула нет**. Либо его надо добавить (это самый дешёвый способ закрыть сразу всё), либо поправить reference.

---

## Что MCP сейчас умеет (база для сравнения)

| Группа | Инструменты MCP |
|---|---|
| Campaigns | get / add / update / delete / suspend / resume |
| AdGroups | get / add / update / delete |
| Ads | get / add / update / delete / suspend / resume / moderate |
| AdImages | add (с кропом) / get |
| BidModifiers | demographics / get |
| Keywords | get / add / update / delete / suspend / resume |
| Reports | campaign / ad / search_queries |
| Dictionaries | regions / currencies / interests / all |

Всего 8 сервисов API из ~28. Дальше — что осталось за бортом.

---

## Часть 1. То, что вы назвали напрямую

### 1.1. Быстрые ссылки (Sitelinks / быстрые ссылки)

- **Что это.** Набор из 2–8 доп. ссылок под объявлением («Цены», «Доставка», «Отзывы»). Повышает CTR и занимает больше места в выдаче.
- **Как устроено в API.** Сначала создаёте **набор** быстрых ссылок отдельным сервисом `Sitelinks` (методы `add` / `get` / `delete`), получаете `SitelinkSetId`, и затем кладёте этот ID в поле объявления `SitelinkSetId`.
- **Пробел в MCP.** Сервиса `Sitelinks` нет вообще; поля `SitelinkSetId` нет в `ads_add`/`ads_update`. → **Создать нельзя, привязать нельзя.**
- **Документация:** https://yandex.ru/dev/direct/doc/ru/sitelinks/sitelinks

### 1.2. Уточнения (Callouts / уточнения)

- **Что это.** Короткие приписки-преимущества под объявлением («Гарантия 2 года», «Работаем 24/7»). Не кликабельны, но добавляют доверия и площадь.
- **Как устроено в API.** Уточнения — это «расширения»: создаются сервисом `AdExtensions` (методы `add` / `get` / `delete`), на выходе — ID расширений, которые кладутся в объявление массивом `AdExtensionIds` (до 50 шт.). Отдельного поля `CalloutIds` нет — всё идёт через `AdExtensionIds`.
- **Пробел в MCP.** Сервиса `AdExtensions` нет; поля `AdExtensionIds` нет в обёртке объявления. → **Создать нельзя, привязать нельзя.**
- **Документация:** https://yandex.ru/dev/direct/doc/ru/adextensions/adextensions

### 1.3. Отображаемая ссылка (DisplayUrlPath / отображаемая ссылка)

- **Что это.** «Красивый хвост» к домену в объявлении (`site.ru/Доставка-за-час`). До 20 символов. Чисто поле объявления — отдельный сервис не нужен.
- **Как устроено в API.** Поле `DisplayUrlPath` прямо в объекте `TextAdAdd` / `TextAdUpdate`.
- **Пробел в MCP.** Поле просто не прокидывается в `ads_add`/`ads_update`. Самый простой из трёх пунктов — это добавление одной строки в обёртку, новый сервис не нужен.
- **Документация:** https://yandex.ru/dev/direct/doc/ru/ads/add (структура `TextAdAdd`).

> ⚠️ Важно: ваши reference-файлы местами передают `display_url_path` в `ads_add` (например [`yandex-direct-mcp.md`](yandex-direct-mcp.md) стр. 50). По факту MCP этот параметр **молча игнорирует** (см. [`ads.ts`](../../yandex-direct-mcp/src/tools/ads.ts) — в `textAd` он не попадает).

---

## Часть 2. Поля объявления, которых нет в обёртке `ads_add` / `ads_update`

Обёртка собирает только `Title / Title2 / Text / Href / Mobile / AdImageHash`. Полный список того, что есть у `TextAdAdd` в API, но потеряно в MCP:

| Поле API | Что даёт | Нужен доп. сервис? |
|---|---|---|
| `SitelinkSetId` | быстрые ссылки | да — `Sitelinks` |
| `AdExtensionIds` | уточнения (и др. расширения) | да — `AdExtensions` |
| `DisplayUrlPath` | отображаемая ссылка | нет, просто поле |
| `VCardId` | визитка (адрес/телефон) — **устаревает** | да — `VCards` (legacy) |
| `BusinessId` | профиль организации (Яндекс Бизнес) — современная замена визитке | да — `Businesses` |
| `TurboPageId` | Турбо-страница как посадочная | да — `TurboPages` |
| `PriceExtension` | цена прямо в объявлении | нет, объект-поле |
| `VideoExtension` (`CreativeId`) | видеодополнение | да — `Creatives` |

Плюс: обёртка умеет **только текстово-графические объявления** (`TextAd`). Не поддержаны типы `DynamicTextAd` (динамические), `MobileAppAd` (реклама приложений), `CpcVideoAd`, смарт-баннеры и т.п. И нет методов `archive` / `unarchive`.

- **Документация по объявлению:** https://yandex.ru/dev/direct/doc/ru/ads/ads · добавление — https://yandex.ru/dev/direct/doc/ru/ads/add

---

## Часть 3. Целые сервисы API, которых нет в MCP

Сгруппировано по приоритету «для вашего пайплайна».

### 🔴 Высокий приоритет — ломает заявленную методологию агентства

| Сервис | Что даёт | Зачем вам конкретно | Документация |
|---|---|---|---|
| **KeywordBids** | Установка/чтение ставок на ключи и группы, данные живого аукциона | Без него ключи висят на дефолтной ставке (~0.30 ₽) и их **нельзя поднять до целевой**. Прямо ломает скилл `bidding-strategy`. Также нужен для оценки CPC (`frequency-calculator`). | https://yandex.ru/dev/direct/doc/ru/keywordbids/keywordbids |
| **NegativeKeywordSharedSets** | Общие (аккаунт-уровня) наборы минус-слов | Скилл `negative-keywords-builder` строит минусы «уровня аккаунта» — без этого сервиса их приходится дублировать в каждую кампанию руками. | https://yandex.ru/dev/direct/doc/ru/negativekeywordsharedsets/negativekeywordsharedsets |
| **AudienceTargets** | Нацеливание групп на аудитории/ретаргетинг | Базовая настройка РСЯ и ретаргетинга. Сейчас собрать аудиторную кампанию через MCP нельзя. | https://yandex.ru/dev/direct/doc/ru/audiencetargets/audiencetargets |
| **RetargetingLists** | Условия подбора аудитории (сегменты Метрики/правила) | Нужны как «кирпичи» для `AudienceTargets`. Без них ретаргетинг в РСЯ недоступен. | https://yandex.ru/dev/direct/doc/ru/retargetinglists/retargetinglists |
| **KeywordsResearch** | Оценка наличия/охвата спроса по фразам | Частично закрывает потребность `frequency-calculator` (в API v5 классического `Forecast.GetForecast` нет — это правильно отмечено в вашем `mcp-account-integration.md`). | https://yandex.ru/dev/direct/doc/ru/keywordsresearch/keywordsresearch |

### 🟡 Средний приоритет — расширения объявлений и посадочные

| Сервис | Что даёт | Зачем вам | Документация |
|---|---|---|---|
| **Sitelinks** | Наборы быстрых ссылок | Ваш пункт 1.1 | https://yandex.ru/dev/direct/doc/ru/sitelinks/sitelinks |
| **AdExtensions** | Уточнения | Ваш пункт 1.2 | https://yandex.ru/dev/direct/doc/ru/adextensions/adextensions |
| **Businesses** | Профили организаций (Яндекс Бизнес): адрес, телефон, часы | Современная замена визитке; контакты в объявлении | https://yandex.ru/dev/direct/doc/ru/businesses/businesses |
| **VCards** | Визитки (адрес/телефон) — **legacy**, вытесняется `Businesses` | Только если аккаунт ещё на старых визитках | (раздел устаревает; см. `Businesses`) |
| **TurboPages** | Турбо-страницы как быстрые посадочные | Полезно для лидформ без сайта | https://yandex.ru/dev/direct/doc/ru/turbopages/turbopages |
| **Leads** | Выгрузка лидов с Турбо-страниц/лидформ | Сбор заявок, если используете Турбо | https://yandex.ru/dev/direct/doc/ru/leads/leads |

### 🟢 Для РСЯ / медийки / динамики и сервисные

| Сервис | Что даёт | Документация |
|---|---|---|
| **Creatives** | Креативы для смарт-баннеров и графических объявлений | https://yandex.ru/dev/direct/doc/ru/creatives/creatives |
| **AdVideos** | Видео для видеодополнений | https://yandex.ru/dev/direct/doc/ru/advideos/advideos |
| **Feeds** | Товарные фиды (динамика, смарт-баннеры, товарная кампания) | https://yandex.ru/dev/direct/doc/ru/feeds/feeds |
| **DynamicTextAdTargets** | Условия нацеливания динамических объявлений | https://yandex.ru/dev/direct/doc/ru/dynamictextadtargets/dynamictextadtargets |
| **SmartAdTargets** | Условия нацеливания смарт-баннеров | https://yandex.ru/dev/direct/doc/ru/smartadtargets/smartadtargets |
| **Bids** | Старое управление ставками (для legacy-стратегий) | https://yandex.ru/dev/direct/doc/ru/bids/bids |
| **Changes** | «Что изменилось с момента X» — чтобы не перечитывать весь аккаунт | https://yandex.ru/dev/direct/doc/ru/changes/changes |
| **Clients** | Настройки клиента: дневной лимит, уведомления, валюта | https://yandex.ru/dev/direct/doc/ru/clients/clients |
| **AgencyClients** | Управление клиентами агентства (создание субаккаунтов) | https://yandex.ru/dev/direct/doc/ru/agencyclients/agencyclients |

---

## Часть 4. Узкие места ВНУТРИ уже существующих инструментов

Сервис есть, но обёртка покрывает 10–20% его возможностей.

### Campaigns (создание/обновление) — самый болезненный

Обёртка [`campaigns.ts`](../../yandex-direct-mcp/src/tools/campaigns.ts) жёстко зашивает:
- только тип `TextCampaign`;
- стратегию `HIGHEST_POSITION` на поиске + сеть выключена (`SERVING_OFF`);
- только дневной бюджет в режиме `DISTRIBUTED`.

Чего нельзя задать, хотя в API есть:
- **Выбор стратегии торгов** (`WB_MAXIMUM_CLICKS`, `WB_MAXIMUM_CONVERSION_RATE`, `AVERAGE_CPC`, `AVERAGE_CPA`, `PAY_FOR_CONVERSION` и др.) — прямо ломает скилл `bidding-strategy` и всю «эволюцию автостратегий».
- **Недельный бюджет** (`WeeklySpendLimit`).
- **Привязка счётчика Метрики и целей** (`Metrika`/`PriorityGoals`) — ломает скилл `metrika-goals-setup`: без целей автостратегии не на чем учиться.
- **Временной таргетинг** (`TimeTargeting`) — расписание показов.
- Другие типы кампаний: `SmartCampaign`, `DynamicTextCampaign`, `MobileAppCampaign`, `CpmBannerCampaign`.
- Методы `archive` / `unarchive`.

Док: https://yandex.ru/dev/direct/doc/ru/campaigns/campaigns

### Keywords

- **Нет установки ставки** (это отдельный сервис `KeywordBids`). `keywords_update` принимает только новый текст.
- Нет управления **автотаргетингом** (`RelevanceMatch`) на уровне группы.

Док: https://yandex.ru/dev/direct/doc/ru/keywords/keywords

### BidModifiers (корректировки ставок)

Обёртка [`bidModifiers.ts`](../../yandex-direct-mcp/src/tools/bidModifiers.ts) умеет только демографию (пол/возраст) + чтение. В API есть ещё корректировки по:
- регионам, типу устройства (мобайл/десктоп/смарт-ТВ), времени (`TimeTargeting`-bids), ретаргетингу/аудиториям, видеодополнениям и др.;
- плюс отсутствуют общие методы `set` / `add` / `delete` / `toggle`.

Док: https://yandex.ru/dev/direct/doc/ru/bidmodifiers/bidmodifiers

### Ads

- Только `TextAd` (см. Часть 2), нет `archive`/`unarchive`.

### Reports

- Только 3 «зашитых» пресета (`campaign` / `ad` / `search_queries`). Полный Reports API даёт произвольный набор полей, фильтры, типы отчётов (включая `REACH_AND_FREQUENCY` для медийки) и кастомные периоды.
- Док: https://yandex.ru/dev/direct/doc/ru/reports/reports

---

## Часть 5. Как пробелы бьют по вашим скиллам (карта зависимостей)

| Скилл пайплайна | Чего ему не хватает в MCP |
|---|---|
| `bidding-strategy` | Выбор стратегии в `campaigns_*`; установка ставок `KeywordBids`; оплата за конверсию (нет привязки целей) |
| `metrika-goals-setup` | Привязка счётчика и `PriorityGoals` к кампании (`campaigns_*` не умеет) |
| `negative-keywords-builder` | `NegativeKeywordSharedSets` (минусы уровня аккаунта); кросс-минусация всё ещё ручная |
| `frequency-calculator` | `KeywordsResearch` для охвата; `KeywordBids.get` для CPC по живому аукциону |
| РСЯ-часть (`wordstat-filter`, `rsya-creatives`) | `AudienceTargets` + `RetargetingLists` + `Creatives` + `AdVideos` |
| Объявления (`ad-copywriting`, `usp-generator`) | Быстрые ссылки, уточнения, отображаемая ссылка, цена, видеодополнения |

---

## Часть 6. Хорошая новость и рекомендация

**Технически добавить всё это дёшево.** Клиент уже универсален: `client.call(service, method, params)` работает с любым сервисом v5, а Click.ru-прокси не ограничивает список сервисов. Каждая недостающая возможность = новый файл-обёртка в `src/tools/` по образцу существующих + регистрация в реестре.

### Рекомендуемый порядок внедрения

1. **Универсальный passthrough-тул `yandex_direct_api_call({ service, method, params })`.** Один инструмент закрывает разом ВСЕ дыры (его уже зовут ваши reference-файлы, но в коде его нет). Это самый быстрый способ — за полдня получить доступ ко всему API. Минус: agent'у нужно знать структуру запросов Яндекса (но документация по ссылкам ниже это закрывает).
2. **`DisplayUrlPath`** в `ads_add`/`ads_update` — одна строка, ваш пункт 1.3.
3. **`KeywordBids`** (set/get) — без него стратегия торгов мертва.
4. **`Sitelinks` + `AdExtensions`** + поля `SitelinkSetId`/`AdExtensionIds` в объявлении — ваши пункты 1.1 и 1.2.
5. **Стратегия + Метрика-цели** в `campaigns_add/update`.
6. **`NegativeKeywordSharedSets`**, затем РСЯ-блок (`AudienceTargets`, `RetargetingLists`, `Creatives`).

> Подход «делаем что можем, остальное — в `10_launch_log.md` как “доделать руками”» у вас уже описан в [`mcp-account-integration.md`](mcp-account-integration.md) (Use case 5). Этот документ — карта того, что нужно убрать из ручного списка.

---

## Приложение. Все ссылки одним списком

**Обзор и справочник:**
- Обзор API v5 (RU): https://yandex.ru/dev/direct/doc/ru/concepts/about
- Обзор API v5 (EN): https://yandex.com/dev/direct/doc/en/concepts/overview
- История изменений: https://yandex.ru/dev/direct/doc/changelog/index.html

**Ваши три пункта:**
- Быстрые ссылки — Sitelinks: https://yandex.ru/dev/direct/doc/ru/sitelinks/sitelinks
- Уточнения — AdExtensions: https://yandex.ru/dev/direct/doc/ru/adextensions/adextensions
- Отображаемая ссылка — поле `DisplayUrlPath` в `TextAdAdd`: https://yandex.ru/dev/direct/doc/ru/ads/add

**Объявления и расширения:**
- Ads (объект/методы): https://yandex.ru/dev/direct/doc/ru/ads/ads
- Businesses (профиль организации): https://yandex.ru/dev/direct/doc/ru/businesses/businesses
- TurboPages: https://yandex.ru/dev/direct/doc/ru/turbopages/turbopages
- Creatives: https://yandex.ru/dev/direct/doc/ru/creatives/creatives
- AdVideos: https://yandex.ru/dev/direct/doc/ru/advideos/advideos
- AdImages: https://yandex.ru/dev/direct/doc/ru/adimages/adimages

**Ставки, ключи, минусы:**
- KeywordBids (ставки): https://yandex.ru/dev/direct/doc/ru/keywordbids/keywordbids
- Bids (legacy): https://yandex.ru/dev/direct/doc/ru/bids/bids
- Keywords: https://yandex.ru/dev/direct/doc/ru/keywords/keywords
- KeywordsResearch (охват): https://yandex.ru/dev/direct/doc/ru/keywordsresearch/keywordsresearch
- NegativeKeywordSharedSets (общие минусы): https://yandex.ru/dev/direct/doc/ru/negativekeywordsharedsets/negativekeywordsharedsets
- BidModifiers (корректировки): https://yandex.ru/dev/direct/doc/ru/bidmodifiers/bidmodifiers

**РСЯ / аудитории / динамика:**
- AudienceTargets: https://yandex.ru/dev/direct/doc/ru/audiencetargets/audiencetargets
- RetargetingLists: https://yandex.ru/dev/direct/doc/ru/retargetinglists/retargetinglists
- Feeds: https://yandex.ru/dev/direct/doc/ru/feeds/feeds
- DynamicTextAdTargets: https://yandex.ru/dev/direct/doc/ru/dynamictextadtargets/dynamictextadtargets
- SmartAdTargets: https://yandex.ru/dev/direct/doc/ru/smartadtargets/smartadtargets

**Кампании / сервисные:**
- Campaigns (стратегии, бюджет, Метрика, время): https://yandex.ru/dev/direct/doc/ru/campaigns/campaigns
- AdGroups: https://yandex.ru/dev/direct/doc/ru/adgroups/adgroups
- Changes: https://yandex.ru/dev/direct/doc/ru/changes/changes
- Clients: https://yandex.ru/dev/direct/doc/ru/clients/clients
- AgencyClients: https://yandex.ru/dev/direct/doc/ru/agencyclients/agencyclients
- Leads: https://yandex.ru/dev/direct/doc/ru/leads/leads
- Reports: https://yandex.ru/dev/direct/doc/ru/reports/reports
- Dictionaries: https://yandex.ru/dev/direct/doc/ru/dictionaries/dictionaries
