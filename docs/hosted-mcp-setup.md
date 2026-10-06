# Хостовые MCP aihub.click.ru — подключение скиллов

Единая инструкция, как подключить скилы `yandex-direct-manager` и `vk-ads-manager` к хостовым MCP-серверам. Локальный запуск (Bun, клон репозитория) больше не нужен — серверы уже подняты на стороне aihub.

## Серверы

| Сервер в конфиге | URL | Что даёт |
|---|---|---|
| `yandex-direct` | `https://direct-mcp.aihub.click.ru/mcp` | 50 инструментов Direct API v501 (кампании, ЕПК, группы, объявления, ключи, ставки, отчёты, справочники) |
| `yandex-wordstat` | `https://wordstat-mcp.aihub.click.ru/mcp` | Частотность поисковых запросов пачкой (до 1000 фраз за вызов). Похожих запросов, ассоциаций, регионов и динамики сервер **не отдаёт** |
| `vk-ads` | `https://vkads-mcp.aihub.click.ru/mcp` | 44 инструмента VK Ads API (`vk_ads_*`: кампании, группы, объявления, аудитории, статистика) |
| `yandex-metrika` (в сессии может называться иначе, напр. `metrikaCM`) | `https://metrika-mcp.aihub.click.ru/c/<CLICK_RU_TOKEN>` (варианты адреса — в «Авторизации») | 13 инструментов `yandex_metrika_*`: счётчики, цели (с достижениями за N дней), сегменты, отчёты (таблица и динамика), клиенты Директа счётчика. Записи (`goals_add/update/delete`, `segments_add/delete`) поддерживают `dry_run`. Нужен скиллу `yandex-direct-manager` на Шагах 0.5 (разведка аккаунта), 7, 10 |
| `KeepImage` (хранилище картинок) | `https://storage.aihub.click.ru/mcp` | Временное файловое хранилище: публикует картинку → публичная ссылка без авторизации, живёт ≤2 ч. Нужно, чтобы заливать локальные креативы в Директ (`adimages_add(image_url)`) и в VK (`vk_ads_content_upload_image`). Инструменты: `storage_publish_image`, `storage_list`, `storage_info`, `storage_delete`. HTTP API для больших файлов — `PUT/POST /v1/objects` |

Корневой путь `/` отдаёт 404 — рабочий JSON-RPC endpoint именно `/mcp`. Health-check: `GET /healthz` → `OK`.

## Авторизация (проверено прогоном 19.08.2026)

Всё сводится к **одному API-токену click.ru**: профиль https://click.ru/userinfo.html → поле «API Token» → «Создать». Аккаунты Директа и VK Рекламы должны быть подключены в click.ru.

| Сервер | Заголовки на каждый запрос |
|---|---|
| `yandex-direct` | `X-Click-Ru-Token: <CLICK_RU_TOKEN>`, `X-Client-Login: <логин Директа>`; для мастер-аккаунта click.ru добавить `X-Click-Ru-User-Id`. **`Authorization: Bearer` шлюз Директа не принимает** — отвечает «Invalid credentials headers: X-Click-Ru-Token обязателен в прокси-режиме». Альтернатива для окон коннектора, где заголовков нет: токен в пути — `/c/<CLICK_RU_TOKEN>/mcp`, `/c/<CLICK_RU_TOKEN>/<user-id>/mcp` или `/c/<логин Директа>/<CLICK_RU_TOKEN>/<user-id>` |
| `yandex-wordstat` | `Authorization: Bearer <CLICK_RU_TOKEN>` (токен проверяется шлюзом через click.ru; ключ Yandex Cloud не нужен — он на стороне сервера) |
| `vk-ads` | `X-Click-Ru-Token: <CLICK_RU_TOKEN>`, `X-Click-Ru-Account-Id: <ID аккаунта VK Рекламы в click.ru>` |
| `yandex-metrika` | Токен — **в адресе**, заголовков нет. Три формы: `https://metrika-mcp.aihub.click.ru/c/<CLICK_RU_TOKEN>` — через click.ru, видны все аккаунты Яндекса с Метрикой, подключённые в click.ru; `https://metrika-mcp.aihub.click.ru/c/<CLICK_RU_TOKEN>/<аккаунт>` — то же, но закреплён один аккаунт (логин или ID интеграции Метрики в click.ru, их показывает `yandex_metrika_accounts_get`); `https://metrika-mcp.aihub.click.ru/y/<OAuth-токен Яндекса>` — прямой режим без click.ru, OAuth-токен с доступом к Метрике. Для режима click.ru **аккаунт Яндекса с Метрикой должен быть подключён в интеграциях click.ru** (инструкция: https://help.click.ru/97#connect-yandex-metrica) — иначе `yandex_metrika_accounts_get` вернёт пустой список с подсказкой «не подключена Яндекс Метрика», а остальные вызовы — ошибку. Адрес с токеном — секрет, как пароль |
| `KeepImage` | `X-Auth-Token: <CLICK_RU_TOKEN>` (или токен прямо в адресе: `/c/<CLICK_RU_TOKEN>[/<user-id>]/mcp`); для мастер-аккаунта click.ru добавить `X-Auth-UserId: <ID пользователя>`. Тот же токен click.ru, что у Директа |

Примечания:

- Список инструментов VK Ads открыт без кредов (`GET /mcp/tools`), но вызовы без заголовков возвращают ошибку «Не заданы креды VK Ads…» с перечнем нужных заголовков.
- Direct и Wordstat без токена отвечают `401 {"error":"Unauthorized"}`; с недействительным токеном — `401 click.ru: токен недействителен`.
- ID аккаунта VK Рекламы в click.ru: `GET /accounts` в https://api.click.ru/V0/docs/.
- Альтернативы click.ru для VK (готовый `X-VK-Ads-Token`, OAuth `X-VK-Ads-Client-Id` + `X-VK-Ads-Client-Secret`) сервер тоже принимает — см. его сообщение об ошибке.
- Токен click.ru — секрет. В git не коммитим: в репозитории только плейсхолдеры, реальные значения пишутся в конфиги клиентов установщиком.
- **KeepImage** обычно прописывается установщиком `setup_yandex_direct_mcp.py` (заголовком `X-Auth-Token`, см. «Автоматическая запись конфигов»). Если подключаешь **вручную через окно коннектора** (где заголовки не задать) — используй адрес с токеном в пути: `https://storage.aihub.click.ru/c/<CLICK_RU_TOKEN>/mcp` (для мастер-аккаунта — `/c/<CLICK_RU_TOKEN>/<user-id>/mcp`). Такой URL с токеном — секрет (он логируется прокси и историей), береги его как пароль. Через `mcp-remote` для Claude Desktop — блок `mcpServers.KeepImage` с `command: npx`, `args: ["-y","mcp-remote","https://storage.aihub.click.ru/mcp","--header","X-Auth-Token:${CLICK_TOKEN}"]`, `env: {"CLICK_TOKEN":"<токен>"}` (без пробела после двоеточия в `--header`; после правки — полный перезапуск Desktop). Скрипт `scripts/upload_creatives_to_storage.py` ходит в KeepImage по HTTP напрямую и коннектора не требует — ему нужен только токен `clickru` в реестре ключей.

## Автоматическая запись конфигов (рекомендуется)

Установщики лежат в скиллах и умеют цели `cursor` (глобально, `~/.cursor/mcp.json`), `cursor-project` (`.cursor/mcp.json` в текущей папке), `claude-code` (`.mcp.json` в текущей папке), `claude-desktop`, `all`:

```bash
# Директ + Wordstat + KeepImage (одна команда, все три сервера — по умолчанию --server all)
python -m scripts.setup_yandex_direct_mcp \
  --token <CLICK_RU_TOKEN> --client-login <ЛОГИН_ДИРЕКТА> \
  --target all

# VK Ads
python -m scripts.setup_vk_ads_mcp \
  --token <CLICK_RU_TOKEN> --vk-account-id <ID_АККАУНТА> \
  --target all
```

Полезные флаги: `--dry-run` (показать, что будет записано), `--remove` (удалить записи), `--click-ru-user-id` (мастер-аккаунт click.ru), `--server` (`all` по умолчанию — direct + wordstat + KeepImage; `both` — только direct + wordstat). Токен можно не передавать аргументом, если он уже сохранён через `manage_credentials set clickru`.

`setup_yandex_direct_mcp.py` по умолчанию прописывает и **KeepImage** — тем же токеном click.ru, заголовком `X-Auth-Token` (а с `--click-ru-user-id` — ещё `X-Auth-UserId`). Токен идёт заголовком, **а не в URL** `/c/<токен>/mcp`: путь с токеном логируется прокси и историей, а конфиг клиента задаёт заголовки напрямую. Ручной коннектор по адресу с токеном в пути остаётся фолбеком для сред, где заголовки не задать (см. ниже).

Установщик заодно сохраняет токен click.ru в реестр ключей (сервис `clickru`, а с `--click-ru-user-id` — ещё `clickru_user_id`), поэтому скрипт `upload_creatives_to_storage.py` работает сразу после подключения MCP — отдельный `manage_credentials set clickru` больше не нужен. При `--dry-run` и `--remove` реестр не трогается; токен нигде не печатается целиком (только маска).

Установщик **не запускает никаких процессов** и не требует Bun — он только дописывает `mcpServers` в конфиги (с бэкапом, существующие серверы сохраняются).

## Ручная настройка

### Cursor — глобально `~/.cursor/mcp.json` или проектно `.cursor/mcp.json`

```json
{
  "mcpServers": {
    "yandex-direct": {
      "url": "https://direct-mcp.aihub.click.ru/mcp",
      "headers": {
        "X-Click-Ru-Token": "<CLICK_RU_TOKEN>",
        "X-Client-Login": "<ЛОГИН_ДИРЕКТА>"
      }
    },
    "yandex-wordstat": {
      "url": "https://wordstat-mcp.aihub.click.ru/mcp",
      "headers": {
        "Authorization": "Bearer <CLICK_RU_TOKEN>"
      }
    },
    "vk-ads": {
      "url": "https://vkads-mcp.aihub.click.ru/mcp",
      "headers": {
        "X-Click-Ru-Token": "<CLICK_RU_TOKEN>",
        "X-Click-Ru-Account-Id": "<ID_АККАУНТА_VK>"
      }
    }
  }
}
```

Существующие серверы (например Figma) не затирать — блоки дописываются рядом.

### Claude Code — `.mcp.json` в корне проекта

Тот же блок, но у каждого сервера добавить `"type": "http"`:

```json
{
  "mcpServers": {
    "yandex-direct": {
      "type": "http",
      "url": "https://direct-mcp.aihub.click.ru/mcp",
      "headers": { "X-Click-Ru-Token": "<CLICK_RU_TOKEN>", "X-Client-Login": "<ЛОГИН_ДИРЕКТА>" }
    }
  }
}
```

### Claude Desktop — `claude_desktop_config.json`

Claude Desktop не принимает произвольные HTTP-заголовки в конфиге напрямую, поэтому запись идёт через stdio-мост `mcp-remote` (нужен Node.js):

```json
{
  "mcpServers": {
    "yandex-direct": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote", "https://direct-mcp.aihub.click.ru/mcp",
        "--header", "X-Click-Ru-Token:<CLICK_RU_TOKEN>",
        "--header", "X-Client-Login: <ЛОГИН_ДИРЕКТА>"
      ]
    }
  }
}
```

Путь к конфигу: macOS `~/Library/Application Support/Claude/claude_desktop_config.json`, Windows `%APPDATA%\Claude\claude_desktop_config.json`, Linux `~/.config/Claude/claude_desktop_config.json`.

## Проверка после подключения

После записи конфига **перезапусти клиент** (Cursor: Settings → MCP — серверы должны стать зелёными; Claude Desktop: полный выход и запуск). Затем в сессии агента:

1. **Direct:** вызови `campaigns_get` с `limit: 1` — должен вернуть кампании или пустой список, но не 401.
2. **Wordstat:** спроси «пробей частотность фразы „кофеварка"» — агент должен позвать `wordstat_shows_batch` и вернуть `stat` (показов/мес).
3. **Метрика:** вызови `yandex_metrika_accounts_get` — непустой `accounts`; затем `yandex_metrika_counters_get` с `limit: 1`.
4. **VK Ads:** вызови `vk_ads_auth_check` — должен вернуть данные пользователя VK Ads.

Если сервер не появился: проверь URL (ровно `/mcp` на конце), токен и перезапуск клиента. Ошибка 401 — токен click.ru недействителен или заголовок назван иначе, чем ждёт шлюз (сверься с таблицей выше).

## Фолбек: локальный stdio

Хостовый вариант — дефолт. Локальный запуск (клон `ai-hub-open/yandex-direct-mcp` / `ai-hub-open/vk-ads-mcp`, Bun 1.1+, `bun run src/index.ts`) остаётся для отладки и разработки самих серверов — см. README соответствующего репозитория и references скиллов. Скилы в этом случае работают так же: они ищут сервер по имени (`yandex-direct`, `vk-ads`) и коротким именам инструментов, а не по способу запуска.
