"""第 4 批估值修正；合成財報沿用 nowcast 測試的金額與股數。"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screener import detect as dt
from screener import eps_nowcast as en
from screener import val_card as vc


def _quarterly():
    periods = pd.period_range("2021Q1", "2025Q4", freq="Q-DEC")
    return pd.DataFrame({
        "period_end": periods.to_timestamp(how="end").normalize(),
        "revenue": 100.0, "gross_profit": 30.0, "op_income": 10.0,
        "pretax_income": 15.0, "net_income": 12.0, "ni_parent": 12.0,
        "eps": 1.2,
    })


def _monthly():
    return pd.Series(100.0 / 3.0, index=pd.date_range("2022-01-01", "2026-03-01", freq="MS"))


def test_tax_default_when_pretax_nonpositive():
    q = _quarterly()
    q.loc[q.index[-8:], "pretax_income"] = -15.0
    r = en.nowcast(q, _monthly())
    assert r["params"]["t"] == en.DEFAULT_TAX_RATE
    assert any("稅率改用 20%" in f for f in r["flags"])


def test_minority_opposite_sign_rejected():
    q = _quarterly()
    q["net_income"] = -12.0
    r = en.nowcast(q, _monthly())
    assert not r["ok"]
    assert "方向不一致" in r["reason"]


def test_g3_not_needed_when_three_months_present():
    m = _monthly().drop(pd.Timestamp("2025-01-01"))
    r = en.nowcast(_quarterly(), m)
    assert r["params"]["g3"] is None
    assert r["ok"]
    assert r["nc_quarters"][-1]["rev"] == pytest.approx(100.0)


def test_g3_needed_when_month_missing():
    m = _monthly().drop([pd.Timestamp("2025-01-01"), pd.Timestamp("2026-02-01")])
    r = en.nowcast(_quarterly(), m)
    assert r["params"]["g3"] is None
    assert en._estimate(en._normalize_q(_quarterly()), en._normalize_monthly(m),
                        pd.Period("2026Q1"), r, basis="latest") is None
    assert "近三月或去年同期月營收不足，無法計算 g3" in r["flags"]


def test_monthly_keeps_nan():
    rev = pd.DataFrame({"month": ["2026-01", "2026-02"], "revenue": [30.0, np.nan]})
    m = vc._monthly(rev)
    assert m.index[-1] == pd.Timestamp("2026-02-01")
    assert pd.isna(m.iloc[-1])
    r = en.nowcast(_quarterly(), m)
    assert any("月營收有非有限值" in f for f in r["flags"])
    assert dt.revenue_caliber(_quarterly(), m).level == "ok"


def test_bvps_stale_returns_none():
    last = pd.Timestamp("2026-03-31")
    dates = [last - pd.Timedelta(days=n) for n in (40, 10, 0)]
    px = pd.DataFrame({"date": dates, "close": 20.0})
    assert vc._bvps(pd.DataFrame({"date": dates[:1], "pbr": 2.0}), px) is None
    assert vc._bvps(pd.DataFrame({"date": dates[1:2], "pbr": 2.0}), px) == 10.0


def test_quarter_sanity_flags():
    q = _quarterly()
    q.loc[q.index[-1], ["eps", "ni_parent"]] = [0.09, -6e7]
    c = dt.quarter_sanity(q.sample(frac=1, random_state=4))
    assert c.level == "degrade" and c.value == 1
    assert "2025Q4" in c.why
    q = _quarterly()
    q.loc[q.index[-1], ["revenue", "gross_profit"]] = [0.0, 0.0]
    assert dt.quarter_sanity(q, construction=True).level == "ok"
    q.loc[q.index[-1], "revenue"] = -1.0
    assert dt.quarter_sanity(q).level == "degrade"
    q = _quarterly()
    q.loc[q.index[-1], "gross_profit"] = 101.0
    assert dt.quarter_sanity(q).level == "degrade"
    assert dt.quarter_sanity(_quarterly()).level == "ok"
    assert dt.quarter_sanity(_quarterly().drop(columns=["ni_parent", "gross_profit"])).level == "ok"
