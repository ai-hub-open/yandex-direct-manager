"""Бэкенды forecast_cpc: Live API v4 и Click.ru DRAFT через фейковую сессию."""
from __future__ import annotations

import pytest

from scripts.forecast_cpc import (
    FORECAST_TIMEOUT,
    MAX_KEYWORDS_PER_GROUP,
    MAX_PHRASES_PER_FORECAST,
    ForecastError,
    create_forecast,
    delete_forecast,
    fetch_forecast,
    get_keyword_bids,
    run_budget_forecast,
    run_phrase_probe,
    wait_forecast,
)


class FakeSession:
    """Duck-typed session: .call(...) возвращает заранее заготовленные ответы."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []
        self.last_units = None

    def call(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        # Live4Session: call(method, param=None)
        # DirectApiSession: call(service, method, params)
        return self.handler(*args, **kwargs)


def _v4_handler(*, create_ok=True, list_done=True, fetch_ok=True, delete_ok=True,
                phrases=None, create_error=None, fetch_error=None):
    phrases = phrases or [
        {"Phrase": "купить диван", "Min": 12, "PremiumMin": 28, "PremiumMax": 55,
         "Shows": 100, "Clicks": 5, "CTR": 5.0, "AuctionBids": []},
    ]
    report_ids = {"n": 0}

    def handler(method, param=None):
        if method == "CreateNewForecast":
            if not create_ok:
                return create_error or {"error_str": "quota"}
            report_ids["n"] += 1
            return {"data": 1000 + report_ids["n"]}
        if method == "GetForecastList":
            rid = 1000 + report_ids["n"]
            status = "Done" if list_done else "Pending"
            return {"data": [{"ForecastID": rid, "StatusForecast": status}]}
        if method == "GetForecast":
            if not fetch_ok:
                return fetch_error or {"error_str": "gone"}
            return {"data": {"Phrases": phrases}}
        if method == "DeleteForecastReport":
            return {"data": True} if delete_ok else {"error_str": "no"}
        raise AssertionError(f"unexpected method {method}")

    return handler


def test_v4_happy_path(fast_sleep):
    session = FakeSession(_v4_handler())
    out = run_budget_forecast(session, ["купить диван"], [213])
    assert len(out["phrase_rows"]) == 1
    assert out["chunk_errors"] == []
    methods = [c[0][0] for c in session.calls]
    assert methods == [
        "CreateNewForecast", "GetForecastList", "GetForecast", "DeleteForecastReport",
    ]


def test_v4_chunks_by_100(fast_sleep):
    phrases = [f"фраза {i}" for i in range(MAX_PHRASES_PER_FORECAST + 3)]
    session = FakeSession(_v4_handler(phrases=[{"Phrase": p, "Min": 1, "PremiumMin": 2,
                                                 "PremiumMax": 3} for p in phrases[:1]]))
    run_budget_forecast(session, phrases, [213])
    creates = [c for c in session.calls if c[0][0] == "CreateNewForecast"]
    assert len(creates) == 2
    assert len(creates[0][0][1]["Phrases"]) == MAX_PHRASES_PER_FORECAST
    assert len(creates[1][0][1]["Phrases"]) == 3


def test_v4_deletes_report_even_when_fetch_fails(fast_sleep):
    # wait succeeds, fetch fails → chunk_errors; без phrase_rows → SystemExit,
    # но delete в finally уже вызван.
    session = FakeSession(_v4_handler(fetch_ok=False))
    with pytest.raises(SystemExit, match="все чанки"):
        run_budget_forecast(session, ["a"], [213])
    methods = [c[0][0] for c in session.calls]
    assert "DeleteForecastReport" in methods
    assert methods.index("DeleteForecastReport") > methods.index("GetForecast")


def test_v4_create_error_is_forecast_error():
    session = FakeSession(_v4_handler(create_ok=False,
                                      create_error={"error_code": 56, "error_str": "limit"}))
    with pytest.raises(ForecastError, match="limit"):
        create_forecast(session, ["a"], [213])


def test_v4_partial_chunk_failure(fast_sleep):
    state = {"n": 0}

    def handler(method, param=None):
        if method == "CreateNewForecast":
            state["n"] += 1
            if state["n"] == 1:
                return {"error_str": "first chunk boom"}
            return {"data": 42}
        if method == "GetForecastList":
            return {"data": [{"ForecastID": 42, "StatusForecast": "Done"}]}
        if method == "GetForecast":
            return {"data": {"Phrases": [{"Phrase": "ok", "Min": 1, "PremiumMin": 2,
                                         "PremiumMax": 3}]}}
        if method == "DeleteForecastReport":
            return {"data": True}
        raise AssertionError(method)

    # 101 фраз → 2 чанка
    phrases = [f"p{i}" for i in range(101)]
    session = FakeSession(handler)
    out = run_budget_forecast(session, phrases, [213])
    assert out["phrase_rows"]
    assert len(out["chunk_errors"]) == 1
    assert "boom" in out["chunk_errors"][0]["reason"]


def test_v4_poll_timeout(fast_sleep, monkeypatch):
    monkeypatch.setattr("scripts.forecast_cpc.FORECAST_TIMEOUT", 30)
    monkeypatch.setattr("scripts.forecast_cpc.FORECAST_POLL_INTERVAL", 15)

    def handler(method, param=None):
        if method == "GetForecastList":
            return {"data": [{"ForecastID": 7, "StatusForecast": "Pending"}]}
        raise AssertionError(method)

    session = FakeSession(handler)
    with pytest.raises(ForecastError, match="не готов"):
        wait_forecast(session, 7)


def test_v4_delete_forecast_bool():
    assert delete_forecast(FakeSession(lambda *a, **k: {"data": 1}), 1) is True
    assert delete_forecast(FakeSession(lambda *a, **k: {"error_str": "x"}), 1) is False


def test_v4_fetch_requires_data():
    with pytest.raises(ForecastError, match="GetForecast"):
        fetch_forecast(FakeSession(lambda *a, **k: {"error_str": "no"}), 1)


# --- Click.ru DRAFT ---


def _probe_handler(*, campaign_fail_first=False, fail_on=None, delete_ok=True,
                   reject_keyword=False, bids_fail_times=0):
    """fail_on: service name that should return error once campaign exists."""
    state = {"campaign_attempts": 0, "bid_attempts": 0, "deleted": False}

    def handler(service, method, params):
        if service == "campaigns" and method == "add":
            state["campaign_attempts"] += 1
            if campaign_fail_first and state["campaign_attempts"] == 1:
                return {"error": {"error_string": "unified not allowed"}}
            return {"result": {"AddResults": [{"Id": 9001}]}}
        if service == "campaigns" and method == "delete":
            state["deleted"] = True
            if not delete_ok:
                return {"error": {"error_string": "busy"}}
            return {"result": {}}
        if service == "adgroups" and method == "add":
            if fail_on == "adgroups":
                return {"error": {"error_string": "adgroups boom"}}
            n = len(params["AdGroups"])
            return {"result": {"AddResults": [{"Id": 100 + i} for i in range(n)]}}
        if service == "ads" and method == "add":
            if fail_on == "ads":
                return {"error": {"error_string": "ads boom"}}
            n = len(params["Ads"])
            return {"result": {"AddResults": [{"Id": 200 + i} for i in range(n)]}}
        if service == "keywords" and method == "add":
            if fail_on == "keywords":
                return {"error": {"error_string": "keywords boom"}}
            results = []
            for i, item in enumerate(params["Keywords"]):
                if reject_keyword and i == 0:
                    results.append({"Errors": [{"Message": "стоп-слово", "Code": 1}]})
                else:
                    results.append({"Id": 3000 + i})
            return {"result": {"AddResults": results}}
        if service == "keywordbids" and method == "get":
            state["bid_attempts"] += 1
            if state["bid_attempts"] <= bids_fail_times:
                return {"error": {"error_string": "temporary"}}
            kids = params["SelectionCriteria"]["KeywordIds"]
            return {"result": {"KeywordBids": [
                {"KeywordId": kid, "CampaignId": 9001,
                 "Search": {"AuctionBids": {"AuctionBidItems": [
                     {"TrafficVolume": 62, "Price": 10_000_000},
                     {"TrafficVolume": 75, "Price": 20_000_000},
                     {"TrafficVolume": 100, "Price": 30_000_000},
                 ]}}}
                for kid in kids
            ]}}
        raise AssertionError(f"unexpected {service}.{method}")

    handler.state = state
    return handler


def test_clickru_happy_path_deletes_draft(fast_sleep):
    handler = _probe_handler()
    session = FakeSession(handler)
    out = run_phrase_probe(session, ["купить диван", "диван москва"], [213])
    assert out["campaign_id"] == 9001
    assert len(out["phrase_by_kid"]) == 2
    assert handler.state["deleted"] is True
    services = [c[0][0] for c in session.calls]
    assert services[:5] == ["campaigns", "adgroups", "ads", "keywords", "keywordbids"]
    assert services[-1] == "campaigns"  # delete


def test_clickru_tries_next_campaign_variant(fast_sleep):
    handler = _probe_handler(campaign_fail_first=True)
    session = FakeSession(handler)
    out = run_phrase_probe(session, ["a"], [213])
    assert out["campaign_variant"] == "unified_wb"
    assert handler.state["campaign_attempts"] == 2


def test_clickru_deletes_even_when_keywords_fail(fast_sleep):
    handler = _probe_handler(fail_on="keywords")
    session = FakeSession(handler)
    with pytest.raises(SystemExit, match="keywords"):
        run_phrase_probe(session, ["a"], [213])
    assert handler.state["deleted"] is True


def test_clickru_keep_campaign_skips_delete(fast_sleep):
    handler = _probe_handler()
    session = FakeSession(handler)
    run_phrase_probe(session, ["a"], [213], keep_campaign=True)
    assert handler.state["deleted"] is False
    assert not any(c[0][0] == "campaigns" and c[0][1] == "delete" for c in session.calls)


def test_clickru_delete_failure_is_warning_not_raise(fast_sleep, capsys):
    handler = _probe_handler(delete_ok=False)
    session = FakeSession(handler)
    out = run_phrase_probe(session, ["a"], [213])
    assert out["campaign_id"] == 9001
    err = capsys.readouterr().err
    assert "не удалось удалить" in err


def test_clickru_partial_keyword_rejects(fast_sleep):
    handler = _probe_handler(reject_keyword=True)
    session = FakeSession(handler)
    out = run_phrase_probe(session, ["bad", "good"], [213])
    assert len(out["rejected"]) == 1
    assert out["rejected"][0]["phrase"] == "bad"
    assert "good" in out["phrase_by_kid"].values()


def test_clickru_chunks_keywords_by_200(fast_sleep):
    handler = _probe_handler()
    session = FakeSession(handler)
    phrases = [f"p{i}" for i in range(MAX_KEYWORDS_PER_GROUP + 5)]
    run_phrase_probe(session, phrases, [213])
    adgroup_calls = [c for c in session.calls if c[0][0] == "adgroups"]
    assert len(adgroup_calls[0][0][2]["AdGroups"]) == 2


def test_clickru_keywordbids_retries(fast_sleep):
    handler = _probe_handler(bids_fail_times=2)
    session = FakeSession(handler)
    # get_keyword_bids напрямую
    bids = get_keyword_bids(session, [1, 2])
    assert len(bids) == 2
    bid_calls = [c for c in session.calls if c[0][0] == "keywordbids"]
    assert len(bid_calls) == 3


def test_empty_phrases_exits():
    with pytest.raises(SystemExit, match="пуст"):
        run_phrase_probe(FakeSession(lambda *a, **k: {}), [], [213])
    with pytest.raises(SystemExit, match="пуст"):
        run_budget_forecast(FakeSession(lambda *a, **k: {}), [], [213])
