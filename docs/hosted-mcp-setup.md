# Хостовые MCP aihub.click.ru — подключение скиллов

Единая инструкция, как подключить скилы `yandex-direct-manager` и `vk-ads-manager` к хостовым MCP-серверам. Локальный запуск (Bun, клон репозитория) больше не нужен — серверы уже подняты на стороне aihub.

## Серверы

| Сервер в конфиге | URL | Что даёт |
|---|---|---|
| `yandex-direct` | `https://direct-mcp.aihub.click.ru/mcp` | 50 инструментов Direct API v501 (кампании, ЕПК, группы, объявления, ключи, ставки, отчёты, справочники) |
| `yandex-wordstat` | `https://wordstat-mcp.aihub.click.ru/mcp` | Статистика поискового спроса (частотность, похожие запросы, регионы, динамика) |
| `vk-ads` | `https://vkads-mcp.aihub.click.ru/mcp` | 48 инструментов VK Ads API (`vk_ads_*`: кампании, группы, объявления, аудитории, статистика) |

Корневой путь `/` отдаёт 404 — рабочий JSON-RPC endpoint именно `/mcp`. Health-check: `GET /healthz` → `OK`.

## Авторизация (проверено прогоном 19.08.2026)

Всё сводится к **одному API-токену click.ru**: профиль https://click.ru/userinfo.html → поле «API Token» → «Создать». Аккаунты Директа и VK Рекламы должны быть подключены в click.ru.

| Сервер | Заголовки на каждый запрос |
|---|---|
| `yandex-direct` | `Authorization: Bearer <CLICK_RU_TOKEN>`, `X-Client-Login: <логин Директа>`; для мастер-аккаунта click.ru добавить `X-Click-Ru-User-Id` |
| `yandex-wordstat` | `Authorization: Bearer <CLICK_RU_TOKEN>` (токен проверяется шлюзом через click.ru; ключ Yandex Cloud не нужен — он на стороне сервера) |
| `vk-ads` | `X-Click-Ru-Token: <CLICK_RU_TOKEN>`, `X-Click-Ru-Account-Id: <ID аккаунта VK Рекламы в click.ru>` |

Примечания:

- Список инструментов VK Ads открыт без кредов (`GET /mcp/tools`), но вызовы без заголовков возвращают ошибку «Не заданы креды VK Ads…» с перечнем нужных заголовков.
- Direct и Wordstat без токена отвечают `401 {"error":"Unauthorized"}`; с недействительным токеном — `401 click.ru: токен недействителен`.
- ID аккаунта VK Рекламы в click.ru: `GET /accounts` в https://api.click.ru/V0/docs/.
- Альтернативы click.ru для VK (готовый `X-VK-Ads-Token`, OAuth `X-VK-Ads-Client-Id` + `X-VK-Ads-Client-Secret`) сервер тоже принимает — см. его сообщение об ошибке.
- Токен click.ru — секрет. В git не коммитим: в репозитории только плейсхолдеры, реальные значения пишутся в конфиги клиентов установщиком.

## Автоматическая запись конфигов (рекомендуется)

Установщики лежат в скиллах и умеют цели `cursor` (глобально, `~/.cursor/mcp.json`), `cursor-project` (`.cursor/mcp.json` в текущей папке), `claude-code` (`.mcp.json` в текущей папке), `claude-desktop`, `all`:

```bash
# Директ + Wordstat (одна команда, оба сервера)
python -m scripts.setup_yandex_direct_mcp \
  --token <CLICK_RU_TOKEN> --client-login <ЛОГИН_ДИРЕКТА> \
  --target all

# VK Ads
python -m scripts.setup_vk_ads_mcp \
  --token <CLICK_RU_TOKEN> --vk-account-id <ID_АККАУНТА> \
  --target all
```

Полезные флаги: `--dry-run` (показать, что будет записано), `--remove` (удалить записи), `--click-ru-user-id` (мастер-аккаунт click.ru). Токен можно не передавать аргументом, если он уже сохранён через `manage_credentials set clickru`.

Установщик **не запускает никаких процессов** и не требует Bun — он только дописывает `mcpServers` в конфиги (с бэкапом, существующие серверы сохраняются).

## Ручная настройка

### Cursor — глобально `~/.cursor/mcp.json` или проектно `.cursor/mcp.json`

```json
{
  "mcpServers": {
    "yandex-direct": {
      "url": "https://direct-mcp.aihub.click.ru/mcp",
      "headers": {
        "Authorization": "Bearer <CLICK_RU_TOKEN>",
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
      "headers": { "Authorization": "Bearer <CLICK_RU_TOKEN>", "X-Client-Login": "<ЛОГИН_ДИРЕКТА>" }
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
        "--header", "Authorization: Bearer <CLICK_RU_TOKEN>",
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
2. **Wordstat:** спроси «пробей частотность фразы „кофеварка"» — агент должен позвать инструмент wordstat и вернуть `totalCount`.
3. **VK Ads:** вызови `vk_ads_auth_check` — должен вернуть данные пользователя VK Ads.

Если сервер не появился: проверь URL (ровно `/mcp` на конце), токен и перезапуск клиента. Ошибка 401 — токен click.ru недействителен или заголовок назван иначе, чем ждёт шлюз (сверься с таблицей выше).

## Фолбек: локальный stdio

Хостовый вариант — дефолт. Локальный запуск (клон `ai-hub-open/yandex-direct-mcp` / `ai-hub-open/vk-ads-mcp`, Bun 1.1+, `bun run src/index.ts`) остаётся для отладки и разработки самих серверов — см. README соответствующего репозитория и references скиллов. Скилы в этом случае работают так же: они ищут сервер по имени (`yandex-direct`, `vk-ads`) и коротким именам инструментов, а не по способу запуска.
