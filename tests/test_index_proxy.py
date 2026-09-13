"""reference.index_proxy——讀 `scripts/fetch_index_proxy.py` 產出的 006201 快照。"""
from __future__ import annotations

import pandas as pd

from reference import index_proxy


def test_檔案不存在回空序列(monkeypatch, tmp_path):
    monkeypatch.setattr(index_proxy, "INDEX_006201", tmp_path / "nope.parquet")
    out = index_proxy.load_006201()
    assert out.empty


def test_讀到的序列由舊到新排序(monkeypatch, tmp_path):
    p = tmp_path / "index_006201.parquet"
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-03", "2026-01-02", "2026-01-01"]),
        "close": [12.0, 11.0, 10.0],
    })
    df.to_parquet(p, index=False)
    monkeypatch.setattr(index_proxy, "INDEX_006201", p)
    out = index_proxy.load_006201()
    assert out.index.is_monotonic_increasing
    assert out.iloc[0] == 10.0 and out.iloc[-1] == 12.0
