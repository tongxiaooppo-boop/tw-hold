"""scripts.fetch_global_macro 的純邏輯部分（過期偵測 + 重試合併），不打網路。"""
from __future__ import annotations

import pandas as pd

from scripts.fetch_global_macro import _business_days_since, _check_staleness, _retry_stale


def _df(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    d = pd.DataFrame(rows, columns=["symbol", "date", "close"])
    d["date"] = pd.to_datetime(d["date"])
    return d


def test_全部同一天沒有過期():
    df = _df([("^DJI", "2026-09-14", 1.0), ("AAPL", "2026-09-14", 2.0)])
    assert _check_staleness(df) == []


def test_落後超過門檻才算過期():
    df = _df([
        ("^DJI", "2026-09-14", 1.0),
        ("AAPL", "2026-09-11", 2.0),  # 落後 3 天，不過門檻是 > 3 天，剛好卡邊界不算
    ])
    assert _check_staleness(df) == []

    df2 = _df([
        ("^DJI", "2026-09-14", 1.0),
        ("AAPL", "2026-09-10", 2.0),  # 落後 4 天，超過門檻
    ])
    stale = _check_staleness(df2)
    assert len(stale) == 1
    assert stale[0]["symbol"] == "AAPL"
    assert stale[0]["lag_days"] == 4


def test_亞股門檻放寬到7天_一般symbol還是3天():
    # 恆生落後 6 天——一般 symbol（3 天門檻）會算過期，恆生（7 天門檻）不算
    # （2026-09-22 Opus 審出：日經/恆生/KOSPI 遇國定連假用同一個 3 天門檻會
    # 連續好幾天誤報）。
    df = _df([
        ("^DJI", "2026-09-16", 1.0),
        ("^HSI", "2026-09-10", 2.0),   # 落後 6 天
    ])
    assert _check_staleness(df) == []

    df2 = _df([
        ("^DJI", "2026-09-16", 1.0),
        ("^HSI", "2026-09-08", 2.0),   # 落後 8 天，超過 7 天門檻
    ])
    stale = _check_staleness(df2)
    assert len(stale) == 1
    assert stale[0]["symbol"] == "^HSI"


def test_business_days_since跳過週末():
    import datetime as _dt
    # 週五到下週一，中間隔一個週末，只算 1 個營業日
    fri = _dt.date(2026, 9, 18)
    mon = _dt.date(2026, 9, 21)
    assert _business_days_since(fri, mon) == 1
    assert _business_days_since(fri, fri) == 0


def test_retry_stale用重試資料蓋掉過期尾端(monkeypatch):
    df = _df([
        ("^DJI", "2026-09-10", 1.0),
        ("^DJI", "2026-09-11", 1.1),
        ("AAPL", "2026-09-10", 2.0),
        ("AAPL", "2026-09-11", 2.1),  # 這檔過期，重試會補上 09-14
    ])

    class _FakeRetry:
        def __init__(self):
            self.index = pd.to_datetime(["2026-09-11", "2026-09-14"])
            self.index.name = "Date"
            self.columns = ["Close"]

        def __getitem__(self, cols):
            return pd.DataFrame({"Close": [2.1, 2.4]}, index=self.index)

    def fake_download(sym, **kw):
        assert sym == "AAPL"
        return _FakeRetry()

    monkeypatch.setattr("scripts.fetch_global_macro.yf.download", fake_download)
    merged = _retry_stale(df, ["AAPL"])

    aapl = merged[merged["symbol"] == "AAPL"].sort_values("date")
    assert aapl["date"].max() == pd.Timestamp("2026-09-14")
    assert len(aapl) == 3  # 09-10（舊資料留著）+ 09-11（重試覆蓋）+ 09-14（重試新增）
    # ^DJI 沒被動到
    dji = merged[merged["symbol"] == "^DJI"]
    assert len(dji) == 2
