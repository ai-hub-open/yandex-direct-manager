"""Чистая логика forecast_cpc: парсинг ставок, чанки, отчёты, выбор бэкенда."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.forecast_cpc import (
    MICRO,
    TV_BASE,
    TV_OPTIMISTIC,
    TV_PESSIMISTIC,
    DirectApiSession,
    Live4Session,
    _extract_bid_list,
    _fmt_num,
    _price_or_none,
    build_phrase_report,
    build_probe_campaign,
    build_probe_report,
    chunk_list,
    parse_bids,
    price_at,
    read_phrases,
    resolve_phrases_backend,
    write_phrase_csv,
)


def _auction_items():
    return [
        {"TrafficVolume": 62, "Price": 12_000_000},
        {"TrafficVolume": 75, "Price": 28_000_000},
        {"TrafficVolume": 100, "Price": 55_000_000},
    ]


def test_extract_bid_list_three_shapes():
    items = [{"KeywordId": 1}]
    assert _extract_bid_list({"data": {"KeywordBids": items}}) == items
    assert _extract_bid_list({"result": {"KeywordBids": items}}) == items
    assert _extract_bid_list({"KeywordBids": items}) == items
    assert _extract_bid_list({}) == []


def test_price_at_micro_and_missing():
    assert price_at(_auction_items(), TV_BASE) == 28.0
    assert price_at(_auction_items(), TV_OPTIMISTIC) == 12.0
    assert price_at(_auction_items(), TV_PESSIMISTIC) == 55.0
    assert price_at([], 75) is None
    assert price_at([{"TrafficVolume": 75}], 75) is None  # нет Price


def test_parse_bids_medians_and_region_factor():
    response = {
        "result": {
            "KeywordBids": [
                {"KeywordId": 1, "CampaignId": 9,
                 "Search": {"AuctionBids": {"AuctionBidItems": _auction_items()}}},
                {"KeywordId": 2, "CampaignId": 9,
                 "Search": {"AuctionBids": {"AuctionBidItems": [
                     {"TrafficVolume": 62, "Price": 10_000_000},
                     {"TrafficVolume": 75, "Price": 30_000_000},
                     {"TrafficVolume": 100, "Price": 60_000_000},
                 ]}}},
            ]
        }
    }
    r = parse_bids(response)
    assert r["n_keywords"] == 2
    assert r["base"] == 29  # median(28, 30)
    assert r["optimistic"] == 11
    assert r["pessimistic"] == 58
    r2 = parse_bids(response, region_factor=2.0)
    assert r2["base"] == 58


def test_chunk_list():
    assert chunk_list([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert chunk_list([], 10) == []
    assert chunk_list([1, 2], 10) == [[1, 2]]


def test_read_phrases_skips_comments_headers_dedupes(tmp_path):
    f = tmp_path / "phrases.csv"
    f.write_text(
        "phrase,extra\n"
        "Купить диван,1\n"
        "# комментарий\n"
        "\n"
        "купить диван,2\n"
        "keyword,ignore\n"
        "диван москва\n",
        encoding="utf-8",
    )
    phrases = read_phrases(f, "ещё одна,Купить диван")
    assert phrases == ["Купить диван", "диван москва", "ещё одна"]


def test_build_probe_campaign_variants():
    for v in ("unified_highest", "unified_wb", "text_highest"):
        payload = build_probe_campaign(v, "n", "2026-08-07")
        assert payload["Name"] == "n"
        assert payload["StartDate"] == "2026-08-07"
    wb = build_probe_campaign("unified_wb", "n", "2026-08-07")
    limit = wb["UnifiedCampaign"]["BiddingStrategy"]["Search"]["WbMaximumClicks"]["WeeklySpendLimit"]
    assert limit == 300 * MICRO
    with pytest.raises(ValueError, match="Неизвестный вариант"):
        build_probe_campaign("nope", "n", "2026-08-07")


def test_price_or_none():
    assert _price_or_none(12.5) == 12.5
    assert _price_or_none(0) is None
    assert _price_or_none(-1) is None
    assert _price_or_none(None) is None


def test_build_phrase_report_mapping_and_thin_data():
    forecast = {
        "phrase_rows": [
            {"Phrase": "a", "Min": 10, "PremiumMin": 20, "PremiumMax": 40,
             "Shows": 100, "Clicks": 5, "CTR": 5.0, "AuctionBids": []},
        ],
        "chunk_errors": [{"phrases": ["b"], "reason": "timeout"}],
    }
    report = build_phrase_report(forecast, ["a", "b", "c"], [213])
    assert report["cpc_source"] == "budget-forecast-v4"
    by = {k["phrase"]: k for k in report["per_keyword"]}
    assert by["a"]["status"] == "ok"
    assert by["a"]["cpc_optimistic"] == 10
    assert by["a"]["cpc_base"] == 20
    assert by["a"]["cpc_pessimistic"] == 40
    assert by["b"]["status"] == "chunk_error"
    assert by["c"]["status"] == "no_forecast_data"
    assert report["thin_data"] is True  # 1 ok из 3
    assert report["n_ok"] == 1


def test_build_probe_report():
    probe = {
        "phrase_by_kid": {111: "купить диван", 222: "без аукциона"},
        "rejected": [{"phrase": "bad", "reason": "модерация"}],
        "bids": [{
            "KeywordId": 111,
            "Search": {"AuctionBids": {"AuctionBidItems": _auction_items()}},
        }],
        "campaign_id": 999,
        "campaign_variant": "unified_highest",
    }
    report = build_probe_report(probe, [213])
    assert report["cpc_source"] == "live-auction-draft-probe"
    by = {k["phrase"]: k for k in report["per_keyword"]}
    assert by["купить диван"]["status"] == "ok"
    assert by["купить диван"]["cpc_base"] == 28.0
    assert by["без аукциона"]["status"] == "no_auction_data"
    assert by["bad"]["status"] == "rejected"
    assert report["thin_data"] is True  # 1 ok из 3


def test_fmt_num_and_csv(tmp_path):
    assert _fmt_num(None) == ""
    assert _fmt_num(52.0) == "52"
    assert _fmt_num(52.5) == "52.5"
    assert _fmt_num(1_234_567) == "1234567"
    path = tmp_path / "out.csv"
    report = {
        "per_keyword": [{
            "phrase": "a", "cpc_optimistic": 10.0, "cpc_base": 20.5,
            "cpc_pessimistic": None, "forecast_shows": 100, "forecast_clicks": 5,
            "status": "ok",
        }],
    }
    write_phrase_csv(report, path)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # utf-8-sig
    text = path.read_text(encoding="utf-8-sig")
    assert "phrase,cpc_optimistic" in text
    assert "a,10,20.5,,100,5,ok" in text


def test_direct_session_init_and_build_request():
    with pytest.raises(ValueError, match="Неизвестный режим"):
        DirectApiSession("other", token="t")
    with pytest.raises(ValueError, match="токен"):
        DirectApiSession("clickru", client_login="login")
    with pytest.raises(ValueError, match="логин"):
        DirectApiSession("clickru", clickru_token="t")
    with pytest.raises(ValueError, match="песочницу"):
        DirectApiSession("clickru", clickru_token="t", client_login="l", sandbox=True)
    with pytest.raises(ValueError, match="YANDEX_DIRECT_TOKEN"):
        DirectApiSession("direct")

    direct = DirectApiSession("direct", token="tok", client_login="me")
    url, headers = direct.build_request("campaigns")
    assert url.endswith("/campaigns")
    assert headers["Authorization"] == "Bearer tok"
    assert headers["Client-Login"] == "me"

    click = DirectApiSession("clickru", clickru_token="ct", client_login="cl",
                             clickru_user_id="42")
    url, headers = click.build_request("keywords")
    assert "api.click.ru" in url
    assert headers["X-Auth-Token"] == "ct"
    assert headers["Client-Login"] == "cl"
    assert headers["X-Auth-UserId"] == "42"
    assert "Authorization" not in headers


def test_resolve_phrases_backend_paths(monkeypatch):
    args = SimpleNamespace(via_clickru=False, sandbox=False, client_login=None)

    monkeypatch.setattr("scripts.forecast_cpc._load_credential",
                        lambda s: "y0_tok" if s == "yandex_direct" else None)
    name, session = resolve_phrases_backend(args)
    assert name == "v4"
    assert isinstance(session, Live4Session)

    def creds(s):
        return {"clickru": "ct", "clickru_login": "login"}.get(s)

    monkeypatch.setattr("scripts.forecast_cpc._load_credential", creds)
    args.via_clickru = True
    name, session = resolve_phrases_backend(args)
    assert name == "probe"
    assert isinstance(session, DirectApiSession)
    assert session.mode == "clickru"

    monkeypatch.setattr("scripts.forecast_cpc._load_credential", lambda s: None)
    args.via_clickru = False
    with pytest.raises(SystemExit, match="не найден ни прямой"):
        resolve_phrases_backend(args)

    args.via_clickru = True
    with pytest.raises(SystemExit, match="Click.ru"):
        resolve_phrases_backend(args)
