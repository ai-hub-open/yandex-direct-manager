# Yandex Direct MCP — запуск кампании через MCP-сервер

**Это предпочтительный путь запуска РК через API.** У пользователя должна быть локальная копия MCP-сервера `yandex-direct-mcp` (Bun/TypeScript, ~30 инструментов).

## Что внутри MCP

Сервер регистрирует ~30 инструментов в namespace `yandex_direct_*`. После подключения в Claude Desktop они появляются в сессии как `mcp__yandex-direct__<name>`:

| Группа | Инструменты |
|---|---|
| Campaigns | `yandex_direct_campaigns_get` / `_add` / `_update` / `_delete` / `_suspend` / `_resume` |
| AdGroups | `yandex_direct_adgroups_get` / `_add` / `_update` / `_delete` |
| Ads | `yandex_direct_ads_get` / `_add` / `_update` / `_delete` / `_suspend` / `_resume` / `_moderate` |
| AdImages | `yandex_direct_adimages_add` (с кропом) / `_get` |
| BidModifiers | `yandex_direct_bidmodifiers_demographics` / `_get` |
| Keywords | `yandex_direct_keywords_get` / `_add` / `_update` / `_delete` / `_suspend` / `_resume` |
| Reports | `yandex_direct_reports_campaign` / `_ad` / `_search_queries` |
| Dictionaries | `yandex_direct_dictionaries_regions` / `_currencies` / `_interests` / `_all` |

## Алгоритм действий на финале воронки

1. **Проверь, доступен ли MCP в текущей сессии.** Попробуй вызвать любой read-only инструмент, например `mcp__yandex-direct__yandex_direct_campaigns_get` с `limit: 1`.

2. **Если MCP не подключён** — запусти инсталлятор:

   ```bash
   python -m scripts.setup_yandex_direct_mcp \
     --mcp-path "D:\yandex-direct-mcp" \
     --mode sandbox \
     --token <SANDBOX_TOKEN>
   ```

   Скрипт сам найдёт `claude_desktop_config.json`, сделает бэкап и допишет блок `mcpServers.yandex-direct`. Скажи пользователю «закрой Claude Desktop полностью и открой заново — потом вернись и скажи "продолжаем"». **Не пытайся запускать MCP сам.**

3. **Когда MCP доступен** — действуй так:

   - **Создай кампанию:**
     ```
     mcp__yandex-direct__yandex_direct_campaigns_add({
       name: creatives.campaign_name,
       start_date: "<YYYY-MM-DD>",
       daily_budget: <рубли>,
       negative_keywords: creatives.negative_keywords
     })
     ```
     Запомни `Id` из ответа.

   - **Для каждой группы** из `creatives.groups`:
     - `yandex_direct_adgroups_add({ name, campaign_id, region_ids })`
     - Для каждого ad — `yandex_direct_ads_add({ adgroup_id, title, title2, text, href, display_url_path })`
     - `yandex_direct_keywords_add({ adgroup_id, keywords: [...], bid })`

   - **Не активируй сразу.** Не дёргай `campaigns_resume`.

## Режимы запуска MCP

### A. Sandbox (рекомендуется на тесте)

- `YANDEX_DIRECT_TOKEN=<sandbox_oauth>`
- `YANDEX_DIRECT_SANDBOX=true`
- Никаких реальных списаний.
- Где взять токен: https://oauth.yandex.ru → создать приложение → разрешение `direct:api`.

### B. Direct production

- `YANDEX_DIRECT_TOKEN=<production_oauth>`
- `YANDEX_DIRECT_SANDBOX=false`
- Требует одобренной заявки на API-доступ (1-3 рабочих дня для новых OAuth-приложений).

### C. Click.ru proxy (без OAuth Яндекса)

- `CLICK_RU_PROXY=true`
- `CLICK_RU_TOKEN=<X-Auth-Token>`
- `CLICK_RU_CLIENT_LOGIN=<логин Яндекс.Директа>`
- Опционально `CLICK_RU_USER_ID=<userId>` для мастер-аккаунтов.
- Работает только в production.
- Не нужна одобренная заявка на API в Яндексе.

## Требования к окружению

- **Bun 1.1+** в PATH. На Windows: `irm bun.sh/install.ps1 | iex` в PowerShell.
- Папка MCP скачана (например `D:\yandex-direct-mcp`).
- Зависимости установлены: `cd D:\yandex-direct-mcp && bun install`.
- Claude Desktop 0.7+.

Setup-скрипт проверит это всё перед тем как трогать конфиг.

## Особенности работы через MCP

- **Имена параметров — snake_case** (`start_date`, `daily_budget`).
- **Бюджеты в валюте аккаунта** (рубли, не микро).
- **Регионы — int.** Частые: `225` (РФ), `213` (Москва), `2` (СПб), `50` (Пермь), `54` (Екатеринбург), `66` (Новосибирск). Полный справочник — `yandex_direct_dictionaries_regions`.
- **Отчёты идут асинхронно** — повтори через N секунд.

## Безопасность

- **Никогда не сохраняй OAuth-токен в артефакты скилла.**
- **Дефолт — sandbox + DRAFT.** Production только с явным «да».
- **Активация — только руками юзера.**

## Полезные ссылки

- Bun: https://bun.sh
- Yandex Direct API v5: https://yandex.com/dev/direct/doc/en/concepts/overview
- OAuth: https://yandex.ru/dev/direct/doc/dg/concepts/auth-token-docpage/
- Click.ru API: https://api.click.ru/V0/docs/
