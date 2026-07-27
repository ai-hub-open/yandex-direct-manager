"""
forecast_cpc.py — оценка CPC по ЖИВОМУ аукциону Яндекс.Директа (Шаг 2 пайплайна).

Заменяет несуществующий метод Forecast.GetForecast (закрыт вместе с API v4).
В API v5 нет прогноза ставок по произвольным фразам, но есть РЕАЛЬНЫЕ данные
аукциона по ключам, которые уже заведены в аккаунт — сервис KeywordBids.get.
Поле Price в AuctionBids — это списываемая цена клика для нужного объёма трафика.

Два режима:
  1. Прямой вызов API (нужен OAuth-токен в YANDEX_DIRECT_TOKEN):
       python -m scripts.forecast_cpc --keyword-ids 57425858469,57425858470 [--sandbox]
     Источник ключей — похожие существующие кампании из аудита (Use case 1),
     либо временная DRAFT-группа с залитыми масками.

  2. Разбор уже полученного ответа (например из MCP yandex_direct_api_call):
       python -m scripts.forecast_cpc --input _keywordbids_raw.json

Вывод — JSON для 02_frequency.json:
  {"base": 28, "optimistic": 27, "pessimistic": 55, "n_keywords": 3,
   "cpc_source": "live-auction", ...}

Цены в ответе API — в МИКРО-валюте (÷1_000_000 = рубли).
TrafficVolume — доля объёма трафика позиции (62-100 = показ в премиум-блоке).
Планируем под TrafficVolume 75 (хорошая видимость без переплаты за топ):
  - base        = Price @ TV ~75
  - pessimistic = Price @ TV ~100 (верх премиум-блока)
  - optimistic  = Price @ TV ~62  (нижняя граница показа)
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path
from urllib import request as urlreq, error as urlerror

API_PRODUCTION = "https://api.direct.yandex.com/json/v5"
API_SANDBOX = "https://api-sandbox.direct.yandex.com/json/v5"

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
    # MCP yandex_direct_api_call: {"success": true, "data": {"KeywordBids": [...]}}
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


def main() -> None:
    # Кириллица в stdout на Windows-консолях (cp1251) иначе ломается.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Оценка CPC по живому аукциону Директа (KeywordBids.get)")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--keyword-ids", help="ID ключей через запятую (вызовет API, нужен YANDEX_DIRECT_TOKEN)")
    src.add_argument("--input", help="Путь к JSON с ответом KeywordBids (из MCP api_call или сырого API)")
    parser.add_argument("--sandbox", action="store_true", help="Песочница вместо production")
    parser.add_argument("--client-login", default=None, help="Client-Login для агентских аккаунтов")
    parser.add_argument("--region-factor", type=float, default=1.0,
                        help="Множитель региона (Мск=1.0, СПб=0.85, миллионники=0.6 и т.д.)")
    parser.add_argument("--output", default=None, help="Куда записать результат (по умолчанию stdout)")
    args = parser.parse_args()

    if args.keyword_ids:
        token = os.environ.get("YANDEX_DIRECT_TOKEN")
        if not token:
            sys.exit("ERROR: нет YANDEX_DIRECT_TOKEN в окружении (нужен для прямого вызова API)")
        ids = [int(x) for x in args.keyword_ids.split(",") if x.strip()]
        response = call_keywordbids(token, ids, args.sandbox, args.client_login)
        if "error" in response:
            sys.exit(f"API error: {json.dumps(response['error'], ensure_ascii=False)}")
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
