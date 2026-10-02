from datetime import UTC, date, datetime

import httpx
import pytest

from btest.sources.alpaca import DATA_URL, AlpacaSource


def bar(t, c):
    return {"t": t, "o": c, "h": c, "l": c, "c": c, "v": 10, "n": 2, "vw": c}


def make(handler):
    client = httpx.Client(base_url=DATA_URL, transport=httpx.MockTransport(handler))
    return AlpacaSource("k", "s", client=client, sleep=lambda _: None)


def test_bars_paginates_retries_429_and_parses():
    calls = []

    def handler(req):
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(429)
        if "page_token" not in req.url.params:
            return httpx.Response(200, json={"bars": [bar("2024-01-02T14:30:00Z", 1.0)],
                                             "next_page_token": "p2"})
        return httpx.Response(200, json={"bars": [bar("2024-01-02T14:31:00Z", 2.0)],
                                         "next_page_token": None})

    df = make(handler).bars("SPY", datetime(2024, 1, 2, tzinfo=UTC),
                            datetime(2024, 1, 3, tzinfo=UTC))
    assert df["close"].to_list() == [1.0, 2.0]
    assert df["ts"][0] == datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    assert calls[-1].url.params["feed"] == "sip"
    assert calls[-1].url.params["adjustment"] == "raw"
    assert calls[0].headers["APCA-API-KEY-ID"] == "k"


def test_empty_bars_keep_schema():
    df = make(lambda req: httpx.Response(200, json={"bars": None, "next_page_token": None})).bars(
        "SPY", datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC))
    assert df.is_empty() and "vwap" in df.columns


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        make(lambda req: httpx.Response(200)).bars("SPY", datetime(2024, 1, 1),
                                                   datetime(2024, 1, 2))


def test_corporate_actions_parse_forward_and_reverse_splits_and_dividends():
    def handler(req):
        return httpx.Response(200, json={"next_page_token": None, "corporate_actions": {
            "forward_splits": [{"id": "f", "ex_date": "2024-06-10", "old_rate": 1,
                                "new_rate": 10}],
            "reverse_splits": [{"id": "r", "ex_date": "2020-01-02", "old_rate": 5,
                                "new_rate": 1}],
            "cash_dividends": [{"id": "d", "ex_date": "2024-03-15", "rate": 1.59,
                                "special": False, "foreign": False}],
        }})

    src = make(handler)
    splits = src.splits("X", date(2016, 1, 1), date(2026, 1, 1))
    assert {(s.source_id, s.old_rate, s.new_rate) for s in splits} == {("f", 1, 10), ("r", 5, 1)}
    [div] = src.dividends("X", date(2016, 1, 1), date(2026, 1, 1))
    assert (div.ex_date, div.rate) == (date(2024, 3, 15), 1.59)
