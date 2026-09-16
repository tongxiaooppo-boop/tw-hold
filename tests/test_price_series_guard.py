"""reference/price_series_guard.py——0050／006201 落地前的共用守門。

「前一日的資料錯誤不可原諒」：寧可保留舊檔案不覆寫，也不要讓一份縮水／倒退／
被改寫過的資料蓋掉本來正確的。但 **sanitize 得動的東西不能拿來拒絕**——FinMind
每次全量重抓都會再吐一次同樣的 close=0，設計成「看到就拒絕」會讓資料凍死。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from reference import price_series_guard as g


def _series(n: int, start: float = 100.0, last: float | None = None) -> pd.DataFrame:
    """n 筆平穩序列（每日 +0.1%），可指定最後一筆收盤。"""
    dates = pd.bdate_range("2015-01-01", periods=n)
    close = [start * (1.001 ** i) for i in range(n)]
    if last is not None:
        close[-1] = last
    return pd.DataFrame({"date": dates, "close": close})


# ---- sanitize：清得掉的不要拒絕 ----------------------------------------------

def test_收盤0與NaN被清掉_不是拒絕理由():
    """實測：index_006201.parquet 裡 2016-08-24／2017-04-10 就是 close=0。"""
    df = _series(300)
    df.loc[100, "close"] = 0.0
    df.loc[150, "close"] = np.nan
    out = g.sanitize(df)
    assert len(out) == 298
    assert (out["close"] > 0).all()
    assert g.validate(out, None) == []


def test_同一天重複的列只留後寫的():
    df = _series(300)
    dup = pd.DataFrame({"date": [df["date"].iloc[-1]], "close": [df["close"].iloc[-1] * 1.001]})
    out = g.sanitize(pd.concat([df, dup], ignore_index=True))
    assert len(out) == 300
    assert out["close"].iloc[-1] == dup["close"].iloc[0]


def test_空表或缺欄回None():
    assert g.sanitize(pd.DataFrame({"date": [], "close": []})) is None
    assert g.sanitize(pd.DataFrame({"date": [1], "px": [2]})) is None
    assert g.sanitize(None) is None


# ---- validate：這些才該拒絕 ---------------------------------------------------

def test_新資料是空的就拒絕():
    assert g.validate(None, _series(300)) != []


def test_筆數縮水就拒絕_這是舊版三道檢查全部放行的那個洞():
    """上游只回最近 30 列：欄位對、最後日期是今天、最後一筆漲跌正常——
    舊版檢查全過，覆寫後 MA200 靜默算不出來，freshness_check 也抓不到。"""
    old = g.sanitize(_series(2848))
    new = g.sanitize(_series(2848).tail(30).reset_index(drop=True))
    reasons = g.validate(new, old)
    assert any("縮" in r for r in reasons)


def test_筆數不足餵不動MA200就拒絕():
    assert any("MA200" in r for r in g.validate(g.sanitize(_series(100)), None))


def test_上游修掉幾筆爛資料不算縮水():
    old = g.sanitize(_series(1000))
    new = g.sanitize(_series(1000).drop(index=[10, 20, 30]).reset_index(drop=True))
    assert g.validate(new, old) == []


def test_最後日期倒退就拒絕():
    old = g.sanitize(_series(1000))
    new = g.sanitize(_series(995))
    assert any("還舊" in r for r in g.validate(new, old))


def test_單日漲跌幅超過門檻就拒絕():
    old = g.sanitize(_series(999))
    new = g.sanitize(_series(1000, last=_series(1000)["close"].iloc[-2] * 1.3))
    assert any("漲跌幅" in r for r in g.validate(new, old))


def test_漲跌停附近仍放行_實測0050最大單日就是10pct():
    old = g.sanitize(_series(999))
    base = _series(1000)
    new = g.sanitize(_series(1000, last=base["close"].iloc[-2] * 0.90))
    assert g.validate(new, old) == []


# ---- 歷史被回填／改寫：比報酬，不比價格 ----------------------------------------

def test_歷史被改寫就拒絕():
    old = g.sanitize(_series(1000))
    tampered = _series(1000)
    tampered.loc[980, "close"] *= 1.05          # 動一天 → 前後兩天的報酬都變
    assert any("回填" in r for r in g.validate(g.sanitize(tampered), old))


def test_合法的還原基準變更不拒絕():
    """除息／分割後上游把事件日之前整段乘上常數：價格全變，但日報酬只有事件日
    當天那一筆會變——所以容許 1 天不一致。"""
    old = g.sanitize(_series(1000))
    rebased = _series(1000)
    rebased.loc[:970, "close"] *= 0.985         # 事件日之前整段重訂基準
    assert g.validate(g.sanitize(rebased), old) == []


def test_沒有舊檔就只驗新檔自己():
    assert g.validate(g.sanitize(_series(300)), None) == []
