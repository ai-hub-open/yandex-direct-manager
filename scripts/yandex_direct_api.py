"""
yandex_direct_api.py — Прямой HTTP fallback на случай, если MCP yandex-direct
не доступен или не настроен.

ПРЕДПОЧТИТЕЛЬНЫЙ путь — использовать локальный MCP yandex-direct (см.
references/yandex-direct-mcp.md и scripts/setup_yandex_direct_mcp.py).

Этот скрипт — только аварийный обходной канал. Делает прямые HTTP-запросы
к api.direct.yandex.com (или api-sandbox.direct.yandex.com), читает creatives.json
из workspace и создаёт кампанию в DRAFT.

Использование:
    export YANDEX_DIRECT_TOKEN="<OAUTH_TOKEN>"
    python -m scripts.yandex_direct_api --workspace <path> [--production] [--region-ids 225]

По умолчанию: sandbox + DRAFT. Никаких реальных списаний.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from urllib import request as urlreq, error as urlerror


API_PRODUCTION = "https://api.direct.yandex.com/json/v5"
API_SANDBOX = "https://api-sandbox.direct.yandex.com/json/v5"


def call(endpoint: str, service: str, payload: dict, token: str, client_login: str | None = None) -> dict:
    url = f"{endpoint}/{service}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8",
    }
    if client_login:
        headers["Client-Login"] = client_login

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


def rubles_to_micros(rub: float) -> int:
    return int(round(rub * 1_000_000))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--token", default=os.environ.get("YANDEX_DIRECT_TOKEN"))
    parser.add_argument("--client-login", default=None)
    parser.add_argument("--production", action="store_true", help="По умолчанию — sandbox")
    parser.add_argument("--start-date", default=time.strftime("%Y-%m-%d"))
    parser.add_argument("--daily-budget", type=float, default=1000)
    parser.add_argument("--default-bid", type=float, default=15)
    parser.add_argument("--region-ids", default="225", help="225=РФ, 213=Москва, 2=СПб, 50=Пермь")
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("Нужен --token или env YANDEX_DIRECT_TOKEN.")

    endpoint = API_PRODUCTION if args.production else API_SANDBOX
    workspace = Path(args.workspace).resolve()
    creatives_path = workspace / "creatives.json"
    if not creatives_path.exists():
        raise SystemExit(f"Нет {creatives_path}. Пройди шаг 10 и сформируй creatives.json.")

    creatives = json.loads(creatives_path.read_text(encoding="utf-8"))
    region_ids = [int(r) for r in args.region_ids.split(",")]
    log: list[str] = []

    def L(msg: str):
        print(msg)
        log.append(msg)

    L(f"=== Direct API ({'PROD' if args.production else 'SANDBOX'}) ===")

    res = call(endpoint, "campaigns", {
        "method": "add",
        "params": {"Campaigns": [{
            "Name": creatives.get("campaign_name", f"Direct {args.start_date}")[:255],
            "StartDate": args.start_date,
            "TextCampaign": {
                "BiddingStrategy": {
                    "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
                    "Network": {"BiddingStrategyType": "SERVING_OFF"},
                },
                "Settings": [],
            },
            "DailyBudget": {"Amount": rubles_to_micros(args.daily_budget), "Mode": "STANDARD"},
        }]},
    }, args.token, args.client_login)
    if "error" in res:
        raise SystemExit(f"Ошибка создания кампании: {res['error']}")
    campaign_id = res["result"]["AddResults"][0]["Id"]
    L(f"Кампания: id={campaign_id}")

    for group in creatives.get("groups", []):
        res = call(endpoint, "adgroups", {
            "method": "add",
            "params": {"AdGroups": [{
                "Name": group["name"][:255],
                "CampaignId": campaign_id,
                "RegionIds": region_ids,
                "TextAdGroup": {},
            }]},
        }, args.token, args.client_login)
        if "error" in res:
            L(f"  Ошибка группы '{group['name']}': {res['error']}"); continue
        adgroup_id = res["result"]["AddResults"][0]["Id"]
        L(f"  Группа '{group['name']}': id={adgroup_id}")

        for ad in group.get("ads", []):
            text_ad = {
                "Title": ad.get("title", ""),
                "Title2": ad.get("title2", ""),
                "Text": ad.get("text", ""),
                "Href": ad.get("href") or group.get("url") or creatives.get("default_url", ""),
                "Mobile": "NO",
            }
            if ad.get("display_url_path"):
                text_ad["DisplayUrlPath"] = ad["display_url_path"]
            res = call(endpoint, "ads", {
                "method": "add",
                "params": {"Ads": [{"AdGroupId": adgroup_id, "TextAd": text_ad}]},
            }, args.token, args.client_login)
            if "error" in res:
                L(f"    Ошибка ad: {res['error']}"); continue
            L(f"    Ad id={res['result']['AddResults'][0]['Id']} «{ad.get('title','')[:30]}...»")

        kws = [k for k in group.get("keywords", []) if k.strip()]
        if kws:
            items = [{"Keyword": k, "AdGroupId": adgroup_id, "Bid": rubles_to_micros(args.default_bid)} for k in kws]
            res = call(endpoint, "keywords", {"method": "add", "params": {"Keywords": items}}, args.token, args.client_login)
            if "error" in res:
                L(f"    Ошибка ключей: {res['error']}")
            else:
                L(f"    Ключи: {len(res['result']['AddResults'])}")

    L("")
    L("Готово. Кампания в DRAFT — зайди в интерфейс Директа и активируй вручную.")
    (workspace / "campaign_run.log").write_text("\n".join(log), encoding="utf-8")


if __name__ == "__main__":
    main()
