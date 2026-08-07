"""
forecast_cpc.py — оценка CPC по ЖИВОМУ аукциону Яндекс.Директа (Шаг 2 пайплайна).

В v5 прогноза по произвольным фразам нет; режим фраз имеет два бэкенда:
  - Прямой токен Яндекса → v4 CreateNewForecast („Прогноз бюджета", быстрее, без записей в аккаунт)
  - Ключи Click.ru → черновик через v5 (План Б, только для аккаунтов через Click.ru).
Для ключей аккаунта есть РЕАЛЬНЫЕ данные аукциона (сервис KeywordBids.get).
Поле Price в AuctionBids — это списываемая цена клика для нужного объёма трафика.

Три режима:
  1. Живой аукцион по ключам аккаунта (нужен OAuth-токен в YANDEX_DIRECT_TOKEN):
       python -m scripts.forecast_cpc --keyword-ids 57425858469,57425858470 [--sandbox]
     Источник ключей — похожие существующие кампании из аудита (Use case 1),
     либо временная DRAFT-группа с залитыми масками.

  2. Разбор ответа MCP-инструмента keywordbids_get (или сырого API):
       python -m scripts.forecast_cpc --input _keywordbids_raw.json
     Понимает конверт MCP {"success": true, "data": {"KeywordBids": [...]}}
     и сырой ответ API {"result": {"KeywordBids": [...]}}.

  3. Прогноз бюджета по произвольным фразам (нужен прямой OAuth-токен или ключи Click.ru):
       python -m scripts.forecast_cpc --phrases-file masks.txt --region-ids 213 --csv-output cpc.csv
     Бэкенд выбирается автоматически: v4 при прямом токене, черновик v5 при Click.ru.
     Флаги: --via-clickru (форсировать черновик v5), --keep-campaign (не удалять пробный черновик).
     Под Click.ru MCP-инструмент forecast_bids недоступен (Live API v4) — этот режим закрывает дыру.

Вывод — JSON для 02_frequency.json:
  {"base": 28, "optimistic": 27, "pessimistic": 55, "n_keywords": 3,
   "cpc_source": "live-auction", ...}

Цены в ответе API v5 — в МИКРО-валюте (÷1_000_000 = рубли).
TrafficVolume — доля объёма трафика позиции (62-100 = показ в премиум-блоке).
Планируем под TrafficVolume 75 (хорошая видимость без переплаты за топ):
  - base        = Price @ TV ~75
  - pessimistic = Price @ TV ~100 (верх премиум-блока)
  - optimistic  = Price @ TV ~62  (нижняя граница показа)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from datetime import date
from pathlib import Path
from urllib import request as urlreq, error as urlerror
from urllib.parse import quote

try:
    from scripts.credentials import CredentialNotFound, load_api_key
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.credentials import CredentialNotFound, load_api_key

API_PRODUCTION = "https://api.direct.yandex.com/json/v501"
API_SANDBOX = "https://api-sandbox.direct.yandex.com/json/v501"
CLICKRU_PROXY = "https://api.click.ru/V0/api_proxy/yandex_direct"

API_V4_PRODUCTION = "https://api.direct.yandex.ru/live/v4/json/"
API_V4_SANDBOX = "https://api-sandbox.direct.yandex.ru/live/v4/json/"

MICRO = 1_000_000

# Целевые объёмы трафика для трёх сценариев.
TV_PESSIMISTIC = 100
TV_BASE = 75
TV_OPTIMISTIC = 62


def call_keywordbids(token: str, keyword_ids: list[int], sandbox: bool,
                     client_login: str | None = None) -> dict:
    endpoint = API_SANDBOX if sandbox else API_PRODUCTION
    url = f"{endpoint}/keywordbids"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8",
    }
    if client_login:
        headers["Client-Login"] = client_login
    payload = {
        "method": "get",
        "params": {
            "SelectionCriteria": {"KeywordIds": keyword_ids},
            "FieldNames": ["KeywordId", "CampaignId"],
            "SearchFieldNames": ["Bid", "AuctionBids"],
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = urlreq.Request(url, data=data, headers=headers, method="POST")
    try:
        with urlreq.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"error": {"error_code": e.code, "error_string": str(e), "error_detail": body}}


def _extract_bid_list(response: dict) -> list[dict]:
    """Достаёт массив KeywordBids из ответа MCP-обёртки или сырого API v5."""
    # Конверт MCP keywordbids_get: {"success": true, "data": {"KeywordBids": [...]}}
    if isinstance(response.get("data"), dict) and "KeywordBids" in response["data"]:
        return response["data"]["KeywordBids"]
    # Сырой API v5: {"result": {"KeywordBids": [...]}}
    if isinstance(response.get("result"), dict) and "KeywordBids" in response["result"]:
        return response["result"]["KeywordBids"]
    # Уже распакованный массив
    if "KeywordBids" in response:
        return response["KeywordBids"]
    return []


def price_at(items: list[dict], target_tv: int) -> float | None:
    """Списываемая цена (₽) на позиции с объёмом трафика, ближайшим к target_tv."""
    if not items:
        return None
    best = min(items, key=lambda it: abs(it.get("TrafficVolume", 0) - target_tv))
    price_micro = best.get("Price")
    if price_micro is None:
        return None
    return price_micro / MICRO


def parse_bids(response: dict, region_factor: float = 1.0) -> dict:
    bid_list = _extract_bid_list(response)
    per_keyword = []
    for kb in bid_list:
        search = kb.get("Search") or {}
        items = (search.get("AuctionBids") or {}).get("AuctionBidItems") or []
        if not items:
            continue
        per_keyword.append({
            "keyword_id": kb.get("KeywordId"),
            "campaign_id": kb.get("CampaignId"),
            "pessimistic": price_at(items, TV_PESSIMISTIC),
            "base": price_at(items, TV_BASE),
            "optimistic": price_at(items, TV_OPTIMISTIC),
        })

    def median_of(key: str) -> float | None:
        vals = [k[key] for k in per_keyword if k[key] is not None]
        if not vals:
            return None
        return round(statistics.median(vals) * region_factor)

    n = len(per_keyword)
    return {
        "cpc_source": "live-auction",
        "cpc_source_details": (
            f"KeywordBids.get по {n} ключам, медиана Price @ TrafficVolume "
            f"{TV_OPTIMISTIC}/{TV_BASE}/{TV_PESSIMISTIC}, region_factor={region_factor}"
        ),
        "n_keywords": n,
        "optimistic": median_of("optimistic"),
        "base": median_of("base"),
        "pessimistic": median_of("pessimistic"),
        "per_keyword": per_keyword,
    }


MAX_PHRASES_PER_FORECAST = 100  # лимит CreateNewForecast на один отчёт

# Значения первого столбца, означающие CSV-заголовок, а не фразу
_CSV_HEADER_WORDS = {"keyword", "phrase", "ключ"}


def read_phrases(file_path, inline) -> list[str]:
    """Список фраз из файла (txt или csv — первый столбец) и/или строки через запятую.

    Пустые строки и #-комментарии игнорируются, CSV-заголовок отбрасывается,
    дубликаты схлопываются без учёта регистра (остаётся первое написание).
    """
    phrases: list[str] = []
    if file_path:
        for line in Path(file_path).read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            first_col = line.split(",")[0].strip().strip('"').strip()
            if not first_col or first_col.lower() in _CSV_HEADER_WORDS:
                continue
            phrases.append(first_col)
    if inline:
        phrases.extend(p.strip() for p in inline.split(",") if p.strip())

    seen: set[str] = set()
    unique: list[str] = []
    for p in phrases:
        low = p.lower()
        if low not in seen:
            seen.add(low)
            unique.append(p)
    return unique


def chunk_list(items: list, size: int) -> list[list]:
    """Нарезает список чанками по size (последний может быть короче)."""
    return [items[i:i + size] for i in range(0, len(items), size)]


class DirectApiSession:
    """Транспорт API Директа v5/v501: прямой (Bearer) или прокси Click.ru.

    call() возвращает сырой JSON; при сетевой/HTTP-ошибке — {"error": {...}}
    в формате ошибок v5.
    """

    def __init__(self, mode: str, *, token: str | None = None,
                 clickru_token: str | None = None, client_login: str | None = None,
                 clickru_user_id: str | None = None, sandbox: bool = False):
        if mode not in ("direct", "clickru"):
            raise ValueError(f"Неизвестный режим доступа: {mode}")
        if mode == "clickru":
            if not clickru_token:
                raise ValueError("Режим Click.ru: нужен токен (CLICK_RU_TOKEN)")
            if not client_login:
                raise ValueError("Режим Click.ru: нужен логин Директа (CLICK_RU_CLIENT_LOGIN или --client-login)")
            if sandbox:
                raise ValueError("Click.ru прокси не поддерживает песочницу Яндекс.Директа")
        elif not token:
            raise ValueError("Прямой режим: нужен YANDEX_DIRECT_TOKEN")
        self.mode = mode
        self.token = token
        self.clickru_token = clickru_token
        self.client_login = client_login
        self.clickru_user_id = clickru_user_id
        self.sandbox = sandbox
        self.last_units: str | None = None

    def build_request(self, service: str) -> tuple[str, dict]:
        yandex_url = f"{API_SANDBOX if self.sandbox else API_PRODUCTION}/{service}"
        headers = {"Content-Type": "application/json; charset=utf-8", "Accept-Language": "ru"}
        if self.mode == "clickru":
            url = f"{CLICKRU_PROXY}?url={quote(yandex_url, safe='')}"
            headers["X-Auth-Token"] = self.clickru_token
            headers["Client-Login"] = self.client_login
            if self.clickru_user_id:
                headers["X-Auth-UserId"] = self.clickru_user_id
            return url, headers
        headers["Authorization"] = f"Bearer {self.token}"
        if self.client_login:
            headers["Client-Login"] = self.client_login
        return yandex_url, headers

    def call(self, service: str, method: str, params: dict) -> dict:
        url, headers = self.build_request(service)
        data = json.dumps({"method": method, "params": params}, ensure_ascii=False).encode("utf-8")
        req = urlreq.Request(url, data=data, headers=headers, method="POST")
        try:
            with urlreq.urlopen(req, timeout=60) as resp:
                self.last_units = resp.headers.get("Units")
                return json.loads(resp.read().decode("utf-8"))
        except urlerror.HTTPError as e:
            text = e.read().decode("utf-8", errors="replace")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"error": {"error_code": e.code, "error_string": str(e), "error_detail": text}}
        except OSError as e:
            return {"error": {"error_string": f"Сетевая ошибка: {e}"}}


MAX_KEYWORDS_PER_GROUP = 200  # лимит Яндекса на число фраз в группе

# Порядок: сначала ЕПК — техническое объявление (ResponsiveAd) работает только в ЕПК;
# text_highest — последний фолбек (ТГО-объявления заморожены, аукцион может молчать).
PROBE_CAMPAIGN_VARIANTS = ["unified_highest", "unified_wb", "text_highest"]

# WB_MAXIMUM_CLICKS требует недельный бюджет; минимум Директа — 300 ₽/нед.
_PROBE_WEEKLY_BUDGET_RUB = 300


def build_probe_campaign(variant: str, name: str, start_date: str) -> dict:
    """Payload campaigns.add для одного варианта пробной кампании.

    Фолбек: UnifiedCampaign+HIGHEST_POSITION → UnifiedCampaign+WB_MAXIMUM_CLICKS
    с мин. бюджетом → TextCampaign+HIGHEST_POSITION (ЕПК приоритетнее: техническое
    объявление ResponsiveAd работает только в ЕПК-группах; ТГО — последний фолбек;
    черновик в любом варианте не тратит бюджет).
    """
    manual = {
        "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
        "Network": {"BiddingStrategyType": "SERVING_OFF"},
    }
    wb = {
        "Search": {"BiddingStrategyType": "WB_MAXIMUM_CLICKS",
                   "WbMaximumClicks": {"WeeklySpendLimit": _PROBE_WEEKLY_BUDGET_RUB * MICRO}},
        "Network": {"BiddingStrategyType": "SERVING_OFF"},
    }
    base = {"Name": name, "StartDate": start_date}
    if variant == "text_highest":
        return {**base, "TextCampaign": {"BiddingStrategy": manual}}
    if variant == "unified_highest":
        return {**base, "UnifiedCampaign": {"BiddingStrategy": manual}}
    if variant == "unified_wb":
        return {**base, "UnifiedCampaign": {"BiddingStrategy": wb}}
    raise ValueError(f"Неизвестный вариант кампании: {variant}")


def _first_add_id(response: dict) -> int | None:
    """Id первого объекта из AddResults, либо None (ошибка уровня объекта)."""
    results = (response.get("result") or {}).get("AddResults") or []
    if results and "Id" in results[0]:
        return results[0]["Id"]
    return None


def create_probe_campaign(session, name: str, start_date: str) -> tuple[int, str]:
    last_err = None
    for variant in PROBE_CAMPAIGN_VARIANTS:
        resp = session.call("campaigns", "add",
                            {"Campaigns": [build_probe_campaign(variant, name, start_date)]})
        if "error" in resp:
            last_err = resp["error"]
            continue
        cid = _first_add_id(resp)
        if cid:
            print(f"[probe] Создан черновик кампании №{cid} (вариант {variant}). "
                  f"Если скрипт упадёт — удалите её вручную в Директе.", file=sys.stderr)
            return cid, variant
        last_err = (resp.get("result") or {}).get("AddResults")
    sys.exit(f"ERROR: не удалось создать пробную кампанию ни одним вариантом. "
             f"Последняя ошибка: {json.dumps(last_err, ensure_ascii=False)}")


def create_probe_groups(session, campaign_id: int, n_groups: int, region_ids: list[int]) -> list[int]:
    payload = {"AdGroups": [
        {"Name": f"probe_{i + 1}", "CampaignId": campaign_id, "RegionIds": region_ids}
        for i in range(n_groups)
    ]}
    resp = session.call("adgroups", "add", payload)
    if "error" in resp:
        sys.exit(f"ERROR: adgroups.add: {json.dumps(resp['error'], ensure_ascii=False)}")
    ids = []
    for r in (resp.get("result") or {}).get("AddResults") or []:
        if "Id" not in r:
            sys.exit(f"ERROR: группа не создана: {json.dumps(r, ensure_ascii=False)}")
        ids.append(r["Id"])
    return ids


def add_probe_keywords(session, group_ids: list[int], phrase_chunks: list[list[str]]):
    """Заливает фразы; частичные отказы не валят прогон.

    Returns: (keyword_id → фраза, [{"phrase":..., "reason":...}])
    """
    items = []
    for gid, chunk in zip(group_ids, phrase_chunks):
        items.extend({"Keyword": ph, "AdGroupId": gid} for ph in chunk)

    phrase_by_kid: dict[int, str] = {}
    rejected: list[dict] = []
    for batch in chunk_list(items, 1000):  # лимит keywords.add на один вызов
        resp = session.call("keywords", "add", {"Keywords": batch})
        if "error" in resp:
            sys.exit(f"ERROR: keywords.add: {json.dumps(resp['error'], ensure_ascii=False)}")
        results = (resp.get("result") or {}).get("AddResults") or []
        for item, r in zip(batch, results):
            if "Id" in r:
                phrase_by_kid[r["Id"]] = item["Keyword"]
            else:
                reason = "; ".join(e.get("Message", str(e.get("Code"))) for e in r.get("Errors", [])) or "отклонено API"
                rejected.append({"phrase": item["Keyword"], "reason": reason})
    return phrase_by_kid, rejected


def get_keyword_bids(session, keyword_ids: list[int]) -> list[dict]:
    """keywordbids.get чанками ≤10000, 3 повтора на ошибках."""
    bids: list[dict] = []
    for batch in chunk_list(keyword_ids, 10_000):
        params = {
            "SelectionCriteria": {"KeywordIds": batch},
            "FieldNames": ["KeywordId", "CampaignId", "ServingStatus"],
            "SearchFieldNames": ["Bid", "AuctionBids"],
        }
        resp = None
        for attempt in range(3):
            resp = session.call("keywordbids", "get", params)
            if "error" not in resp:
                break
            time.sleep(2)
        if resp is None or "error" in resp:
            sys.exit(f"ERROR: keywordbids.get: {json.dumps(resp.get('error'), ensure_ascii=False)}")
        bids.extend(_extract_bid_list(resp))
    return bids


def delete_campaign(session, campaign_id: int) -> bool:
    resp = session.call("campaigns", "delete", {"SelectionCriteria": {"Ids": [campaign_id]}})
    return "error" not in resp


# Аукцион отдаёт AuctionBids только при наличии объявления в группе (проверено
# e2e 2026-07-28: без объявления — null навсегда). Черновик не активируется,
# объявление не уходит на модерацию и никому не показывается.
_PROBE_AD_TITLES = ["Техническая проверка цен", "Служебное объявление", "Не для показа"]
_PROBE_AD_TEXTS = ["Служебная проверка цен аукциона", "Черновик, не активируется"]
_PROBE_AD_HREF = "https://ya.ru"


def create_probe_ads(session, group_ids: list[int]) -> None:
    """Создаёт по одному техническому ResponsiveAd в каждой группе черновика."""
    ads = [{"AdGroupId": gid,
            "ResponsiveAd": {"Titles": list(_PROBE_AD_TITLES),
                             "Texts": list(_PROBE_AD_TEXTS),
                             "Href": _PROBE_AD_HREF}}
           for gid in group_ids]
    for batch in chunk_list(ads, 1000):
        resp = session.call("ads", "add", {"Ads": batch})
        if "error" in resp:
            sys.exit(f"ERROR: ads.add (техническое объявление): {json.dumps(resp['error'], ensure_ascii=False)}")
        for r in (resp.get("result") or {}).get("AddResults") or []:
            if "Id" not in r:
                sys.exit(f"ERROR: техническое объявление не создано: {json.dumps(r, ensure_ascii=False)}")


def run_phrase_probe(session, phrases: list[str], region_ids: list[int],
                     keep_campaign: bool = False, start_date: str | None = None) -> dict:
    """План Б: черновик → группы → фразы → аукцион → удаление (finally)."""
    if not phrases:
        sys.exit("ERROR: список фраз пуст")
    start_date = start_date or date.today().isoformat()
    stamp = start_date.replace("-", "")
    campaign_id, variant = create_probe_campaign(session, f"_CPC_PROBE_{stamp}", start_date)
    try:
        chunks = chunk_list(phrases, MAX_KEYWORDS_PER_GROUP)
        group_ids = create_probe_groups(session, campaign_id, len(chunks), region_ids)
        create_probe_ads(session, group_ids)
        phrase_by_kid, rejected = add_probe_keywords(session, group_ids, chunks)
        bids = get_keyword_bids(session, list(phrase_by_kid)) if phrase_by_kid else []
        return {"phrase_by_kid": phrase_by_kid, "rejected": rejected, "bids": bids,
                "campaign_id": campaign_id, "campaign_variant": variant}
    finally:
        if keep_campaign:
            print(f"[probe] --keep-campaign: черновик №{campaign_id} оставлен.", file=sys.stderr)
        elif not delete_campaign(session, campaign_id):
            print(f"ВНИМАНИЕ: не удалось удалить черновик №{campaign_id} — "
                  f"удалите его вручную в интерфейсе Директа.", file=sys.stderr)


class ForecastError(Exception):
    """Ошибка «Прогноза бюджета» v4 (создание/ожидание/чтение отчёта)."""


def _v4_error_text(resp: dict) -> str:
    """Человекочитаемый текст ошибки из ответа v4."""
    parts = [str(resp.get(k)) for k in ("error_code", "error_str", "error_detail") if resp.get(k)]
    return "; ".join(parts) if parts else json.dumps(resp, ensure_ascii=False)[:300]


class Live4Session:
    """Транспорт API Директа v4 Live (JSON): токен передаётся в теле запроса."""

    def __init__(self, token: str, sandbox: bool = False):
        self.token = token
        self.sandbox = sandbox
        self.endpoint = API_V4_SANDBOX if sandbox else API_V4_PRODUCTION

    def call(self, method: str, param=None) -> dict:
        body: dict = {"method": method, "token": self.token, "locale": "ru"}
        if param is not None:
            body["param"] = param
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urlreq.Request(
            self.endpoint, data=data,
            headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
        try:
            with urlreq.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urlerror.HTTPError as e:
            text = e.read().decode("utf-8", errors="replace")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"error_code": e.code, "error_str": str(e), "error_detail": text}
        except OSError as e:
            return {"error_str": f"Сетевая ошибка: {e}"}


FORECAST_POLL_INTERVAL = 15  # GetForecastList — не чаще раза в 10-20 секунд
FORECAST_TIMEOUT = 300       # секунд на готовность одного отчёта


def create_forecast(session, phrases: list[str], region_ids: list[int]) -> int:
    """Создаёт отчёт прогноза по фразам и регионам. Возвращает ID отчёта."""
    resp = session.call("CreateNewForecast", {
        "Phrases": phrases, "GeoID": region_ids,
        "Currency": "RUB", "AuctionBids": "Yes",
    })
    if "data" not in resp:
        raise ForecastError(f"CreateNewForecast: {_v4_error_text(resp)}")
    return resp["data"]


def wait_forecast(session, report_id: int) -> None:
    """Ждёт готовности отчёта. Имена полей списка (ForecastID/StatusForecast)
    зафиксированы по документации; при расхождении правятся по факту e2e."""
    waited = 0
    while True:
        resp = session.call("GetForecastList")
        for item in resp.get("data") or []:
            if item.get("ForecastID") == report_id and item.get("StatusForecast") == "Done":
                return
        if waited >= FORECAST_TIMEOUT:
            raise ForecastError(f"Отчёт {report_id} не готов за {FORECAST_TIMEOUT} с")
        time.sleep(FORECAST_POLL_INTERVAL)
        waited += FORECAST_POLL_INTERVAL


def fetch_forecast(session, report_id: int) -> list[dict]:
    """Получает массив фраз из готового отчёта."""
    resp = session.call("GetForecast", report_id)
    if "data" not in resp:
        raise ForecastError(f"GetForecast: {_v4_error_text(resp)}")
    return (resp["data"] or {}).get("Phrases") or []


def delete_forecast(session, report_id: int) -> bool:
    """Удаляет отчёт. Возвращает True если успешно."""
    return "data" in session.call("DeleteForecastReport", report_id)


def run_budget_forecast(session, phrases: list[str], region_ids: list[int]) -> dict:
    """Прогноз бюджета по чанкам ≤100 фраз, строго последовательно (лимит 5 отчётов).

    Returns: {"phrase_rows": [...сырые элементы Phrases...],
              "chunk_errors": [{"phrases": [...], "reason": str}]}
    """
    if not phrases:
        sys.exit("ERROR: список фраз пуст")
    chunks = chunk_list(phrases, MAX_PHRASES_PER_FORECAST)
    if len(chunks) > 2:
        print(f"[forecast] Чанков: {len(chunks)}, ~1 минута на каждый — "
              f"итого примерно {len(chunks)} мин.", file=sys.stderr)

    phrase_rows: list[dict] = []
    chunk_errors: list[dict] = []
    for i, chunk in enumerate(chunks, 1):
        try:
            report_id = create_forecast(session, chunk, region_ids)
        except ForecastError as e:
            chunk_errors.append({"phrases": chunk, "reason": str(e)})
            continue
        print(f"[forecast] Чанк {i}/{len(chunks)}: отчёт №{report_id}, жду готовности…",
              file=sys.stderr)
        try:
            wait_forecast(session, report_id)
            phrase_rows.extend(fetch_forecast(session, report_id))
        except ForecastError as e:
            chunk_errors.append({"phrases": chunk, "reason": str(e)})
        finally:
            if not delete_forecast(session, report_id):
                print(f"ВНИМАНИЕ: отчёт №{report_id} не удалился "
                      f"(сам исчезнет через 5 часов).", file=sys.stderr)

    if not phrase_rows and chunk_errors:
        sys.exit(f"ERROR: все чанки прогноза упали. Первая ошибка: {chunk_errors[0]['reason']}")
    return {"phrase_rows": phrase_rows, "chunk_errors": chunk_errors}


def _price_or_none(value):
    """Цена v4 уже в рублях; 0/None/отрицательное → None (нет данных)."""
    return value if isinstance(value, (int, float)) and value > 0 else None


def build_phrase_report(forecast: dict, requested_phrases: list[str],
                        region_ids: list[int]) -> dict:
    """Отчёт по фразам из результата run_budget_forecast (схема — в спеке).

    Маппинг сценариев: pessimistic=PremiumMax (1-е место спецразмещения),
    base=PremiumMin (вход в спецразмещение), optimistic=Min (вход в нижний блок).
    """
    rows_by_phrase = {(r.get("Phrase") or "").lower(): r for r in forecast["phrase_rows"]}
    error_reason_by_phrase = {p.lower(): ce["reason"]
                              for ce in forecast["chunk_errors"] for p in ce["phrases"]}

    per_keyword: list[dict] = []
    for phrase in requested_phrases:
        low = phrase.lower()
        if low in error_reason_by_phrase:
            per_keyword.append({
                "phrase": phrase, "status": "chunk_error",
                "reason": error_reason_by_phrase[low],
                "cpc_optimistic": None, "cpc_base": None, "cpc_pessimistic": None,
                "forecast_shows": None, "forecast_clicks": None, "forecast_ctr": None,
                "auction_bids": [],
            })
            continue
        row = rows_by_phrase.get(low) or {}
        opt = _price_or_none(row.get("Min"))
        base = _price_or_none(row.get("PremiumMin"))
        pess = _price_or_none(row.get("PremiumMax"))
        has_price = any(v is not None for v in (opt, base, pess))
        per_keyword.append({
            "phrase": phrase,
            "status": "ok" if has_price else "no_forecast_data",
            "cpc_optimistic": opt, "cpc_base": base, "cpc_pessimistic": pess,
            "forecast_shows": row.get("Shows"), "forecast_clicks": row.get("Clicks"),
            "forecast_ctr": row.get("CTR"),
            "auction_bids": row.get("AuctionBids") or [],
        })

    ok = [k for k in per_keyword if k["status"] == "ok"]
    n_no_data = sum(1 for k in per_keyword if k["status"] == "no_forecast_data")

    def median_of(key: str):
        vals = [k[key] for k in ok if k[key] is not None]
        return round(statistics.median(vals)) if vals else None

    n_total = len(per_keyword)
    return {
        "cpc_source": "budget-forecast-v4",
        "cpc_source_details": (
            f"CreateNewForecast/GetForecast по {n_total} фразам, GeoID {region_ids}, "
            f"цены PremiumMin/PremiumMax/Min (руб.)"
        ),
        "region_ids": region_ids,
        "n_keywords": n_total,
        "n_ok": len(ok),
        "n_no_data": n_no_data,
        "thin_data": n_total > 0 and len(ok) * 2 < n_total,
        "optimistic": median_of("cpc_optimistic"),
        "base": median_of("cpc_base"),
        "pessimistic": median_of("cpc_pessimistic"),
        "per_keyword": per_keyword,
    }


def _fmt_num(value) -> str:
    """Число для CSV: None → пусто, 52.0 → '52', 52.5 → '52.5', 1234567 → '1234567'."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        return str(value)
    return f"{value:g}"


def build_probe_report(probe: dict, region_ids: list[int]) -> dict:
    """Отчёт по фразам из результата run_phrase_probe (План Б; схема как у v4-пути).

    Черновик не даёт прогноза трафика — forecast_* всегда None. Цены аукциона
    в микроединицах, price_at переводит в рубли.
    """
    bids_by_kid = {b.get("KeywordId"): b for b in probe["bids"]}
    per_keyword: list[dict] = []
    for kid, phrase in probe["phrase_by_kid"].items():
        search = (bids_by_kid.get(kid) or {}).get("Search") or {}
        items = (search.get("AuctionBids") or {}).get("AuctionBidItems") or []
        entry = {"phrase": phrase, "keyword_id": kid,
                 "forecast_shows": None, "forecast_clicks": None, "forecast_ctr": None,
                 "auction_bids": items}
        if items:
            entry.update(status="ok",
                         cpc_optimistic=price_at(items, TV_OPTIMISTIC),
                         cpc_base=price_at(items, TV_BASE),
                         cpc_pessimistic=price_at(items, TV_PESSIMISTIC))
        else:
            entry.update(status="no_auction_data", cpc_optimistic=None,
                         cpc_base=None, cpc_pessimistic=None)
        per_keyword.append(entry)

    for rej in probe["rejected"]:
        per_keyword.append({"phrase": rej["phrase"], "keyword_id": None,
                            "status": "rejected", "reason": rej["reason"],
                            "cpc_optimistic": None, "cpc_base": None, "cpc_pessimistic": None,
                            "forecast_shows": None, "forecast_clicks": None,
                            "forecast_ctr": None, "auction_bids": []})

    ok = [k for k in per_keyword if k["status"] == "ok"]

    def median_of(key: str):
        vals = [k[key] for k in ok if k[key] is not None]
        return round(statistics.median(vals)) if vals else None

    n_total = len(per_keyword)
    return {
        "cpc_source": "live-auction-draft-probe",
        "cpc_source_details": (
            f"Черновик №{probe['campaign_id']} (вариант {probe['campaign_variant']}), "
            f"keywordbids.get по {len(probe['phrase_by_kid'])} фразам, "
            f"Price @ TrafficVolume {TV_OPTIMISTIC}/{TV_BASE}/{TV_PESSIMISTIC}"
        ),
        "region_ids": region_ids,
        "n_keywords": n_total,
        "n_ok": len(ok),
        "n_no_data": sum(1 for k in per_keyword if k["status"] == "no_auction_data"),
        "thin_data": n_total > 0 and len(ok) * 2 < n_total,
        "optimistic": median_of("cpc_optimistic"),
        "base": median_of("cpc_base"),
        "pessimistic": median_of("cpc_pessimistic"),
        "per_keyword": per_keyword,
    }


def write_phrase_csv(report: dict, path) -> None:
    """CSV по фразам (utf-8-sig, чтобы открывался в Excel без кракозябр)."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["phrase", "cpc_optimistic", "cpc_base", "cpc_pessimistic",
                         "forecast_shows", "forecast_clicks", "status"])
        for k in report["per_keyword"]:
            writer.writerow([
                k["phrase"],
                _fmt_num(k["cpc_optimistic"]), _fmt_num(k["cpc_base"]),
                _fmt_num(k["cpc_pessimistic"]),
                _fmt_num(k["forecast_shows"]), _fmt_num(k["forecast_clicks"]),
                k["status"],
            ])


def _load_credential(service: str) -> str | None:
    """Ключ из env/credentials.json, None если не сохранён."""
    try:
        return load_api_key(service)
    except (CredentialNotFound, ValueError):
        return None


def resolve_phrases_backend(args) -> tuple[str, object]:
    """Выбор бэкенда режима фраз: прямой токен → v4 «Прогноз бюджета» (быстрее,
    без записей в аккаунт); только ключи Click.ru → черновик через v5.
    --via-clickru форсирует путь черновика."""
    direct_token = _load_credential("yandex_direct")
    if direct_token and not args.via_clickru:
        return "v4", Live4Session(direct_token, sandbox=args.sandbox)
    clickru_token = _load_credential("clickru")
    if clickru_token:
        clickru_login = args.client_login or _load_credential("clickru_login")
        if not clickru_login:
            sys.exit("ERROR: для Click.ru нужен логин Директа.\n"
                     "Сохраните: python -m scripts.manage_credentials set clickru_login "
                     "(или передайте --client-login)")
        try:
            return "probe", DirectApiSession(
                "clickru", clickru_token=clickru_token, client_login=clickru_login,
                clickru_user_id=_load_credential("clickru_user_id"), sandbox=args.sandbox)
        except ValueError as e:
            sys.exit(f"ERROR: {e}")
    if args.via_clickru:
        sys.exit("ERROR: --via-clickru, но токен Click.ru не найден.\n"
                 "Сохраните: python -m scripts.manage_credentials set clickru")
    sys.exit("ERROR: не найден ни прямой токен Яндекса, ни токен Click.ru.\n"
             "Сохраните один: python -m scripts.manage_credentials set yandex_direct\n"
             "           или: python -m scripts.manage_credentials set clickru")


def main() -> None:
    # Кириллица в stdout на Windows-консолях (cp1251) иначе ломается.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(
        description="Оценка CPC: по ключам аккаунта (--keyword-ids/--input, живой аукцион v5) "
                    "или по произвольным фразам (--phrases-file/--phrases + --region-ids): "
                    "бэкенд подбирается автоматически — прямой токен Яндекса даёт Прогноз "
                    "бюджета v4 (в аккаунте ничего не создаётся), только Click.ru — временный "
                    "DRAFT-черновик через v5 (создаётся и автоматически удаляется)")
    parser.add_argument("--keyword-ids", help="ID ключей через запятую (аукцион по ключам аккаунта)")
    parser.add_argument("--input", help="Путь к JSON с готовым ответом KeywordBids")
    parser.add_argument("--phrases-file", help="Файл с фразами (по строке; csv — первый столбец)")
    parser.add_argument("--phrases", help="Фразы через запятую (можно вместе с --phrases-file)")
    parser.add_argument("--region-ids", help="ID регионов через запятую (обязателен в режиме фраз), напр. 213")
    parser.add_argument("--sandbox", action="store_true", help="Песочница (механика без реальных цен)")
    parser.add_argument("--via-clickru", action="store_true",
                        help="Форсировать путь Click.ru (черновик v5) даже при наличии прямого токена")
    parser.add_argument("--keep-campaign", action="store_true",
                        help="Не удалять пробный черновик (только путь Click.ru; отладка)")
    parser.add_argument("--client-login", default=None, help="Client-Login: агентские аккаунты в режиме --keyword-ids, либо логин Директа для Click.ru в режиме фраз (переопределяет сохранённый clickru_login)")
    parser.add_argument("--region-factor", type=float, default=1.0,
                        help="Множитель региона для режимов --keyword-ids/--input")
    parser.add_argument("--output", default=None, help="Куда записать JSON (по умолчанию stdout)")
    parser.add_argument("--csv-output", default=None, help="Куда записать CSV по фразам (режим фраз)")
    args = parser.parse_args()

    phrases_mode = bool(args.phrases_file or args.phrases)
    sources = sum([bool(args.keyword_ids), bool(args.input), phrases_mode])
    if sources != 1:
        parser.error("укажите ровно один источник: --keyword-ids, --input либо --phrases-file/--phrases")

    if phrases_mode:
        if not args.region_ids:
            parser.error("режим фраз требует --region-ids (регион напрямую влияет на цены)")
        if args.sandbox:
            print("ВНИМАНИЕ: песочница не знает реальных цен — это проверка механики, "
                  "не прогноз.", file=sys.stderr)
        region_ids = [int(x) for x in args.region_ids.split(",") if x.strip()]
        phrases = read_phrases(args.phrases_file, args.phrases)
        backend, session = resolve_phrases_backend(args)
        if backend == "v4":
            forecast = run_budget_forecast(session, phrases, region_ids)
            result = build_phrase_report(forecast, phrases, region_ids)
            if forecast["chunk_errors"]:
                print(f"ВНИМАНИЕ: {len(forecast['chunk_errors'])} чанк(ов) упали — "
                      f"их фразы получили статус chunk_error.", file=sys.stderr)
        else:
            probe = run_phrase_probe(session, phrases, region_ids,
                                     keep_campaign=args.keep_campaign)
            result = build_probe_report(probe, region_ids)
            if session.last_units:
                print(f"[units] Остаток баллов API: {session.last_units}", file=sys.stderr)
        if result["thin_data"]:
            print(f"ВНИМАНИЕ: данных нет по {result['n_keywords'] - result['n_ok']} из "
                  f"{result['n_keywords']} фраз — прогноз опирается на малую выборку.",
                  file=sys.stderr)
        if args.csv_output:
            write_phrase_csv(result, args.csv_output)
            print(f"CSV записан: {args.csv_output}", file=sys.stderr)
    elif args.keyword_ids:
        token = os.environ.get("YANDEX_DIRECT_TOKEN")
        if not token:
            sys.exit("ERROR: нет YANDEX_DIRECT_TOKEN в окружении (нужен для прямого вызова API)")
        ids = [int(x) for x in args.keyword_ids.split(",") if x.strip()]
        response = call_keywordbids(token, ids, args.sandbox, args.client_login)
        if "error" in response:
            sys.exit(f"API error: {json.dumps(response['error'], ensure_ascii=False)}")
        result = parse_bids(response, args.region_factor)
    else:
        response = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = parse_bids(response, args.region_factor)

    out = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"Записано: {args.output}")
    else:
        print(out)


if __name__ == "__main__":
    main()
