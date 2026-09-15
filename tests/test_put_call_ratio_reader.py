"""reference.put_call_ratio——讀檔，跟抓取（會打網路）分開測。"""
from __future__ import annotations

import pandas as pd
import pytest

from reference import put_call_ratio


@pytest.fixture()
def _snapshot(monkeypatch, tmp_path):
    p = tmp_path / "put_call_ratio.parquet"
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-09-11", "2026-09-14"]),
        "put_call_volume_ratio": [91.56, 107.09],
        "put_call_oi_ratio": [87.70, 88.04],
    })
    df.to_parquet(p, index=False)
    monkeypatch.setattr(put_call_ratio, "PUT_CALL_RATIO", p)
    return p


def test_檔案不存在回空序列(monkeypatch, tmp_path):
    monkeypatch.setattr(put_call_ratio, "PUT_CALL_RATIO", tmp_path / "nope.parquet")
    assert put_call_ratio.load_series("put_call_volume_ratio").empty


def test_load_series依日期排序(_snapshot):
    s = put_call_ratio.load_series("put_call_volume_ratio")
    assert list(s.index) == [pd.Timestamp("2026-09-11"), pd.Timestamp("2026-09-14")]
    assert list(s.values) == [91.56, 107.09]


def test_兩個field互不干擾(_snapshot):
    assert put_call_ratio.load_series("put_call_oi_ratio").iloc[-1] == 88.04
