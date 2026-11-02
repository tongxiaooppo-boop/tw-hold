"""第 4 批估值修正；合成財報沿用 nowcast 測試的金額與股數。"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screener import detect as dt
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














def test_quarter_sanity_flags():
    q = _quarterly()
    q.loc[q.index[-1], ["eps", "ni_parent"]] = [0.09, -6e7]
    c = dt.quarter_sanity(q.sample(frac=1, random_state=4))
    assert c.level == "warn" and c.value == 1
    assert "2025Q4" in c.why
    q = _quarterly()
    q.loc[q.index[-1], ["revenue", "gross_profit"]] = [0.0, 0.0]
    assert dt.quarter_sanity(q, construction=True).level == "ok"
    q.loc[q.index[-1], "revenue"] = -1.0
    assert dt.quarter_sanity(q).level == "warn"
    q = _quarterly()
    q.loc[q.index[-1], "gross_profit"] = 101.0
    assert dt.quarter_sanity(q).level == "warn"
    assert dt.quarter_sanity(_quarterly()).level == "ok"
    assert dt.quarter_sanity(_quarterly().drop(columns=["ni_parent", "gross_profit"])).level == "ok"




def test_quarter_sanity_runs_without_monthly():
    """sol 審查 D4-1：沒有月營收（試算跑不了）也要查財報矛盾。"""
    q = _quarterly()
    q.loc[q.index[-1], ["eps", "ni_parent"]] = [0.09, -6e7]
    px = pd.DataFrame({"date": pd.to_datetime(["2026-03-02"]), "close": [50.0]})
    card = vc.build_card(q, pd.DataFrame(columns=["month", "revenue"]), px,
                         {"type": "normal", "decided_at": "2025-12-31", "state": [], "subtags": [], "metrics": {}},
                         None, None, None, pd.Timestamp("2026-03-02"))
    assert any(c["name"] == "財報矛盾" for c in card["status"]["data"]["items"])
