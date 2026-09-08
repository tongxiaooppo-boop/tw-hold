"""M1 §5：主動選股候選池（狀態型）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from screener.candidate_pool import (build_candidate_pool, canslim_fundamental,
                                     institutional_net20, trend_template)

ASOF = pd.Timestamp("2026-09-07")


def _uptrend_prices(ticker: str, n: int = 400, start: float = 50.0, drift: float = 0.004):
    dates = pd.date_range(ASOF - pd.Timedelta(days=n * 2), ASOF, freq="B")[-n:]
    close = start * (1 + drift) ** np.arange(len(dates))
    return pd.DataFrame({"date": dates, "ticker": ticker, "open": close * 0.99,
                         "high": close * 1.02, "low": close * 0.98,
                         "close": close, "volume": 1_000_000})


def _flat_index(n: int = 400):
    dates = pd.date_range(ASOF - pd.Timedelta(days=n * 2), ASOF, freq="B")[-n:]
    return pd.DataFrame({"date": dates, "close": 100.0})


def _qf(ticker: str, eps_now: float = 3.0, eps_yoy_ago: float = 1.0,
        roe: float = 0.25, fscore: float = 8, gm: float = 0.3):
    rows = []
    for i in range(20):
        pe = pd.Timestamp("2021-12-31") + pd.DateOffset(months=3 * i)
        e = eps_yoy_ago if i < 16 else eps_now
        rows.append(dict(ticker=ticker, period_end=pe, disclosure_date=pe + pd.Timedelta(days=45),
                         eps=e, ttm_eps=e * 4, roe=roe, f_score=fscore, gross_margin=gm))
    return pd.DataFrame(rows)


def _chips(ticker: str, net_per_day: float = 500.0, n: int = 40):
    dates = pd.date_range(ASOF - pd.Timedelta(days=n * 2), ASOF, freq="B")[-n:]
    return pd.DataFrame({"date": dates, "ticker": ticker,
                         "foreign_net": net_per_day, "trust_net": 0.0})


def _revenue(ticker: str, yoy: float = 0.3):
    return pd.DataFrame([dict(ticker=ticker, revenue=130.0, revenue_last_year=130.0 / (1 + yoy),
                              revenue_prev_month=125.0)])


def _revenue_hist(ticker: str, yoy: float = 0.3, accel: bool = True):
    """新長表 schema：25 個月，最後一個月 YoY = `yoy`、上月 YoY 視 `accel` 高或低。"""
    months = pd.period_range("2024-08", periods=25, freq="M").astype(str)
    base = 100.0
    rev = [base] * 13
    prev_yoy = yoy - 0.1 if accel else yoy + 0.1
    for m in range(13, 25):
        y = yoy if m == 24 else prev_yoy
        rev.append(rev[m - 12] * (1 + y))
    return pd.DataFrame({"ticker": ticker, "month": months, "revenue": rev})


def test_trend_template_上升趨勢過8條():
    tt = trend_template(_uptrend_prices("1001"), _flat_index(), ASOF)
    assert tt.loc["1001", "trend_cnt"] >= 7


def test_institutional_net20_連續買超():
    s = institutional_net20(_chips("1001", 500.0), ASOF)
    assert s["1001"] == 500.0 * 20


def test_canslim_fundamental_全過():
    f = canslim_fundamental(_qf("1001"), ASOF)
    assert f.loc["1001", ["c_eps_yoy", "c_roe", "c_fscore",
                          "c_gm_not_deteriorating"]].all()


def test_build_pool_全條件過才進_且無總分無排名():
    pool = build_candidate_pool(
        _qf("1001"), _uptrend_prices("1001"), _flat_index(),
        _chips("1001"), _revenue("1001"), universe={"1001"}, asof=ASOF)
    assert len(pool) == 1
    rec = pool[0]
    assert rec["ticker"] == "1001"
    assert "score" not in rec and "rank" not in rec and "verdict" not in rec
    assert rec["risk_stop"] < rec["close"]                 # 停損在現價之下
    assert rec["max_buy"] == round(rec["risk_stop"] / 0.9, 2)
    assert len(rec["conditions"]) == 8
    assert len(rec["invalidation"]) == 4
    assert rec["oppose"]                                   # 一定有東西（空 → 檢查不足那句）


def test_build_pool_法人賣超就不進():
    pool = build_candidate_pool(
        _qf("1001"), _uptrend_prices("1001"), _flat_index(),
        _chips("1001", -500.0), _revenue("1001"), universe={"1001"}, asof=ASOF)
    assert pool == []


def test_build_pool_營收衰退就不進():
    pool = build_candidate_pool(
        _qf("1001"), _uptrend_prices("1001"), _flat_index(),
        _chips("1001"), _revenue("1001", yoy=-0.1), universe={"1001"}, asof=ASOF)
    assert pool == []


def test_revenue_yoy_新長表_算加速():
    from screener.candidate_pool import revenue_yoy
    up = revenue_yoy(_revenue_hist("1001", yoy=0.3, accel=True))
    assert up.loc["1001", "revenue_accel"] == True          # noqa: E712
    assert abs(up.loc["1001", "revenue_yoy"] - 0.3) < 1e-6
    down = revenue_yoy(_revenue_hist("1001", yoy=0.3, accel=False))
    assert down.loc["1001", "revenue_accel"] == False       # noqa: E712


def test_build_pool_新長表營收_進池且帶accel():
    pool = build_candidate_pool(
        _qf("1001"), _uptrend_prices("1001"), _flat_index(),
        _chips("1001"), _revenue_hist("1001", yoy=0.3, accel=True),
        universe={"1001"}, asof=ASOF)
    assert len(pool) == 1 and pool[0]["revenue_accel"] is True
    assert "月營收 YoY 較上月加速" in pool[0]["support"]
