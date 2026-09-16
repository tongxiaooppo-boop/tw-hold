"""scripts/promote_index_0050.py 的三道驗證——「前一日資料錯誤不可原諒」，
寧可保留舊檔案不覆寫，也不要讓一份倒退／損毀的資料蓋掉本來正確的。"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts import promote_index_0050 as m


def _write(p, dates, closes):
    pd.DataFrame({"date": pd.to_datetime(dates), "close": closes}).to_parquet(p, index=False)


@pytest.fixture(autouse=True)
def _paths(monkeypatch, tmp_path):
    src, dest = tmp_path / "upstream.parquet", tmp_path / "reference.parquet"
    monkeypatch.setattr(m, "SRC", src)
    monkeypatch.setattr(m, "DEST", dest)
    return src, dest


def test_上游沒附這個檔就跳過_不動舊檔(_paths):
    src, dest = _paths
    _write(dest, ["2026-01-01"], [100.0])
    assert m.validate_and_promote() == 0
    assert pd.read_parquet(dest)["close"].iloc[-1] == 100.0  # 沒被清掉


def test_新檔是空的就拒絕(_paths, tmp_path):
    src, dest = _paths
    pd.DataFrame({"date": [], "close": []}).to_parquet(src, index=False)
    _write(dest, ["2026-01-01"], [100.0])
    assert m.validate_and_promote() == 1
    assert pd.read_parquet(dest)["close"].iloc[-1] == 100.0  # 保留舊檔


def test_新檔日期比舊檔倒退就拒絕(_paths):
    src, dest = _paths
    _write(src, ["2026-01-01", "2026-01-02"], [100.0, 101.0])
    _write(dest, ["2026-01-05"], [110.0])
    assert m.validate_and_promote() == 1
    assert pd.read_parquet(dest)["close"].iloc[-1] == 110.0  # 保留舊檔，沒被倒退的新資料蓋掉


def test_單日漲跌幅超過門檻就拒絕(_paths):
    src, dest = _paths
    _write(src, ["2026-01-01", "2026-01-02"], [100.0, 130.0])  # +30%，超過 15% 門檻
    _write(dest, ["2025-12-31"], [99.0])
    assert m.validate_and_promote() == 1
    assert pd.read_parquet(dest)["close"].iloc[-1] == 99.0


def test_正常資料就覆寫(_paths):
    src, dest = _paths
    _write(src, ["2026-01-01", "2026-01-02"], [100.0, 101.0])
    _write(dest, ["2025-12-31"], [99.0])
    assert m.validate_and_promote() == 0
    out = pd.read_parquet(dest)
    assert len(out) == 2 and out["close"].iloc[-1] == 101.0


def test_舊檔不存在_第一次寫入直接通過(_paths):
    src, dest = _paths
    _write(src, ["2026-01-01", "2026-01-02"], [100.0, 101.0])
    assert not dest.exists()
    assert m.validate_and_promote() == 0
    assert pd.read_parquet(dest)["close"].iloc[-1] == 101.0
