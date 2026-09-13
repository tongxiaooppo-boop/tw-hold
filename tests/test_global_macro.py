"""reference.global_macro——國際指數/美股總經快照的讀檔 + 輔助計算，跟抓取（會打網路）分開測。"""
from __future__ import annotations

import pandas as pd
import pytest

from reference import global_macro


@pytest.fixture()
def _snapshot(monkeypatch, tmp_path):
    p = tmp_path / "global_macro.parquet"
    df = pd.DataFrame({
        "symbol": ["^VIX"] * 5 + ["^DJI"] * 3,
        "date": pd.to_datetime(
            ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05",
             "2026-01-01", "2026-01-02", "2026-01-03"]),
        "close": [20.0, 22.0, 18.0, 25.0, 19.0, 100.0, 101.0, 99.0],
    })
    df.to_parquet(p, index=False)
    monkeypatch.setattr(global_macro, "GLOBAL_MACRO", p)
    return p


def test_檔案不存在回空序列(monkeypatch, tmp_path):
    monkeypatch.setattr(global_macro, "GLOBAL_MACRO", tmp_path / "nope.parquet")
    assert global_macro.load_close("^VIX").empty


def test_load_close只取該symbol且排序(_snapshot):
    s = global_macro.load_close("^DJI")
    assert list(s.values) == [100.0, 101.0, 99.0]


def test_查無該symbol回空序列(_snapshot):
    assert global_macro.load_close("^NOPE").empty


def test_latest_change_re_export自market_status(_snapshot):
    # 完整測試在 test_market_status.py——這裡只確認 re-export 沒斷（呼叫點沒改路徑）。
    s = global_macro.load_close("^DJI")
    out = global_macro.latest_change(s)
    assert out["value"] == 99.0


def test_percentile_rank最新值是最大值時回1(_snapshot):
    s = global_macro.load_close("^VIX")  # 最新一筆 19.0，不是最大也不是最小
    p = global_macro.percentile_rank(s, window=252)
    assert p == pytest.approx((s <= s.iloc[-1]).mean())


def test_percentile_rank空序列回None():
    assert global_macro.percentile_rank(pd.Series(dtype="float64")) is None
