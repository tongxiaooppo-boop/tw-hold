"""已知股票分割 / 面額變更的每股數字還原（reference.corporate_actions）。"""
from __future__ import annotations

import pandas as pd

from reference.corporate_actions import SPLITS, adjust_per_share


def test_分割日前除以factor_日後不動():
    df = pd.DataFrame({
        "ticker": ["5904"] * 4,
        "date": pd.to_datetime(["2026-07-20", "2026-07-21", "2026-07-22", "2026-08-01"]),
        "close": [610.0, 63.0, 64.0, 72.0],
    })
    out = adjust_per_share(df, ["close"])
    assert out["close"].tolist() == [61.0, 63.0, 64.0, 72.0]


def test_沒有已知分割的ticker原樣返回():
    df = pd.DataFrame({"ticker": ["2330", "2330"],
                       "date": pd.to_datetime(["2020-01-01", "2026-01-01"]),
                       "close": [300.0, 1000.0]})
    out = adjust_per_share(df, ["close"])
    pd.testing.assert_frame_equal(out, df)


def test_自訂日期欄_period_end():
    df = pd.DataFrame({
        "ticker": ["5904", "5904"],
        "period_end": pd.to_datetime(["2025-12-31", "2026-09-30"]),
        "eps": [30.0, 3.0],
    })
    out = adjust_per_share(df, ["eps"], date_col="period_end")
    assert out["eps"].tolist() == [3.0, 3.0]


def test_對照表格式():
    for tk, events in SPLITS.items():
        assert tk.isdigit()
        for e in events:
            assert pd.Timestamp(e["date"]) and e["factor"] > 1
