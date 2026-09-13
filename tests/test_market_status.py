"""大盤多空狀態卡（reference.market_status）——跟 regime.py 無關，純顯示。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from reference.market_status import BAND, latest_change, ma_verdict, market_card


def _flat_then_rise(days: int, rise_pct: float) -> pd.Series:
    """暖機到 `days` 天打平，最後一天漲 `rise_pct`——讓最新收盤明確偏離 MA。"""
    vals = [100.0] * days
    vals[-1] = 100.0 * (1 + rise_pct)
    return pd.Series(vals)


def test_資料不足window天回None():
    assert ma_verdict(pd.Series([100.0] * 59), window=60) is None


def test_乖離超過正band判多頭():
    s = _flat_then_rise(60, BAND + 0.03)
    out = ma_verdict(s, window=60)
    assert out["state"] == "bull"
    assert out["gap_pct"] > BAND


def test_乖離低於負band判空頭():
    s = _flat_then_rise(60, -(BAND + 0.03))
    out = ma_verdict(s, window=60)
    assert out["state"] == "bear"
    assert out["gap_pct"] < -BAND


def test_乖離在band內判盤整():
    s = _flat_then_rise(60, BAND / 2)
    out = ma_verdict(s, window=60)
    assert out["state"] == "chop"


def test_market_card回傳ma60與ma200():
    idx = pd.date_range("2024-01-01", periods=250, freq="B")
    s = pd.Series(np.linspace(100, 130, 250), index=idx)
    card = market_card(s)
    assert card["ma60"]["state"] in ("bull", "bear", "chop")
    assert card["ma200"]["state"] in ("bull", "bear", "chop")


def test_market_card資料不足200天_ma200為None():
    idx = pd.date_range("2024-01-01", periods=100, freq="B")
    s = pd.Series(np.linspace(100, 110, 100), index=idx)
    card = market_card(s)
    assert card["ma60"] is not None
    assert card["ma200"] is None


def test_latest_change算對絕對值與百分比():
    out = latest_change(pd.Series([100.0, 103.0]))
    assert out["value"] == 103.0
    assert out["chg"] == 3.0
    assert out["chg_pct"] == pytest.approx(0.03)


def test_latest_change資料不足兩筆回None():
    assert latest_change(pd.Series([1.0])) is None
