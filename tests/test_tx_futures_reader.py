"""reference.tx_futures——台指期近月日盤/夜盤讀檔，跟抓取（會打網路）分開測。"""
from __future__ import annotations

import pandas as pd
import pytest

from reference import tx_futures


@pytest.fixture()
def _snapshot(monkeypatch, tmp_path):
    p = tmp_path / "tx_futures.parquet"
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-09-11", "2026-09-11", "2026-09-14", "2026-09-14"]),
        "session": ["day", "night", "day", "night"],
        "contract_month": ["202609"] * 4,
        "last": [45500.0, 45700.0, 45780.0, 46588.0],
        "settlement": [45500.0, None, 45777.0, None],
    })
    df.to_parquet(p, index=False)
    monkeypatch.setattr(tx_futures, "TX_FUTURES", p)
    return p


def test_檔案不存在回空序列(monkeypatch, tmp_path):
    monkeypatch.setattr(tx_futures, "TX_FUTURES", tmp_path / "nope.parquet")
    assert tx_futures.load_session("day").empty


def test_只取該session且依日期排序(_snapshot):
    s = tx_futures.load_session("night")
    assert list(s.index) == [pd.Timestamp("2026-09-11"), pd.Timestamp("2026-09-14")]
    assert list(s.values) == [45700.0, 46588.0]


def test_day與night互不干擾(_snapshot):
    assert tx_futures.load_session("day").iloc[-1] == 45780.0
    assert tx_futures.load_session("night").iloc[-1] == 46588.0
