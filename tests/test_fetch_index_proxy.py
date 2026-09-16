"""scripts/fetch_index_proxy.py（006201，向 FinMind 全量重抓）落地前的驗證接線。

2026-09-16 加：原本抓到就整份覆寫、零驗證——而 FinMind 實測真的會吐 close=0
（落地檔裡 2016-08-24／2017-04-10 兩筆）。驗證條件本身見 test_price_series_guard.py，
這支只測接線：清得掉的要照樣落地，拒絕時舊檔不能被動到。
"""
from __future__ import annotations

import pandas as pd
import pytest

from reference import price_series_guard as guard
from scripts import fetch_index_proxy as m

N = guard.MIN_ROWS + 50


def _df(n=N, start="2011-01-03"):
    dates = pd.bdate_range(start, periods=n)
    return pd.DataFrame({"date": dates,
                         "close": [10.0 * (1.001 ** i) for i in range(n)]})


@pytest.fixture(autouse=True)
def _out(monkeypatch, tmp_path):
    p = tmp_path / "index_006201.parquet"
    monkeypatch.setattr(m, "OUT", p)
    return p


def test_FinMind吐的0收盤被清掉_照樣落地(_out, monkeypatch):
    bad = _df()
    bad.loc[100, "close"] = 0.0
    monkeypatch.setattr(m, "fetch", lambda: bad)
    assert m.main() == 0
    out = pd.read_parquet(_out)
    assert len(out) == N - 1 and (out["close"] > 0).all()


def test_只回一小段歷史就拒絕_保留舊檔(_out, monkeypatch):
    _df().to_parquet(_out, index=False)
    monkeypatch.setattr(m, "fetch", lambda: _df().tail(20).reset_index(drop=True))
    assert m.main() == 1
    assert len(pd.read_parquet(_out)) == N          # 舊檔沒被蓋掉


def test_正常資料就覆寫(_out, monkeypatch):
    _df(n=N - 1).to_parquet(_out, index=False)
    monkeypatch.setattr(m, "fetch", lambda: _df())
    assert m.main() == 0
    assert len(pd.read_parquet(_out)) == N
