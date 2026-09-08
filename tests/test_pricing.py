"""M2 §6.2/§6.3：買價 + verdict 單元測試（合成資料，不碰真 bundle）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from screener.pricing import add_value_verdict, pe_percentiles, price_levels

ASOF = pd.Timestamp("2026-09-07")


def _per_hist(ticker: str, per: float, n: int = 400) -> pd.DataFrame:
    dates = pd.date_range(ASOF - pd.Timedelta(days=n), ASOF, freq="D")
    return pd.DataFrame({"ticker": ticker, "date": dates, "per": per})


def _price_hist(ticker: str, close: float, n: int = 200) -> pd.DataFrame:
    dates = pd.date_range(ASOF - pd.Timedelta(days=n), ASOF, freq="D")
    return pd.DataFrame({"ticker": ticker, "date": dates, "close": close})


def _val_row(**kw) -> pd.DataFrame:
    base = dict(ticker="1001", close=100.0, normalized_eps=8.0, ttm_eps=8.0,
                passes=True, reject_reason=np.nan)
    base.update(kw)
    return pd.DataFrame([base])


def test_pe_percentiles_p30_小於_p70_且小樣本回_nan():
    hist = pd.concat([_per_hist("1001", 15.0), _per_hist("1002", 20.0, n=10)])
    out = pe_percentiles(hist, ASOF).set_index("ticker")
    assert out.loc["1001", "pe_p30"] <= out.loc["1001", "pe_p70"]
    assert np.isnan(out.loc["1002", "pe_p30"])          # 樣本 < 60 交易日


def test_price_levels_季線與20週低():
    hist = _price_hist("1001", 50.0)
    lv = price_levels(hist, ASOF).set_index("ticker")
    assert lv.loc["1001", "ma_quarter"] == 50.0
    assert lv.loc["1001", "low_20w"] == 50.0


def test_verdict_便宜且支撐在下_給推薦與買區間():
    val = _val_row(close=100.0, normalized_eps=10.0)   # implied PE 10
    per = _per_hist("1001", 15.0)                       # P30≈P70≈15 → 便宜門檻≈150
    px = _price_hist("1001", 90.0)                      # 季線/20週低 = 90 < 現價
    out = add_value_verdict(val, per, px, asof=ASOF).iloc[0]
    assert out["verdict"] == "推薦"
    assert out["buy_low"] == 90.0 and out["buy_high"] == 100.0
    assert out["buy_note"] is None


def test_verdict_現價高於便宜門檻_觀望():
    val = _val_row(close=200.0, normalized_eps=10.0)
    per = _per_hist("1001", 15.0)                       # 便宜門檻≈150 < 200
    out = add_value_verdict(val, per, _price_hist("1001", 180.0), asof=ASOF).iloc[0]
    assert out["verdict"] == "觀望（無安全邊際）"
    assert pd.isna(out["buy_low"])


def test_買區間倒置_不吐負寬度改標支撐位():
    val = _val_row(close=100.0, normalized_eps=10.0)
    per = _per_hist("1001", 15.0)                       # 便宜門檻≈150、上界=min(150,100)=100
    px = _price_hist("1001", 130.0)                     # 季線=130 > 上界 100 → 倒置
    out = add_value_verdict(val, per, px, asof=ASOF).iloc[0]
    assert out["verdict"] == "推薦"
    assert pd.isna(out["buy_low"]) and "支撐位" in out["buy_note"]


def test_eps_基準存疑_擋下():
    # normalized_eps 灌到隱含 PE 只有市場 PE 的 1/4 → 存疑
    val = _val_row(close=100.0, normalized_eps=25.0)    # implied PE 4
    per = _per_hist("1001", 20.0)                       # 市場 PE 20
    out = add_value_verdict(val, per, _price_hist("1001", 95.0), asof=ASOF).iloc[0]
    assert out["eps_basis_suspect"]
    assert out["verdict"] == "資料不足（EPS 基準存疑）"


def test_循環高峰旗標():
    val = _val_row(close=100.0, normalized_eps=5.0, ttm_eps=10.0)   # 比值 2.0 > 1.5
    per = _per_hist("1001", 15.0)
    out = add_value_verdict(val, per, _price_hist("1001", 90.0), asof=ASOF).iloc[0]
    assert bool(out["cyclical_peak_flag"]) is True


def test_無股價_退化為資料不足():
    val = pd.DataFrame([dict(ticker="1001", passes=True, reject_reason=np.nan)])
    out = add_value_verdict(val, None, None, asof=ASOF).iloc[0]
    assert out["verdict"] == "資料不足（無股價）"
    assert pd.isna(out["cheap_threshold"])
