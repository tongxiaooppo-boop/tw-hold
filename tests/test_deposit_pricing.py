"""M2 §7.1/§7.3/§7.4：定存兩道新硬門檻 + 殖利率法買價 / verdict。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from screener.deposit_pricing import (add_deposit_verdict, fill_rates,
                                      incl_div_return_3y, yield_history)

ASOF = pd.Timestamp("2026-09-07")


def _raw(ticker, fills: list[bool]):
    """每個 bool 造一次除息事件：True = 除息後填息、False = 沒填。"""
    rows, evs = [], []
    base = ASOF - pd.DateOffset(years=len(fills) + 1)
    for i, filled in enumerate(fills):
        ex = base + pd.DateOffset(years=i + 1)
        pre = pd.date_range(ex - pd.Timedelta(days=30), ex - pd.Timedelta(days=1), freq="D")
        post = pd.date_range(ex, ex + pd.Timedelta(days=90), freq="D")
        rows += [dict(date=d, ticker=ticker, close=100.0) for d in pre]
        recover = 100.0 if filled else 96.0        # 除息後 30 天內回到的價位
        rows += [dict(date=d, ticker=ticker,
                      close=(95.0 if j < 20 else recover))
                 for j, d in enumerate(post)]
        evs.append(dict(ticker=ticker, ex_date=ex, cash_dividend=5.0,
                        announce_date=ex - pd.Timedelta(days=30)))
    return pd.DataFrame(rows), pd.DataFrame(evs)


def test_fill_rates_填息比率():
    raw, div = _raw("1001", [True, True, False, True])   # 3/4
    fr = fill_rates(raw, div, ASOF)
    assert abs(fr["1001"] - 0.75) < 1e-9


def test_incl_div_return_3y_年化():
    dates = pd.date_range(ASOF - pd.DateOffset(years=4), ASOF, freq="D")
    adj = pd.DataFrame({"date": dates, "ticker": "1001",
                        "close": np.linspace(100, 200, len(dates))})
    r = incl_div_return_3y(adj, ASOF)
    assert r["1001"] > 0


def test_yield_history_分位():
    dates = pd.date_range(ASOF - pd.DateOffset(years=5), ASOF, freq="D")
    yld = np.linspace(3.0, 6.0, len(dates))          # 殖利率一路走高，當前在高位
    per = pd.DataFrame({"ticker": "1001", "date": dates, "per": 12.0,
                        "dividend_yield": yld})
    yh = yield_history(per, ASOF).set_index("ticker").loc["1001"]
    assert 0.03 < yh["avg_yield_5y"] < 0.06
    assert yh["yield_pctile_5y"] > 0.9


def _dep_row(**kw):
    base = dict(ticker="1001", close=100.0, avg_cash_dividend_3y=6.0,
                passes=True, reject_reason=np.nan, safety_score=0.5)
    base.update(kw)
    return pd.DataFrame([base])


def _flat_adj(ticker, close):
    dates = pd.date_range(ASOF - pd.DateOffset(years=4), ASOF, freq="D")
    return pd.DataFrame({"date": dates, "ticker": ticker, "close": float(close)})


def test_verdict_殖利率達標_推薦():
    dep = _dep_row(close=100.0, avg_cash_dividend_3y=6.0)   # cur_yield 6% ≥ 5%
    raw, div = _raw("1001", [True, True, True])             # 填息率 100%
    out = add_deposit_verdict(dep, raw, _flat_adj("1001", 100), None, div, asof=ASOF).iloc[0]
    assert out["verdict"] == "推薦"
    assert out["yield_floor"] == 0.05


def test_verdict_殖利率不足_觀望不剔除():
    dep = _dep_row(close=200.0, avg_cash_dividend_3y=6.0)   # cur_yield 3% < 5%
    raw, div = _raw("1001", [True, True, True])
    out = add_deposit_verdict(dep, raw, _flat_adj("1001", 200), None, div, asof=ASOF).iloc[0]
    assert out["passes"]                                    # 沒被剔除
    assert out["verdict"].startswith("觀望")


def test_填息率不足_硬剔除():
    dep = _dep_row()
    raw, div = _raw("1001", [False, False, True, False])    # 1/4 < 60%
    out = add_deposit_verdict(dep, raw, _flat_adj("1001", 100), None, div, asof=ASOF).iloc[0]
    assert not out["passes"]
    assert out["reject_reason"] == "填息率 < 60%（近5年）"


def test_raw_缺_填息率不擋_但推薦降觀望():
    dep = _dep_row(close=100.0, avg_cash_dividend_3y=6.0)
    div = pd.DataFrame([dict(ticker="1001", ex_date=ASOF - pd.DateOffset(years=1),
                             cash_dividend=5.0, announce_date=ASOF)])
    out = add_deposit_verdict(dep, None, _flat_adj("1001", 100), None, div, asof=ASOF).iloc[0]
    assert out["passes"]                                    # 填息率門檻略過
    assert "填息率未驗" in out["verdict"]
