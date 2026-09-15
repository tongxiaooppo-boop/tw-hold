"""scripts.fetch_put_call_ratio 的純邏輯部分（欄位轉換 + 去重合併），不打網路。"""
from __future__ import annotations

import json

import pandas as pd

from scripts.fetch_put_call_ratio import fetch


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch轉成內部欄名且依日期排序(monkeypatch):
    payload = [
        {"Date": "20260914", "PutVolume": "150180", "CallVolume": "140242",
         "PutCallVolumeRatio%": "107.09", "PutOI": "70687", "CallOI": "80290",
         "PutCallOIRatio%": "88.04"},
        {"Date": "20260911", "PutVolume": "335358", "CallVolume": "366279",
         "PutCallVolumeRatio%": "91.56", "PutOI": "52641", "CallOI": "60025",
         "PutCallOIRatio%": "87.70"},
    ]
    monkeypatch.setattr("scripts.fetch_put_call_ratio.urllib.request.urlopen",
                         lambda *a, **k: _FakeResp(payload))
    df = fetch()
    assert list(df["date"]) == [pd.Timestamp("2026-09-11"), pd.Timestamp("2026-09-14")]
    assert df.iloc[-1]["put_call_volume_ratio"] == 107.09
    assert df.iloc[-1]["put_call_oi_ratio"] == 88.04


def test_main合併時同日期以新資料為準(monkeypatch, tmp_path):
    import scripts.fetch_put_call_ratio as mod

    out = tmp_path / "put_call_ratio.parquet"
    monkeypatch.setattr(mod, "OUT", out)

    old = pd.DataFrame([{"date": pd.Timestamp("2026-09-14"), "put_volume": 1.0,
                          "call_volume": 1.0, "put_call_volume_ratio": 50.0,
                          "put_oi": 1.0, "call_oi": 1.0, "put_call_oi_ratio": 50.0}])
    old.to_parquet(out, index=False)

    payload = [{"Date": "20260914", "PutVolume": "150180", "CallVolume": "140242",
                "PutCallVolumeRatio%": "107.09", "PutOI": "70687", "CallOI": "80290",
                "PutCallOIRatio%": "88.04"}]
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **k: _FakeResp(payload))

    mod.main()
    result = pd.read_parquet(out)
    assert len(result) == 1
    assert result.iloc[0]["put_call_volume_ratio"] == 107.09  # 新資料蓋掉舊的 50.0
