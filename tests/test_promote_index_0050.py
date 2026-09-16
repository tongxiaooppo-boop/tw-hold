"""scripts/promote_index_0050.py——「前一日資料錯誤不可原諒」，寧可保留舊檔案不覆寫，
也不要讓一份倒退／損毀的資料蓋掉本來正確的。

驗證條件本身的逐條測試在 `test_price_series_guard.py`（0050 跟 006201 共用同一套）；
這支只測**接線**：SKIP／REJECT 時舊檔一定不能被動到、通過時才寫進去。

⚠️ 假資料一律給足 `guard.MIN_ROWS` 筆——2026-09-16 起筆數不足（餵不動 MA200）
本身就是拒絕理由，兩三筆的假資料不再是「正常資料」。
"""
from __future__ import annotations

import pandas as pd
import pytest

from reference import price_series_guard as guard
from scripts import promote_index_0050 as m

N = guard.MIN_ROWS + 50


def _write(p, n=N, start="2015-01-01", last=None):
    dates = pd.bdate_range(start, periods=n)
    close = [100.0 * (1.001 ** i) for i in range(n)]
    if last is not None:
        close[-1] = last
    pd.DataFrame({"date": dates, "close": close}).to_parquet(p, index=False)
    return close[-1]


@pytest.fixture(autouse=True)
def _paths(monkeypatch, tmp_path):
    src, dest = tmp_path / "upstream.parquet", tmp_path / "reference.parquet"
    monkeypatch.setattr(m, "SRC", src)
    monkeypatch.setattr(m, "DEST", dest)
    return src, dest


def test_上游沒附這個檔就跳過_不動舊檔(_paths):
    src, dest = _paths
    keep = _write(dest)
    assert m.validate_and_promote() == 0
    assert pd.read_parquet(dest)["close"].iloc[-1] == keep   # 沒被清掉


def test_新檔是空的就拒絕(_paths):
    src, dest = _paths
    pd.DataFrame({"date": [], "close": []}).to_parquet(src, index=False)
    keep = _write(dest)
    assert m.validate_and_promote() == 1
    assert pd.read_parquet(dest)["close"].iloc[-1] == keep   # 保留舊檔


def test_新檔日期比舊檔倒退就拒絕(_paths):
    src, dest = _paths
    _write(src, n=N)
    keep = _write(dest, n=N + 10)                            # 舊檔多 10 天，更新
    assert m.validate_and_promote() == 1
    assert pd.read_parquet(dest)["close"].iloc[-1] == keep


def test_單日漲跌幅超標就拒絕(_paths):
    src, dest = _paths
    _write(src, n=N, last=100.0 * (1.001 ** (N - 2)) * 1.30)  # +30%
    keep = _write(dest, n=N - 1)
    assert m.validate_and_promote() == 1
    assert pd.read_parquet(dest)["close"].iloc[-1] == keep


def test_筆數縮水就拒絕(_paths):
    """欄位對、最後日期是最新的、最後一筆漲跌正常，只是歷史只剩一小段——
    這是舊版三道檢查唯一放行、且畫面會靜默壞掉（MA200 算不出來）的情況。"""
    src, dest = _paths
    full = pd.bdate_range("2015-01-01", periods=N + 100)
    pd.DataFrame({"date": full, "close": [100.0 * (1.001 ** i) for i in range(len(full))]}
                 ).to_parquet(dest, index=False)
    tail = full[-30:]
    pd.DataFrame({"date": tail, "close": [100.0] * 30}).to_parquet(src, index=False)
    assert m.validate_and_promote() == 1
    assert len(pd.read_parquet(dest)) == N + 100             # 舊檔完好


def test_正常資料就覆寫(_paths):
    src, dest = _paths
    last = _write(src, n=N)
    _write(dest, n=N - 1)
    assert m.validate_and_promote() == 0
    out = pd.read_parquet(dest)
    assert len(out) == N and out["close"].iloc[-1] == pytest.approx(last)


def test_首次寫入_沒有舊檔也能通過(_paths):
    src, dest = _paths
    last = _write(src, n=N)
    assert not dest.exists()
    assert m.validate_and_promote() == 0
    assert pd.read_parquet(dest)["close"].iloc[-1] == pytest.approx(last)
