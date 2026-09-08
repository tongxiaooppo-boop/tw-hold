"""G2：未還原 / 還原搞混偵測（PRD §10.2）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from screener.gates import GateError, assert_raw_not_adjusted

EX = pd.Timestamp("2024-07-04")


def _div(ticker="2412", cash=5.0):
    return pd.DataFrame([dict(ticker=ticker, ex_date=EX, cash_dividend=cash,
                              announce_date=EX - pd.Timedelta(days=30))])


def _series(ticker, before, after, n=90):
    pre = pd.date_range(EX - pd.Timedelta(days=n), EX - pd.Timedelta(days=1), freq="D")
    post = pd.date_range(EX, EX + pd.Timedelta(days=n), freq="D")
    return pd.DataFrame({
        "date": [*pre, *post],
        "ticker": ticker,
        "close": [before] * len(pre) + [after] * len(post),
    })


def test_raw_有除息跳空_adj_沒有_通過():
    raw = _series("2412", 100.0, 94.0)      # −6% 跳空
    adj = _series("2412", 95.0, 95.0)       # 還原後無跳空
    note = assert_raw_not_adjusted(raw, adj, _div())
    assert "G2 通過" in note and "2412" in note


def test_raw_其實是還原序列_擋下():
    adj_like = _series("2412", 95.0, 95.0)  # 傳進來的「raw」根本沒跳空
    with pytest.raises(GateError, match="找不到有跳空"):
        assert_raw_not_adjusted(adj_like, adj_like, _div())


def test_raw_跳空但_adj_也跳空_擋下():
    raw = _series("2412", 100.0, 94.0)
    adj_bad = _series("2412", 100.0, 94.0)  # 「還原序列」也掉 6% → 沒還原
    with pytest.raises(GateError, match="沒有還原"):
        assert_raw_not_adjusted(raw, adj_bad, _div())


def test_raw_是_none_擋下():
    with pytest.raises(GateError, match="沒有 prices_raw_close"):
        assert_raw_not_adjusted(None, None, _div())
