# 複製自 tw-swing @c310b60，2026-09-07；上游改動不自動同步。
# 用途：市況顯示旗標（PRD §6.5）。漂移後果無害（只是顯示）。
# 純函式，只依賴 numpy / pandas。
"""市況分期（多頭／震盪／空頭）。

## 為什麼需要這個維度

P2 的結論是「A3／C1 有超額、其餘沒有」，但那是**整段平均**。分層之後才看得到
價值來自哪一種盤（見 `docs/RULE_LEDGER.md`〈市況分層〉）：A3 的超額幾乎全部
來自震盪與空頭，多頭時幾乎為零——這正是 PRD §1.1.1「主動 sleeve」定位的
實證基礎。B2／B3 則在空頭為正、被多頭的虧損蓋掉。

## 分期規則（三條，全部用大盤代理 0050 的收盤序列）

| 市況 | 條件 |
| :--- | :--- |
| **多頭** `bull` | 站上 MA200 **且** 近 60 日報酬 > +5% |
| **空頭** `bear` | 跌破 MA200 **且**（近 60 日報酬 < −5% **或** 距波段高點回撤 < −10%） |
| **震盪** `chop` | 其餘 |

三個判準各自負責一件事，缺一不可：**MA200** 定方向，**60 日報酬** 排除
「在均線上下磨來磨去」的盤（只用 MA200 會把 2015 下半年那種鋸齒切成一堆
假多頭），**回撤** 抓 2020-03 那種「跌得又快又深、60 日報酬還沒轉負」的急殺。

⚠️ **這些門檻是人訂的，不是最佳化出來的**，也**沒有**對著績效調過——調它會
直接製造「挑一個讓 B2 空頭好看的切法」這種自我放水。要改門檻必須先有機制
理由，並且改完要重跑全部規則、不能只看被改的那條。

## 暖機期回 NA，不回「震盪」

前 200 日算不出 MA200。把「不知道」併進震盪會讓震盪那格混進一段實際上是
2015 年空頭的資料——分層診斷的價值就在每一格乾淨，所以寧可標成 NA 讓它
被排除，也不要猜。

## 這是 point-in-time 安全的

三個判準都只用到**當日與之前**的資料（rolling／pct_change／cummax 皆不前視）。
`regime_at()` 依訊號的進場日取當日市況，不會拿到未來資訊。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MA_WINDOW = 200
RET_WINDOW = 60
BULL_RET = 0.05
BEAR_RET = -0.05
BEAR_DD = -0.10

# 報告用的中文標籤。程式內部一律用 ASCII key（本機 shell 對中文輸出會 mojibake）。
LABELS = {"bull": "多頭", "chop": "震盪", "bear": "空頭"}
ORDER = ["bull", "chop", "bear"]


def classify(close: pd.Series) -> pd.Series:
    """把大盤收盤序列分成 bull / chop / bear，暖機不足處為 NA。

    參數是序列而非「自己去讀資料」，因為這樣才測得動，也才能在換掉大盤代理
    （見 `market.py` 檔頭）時完全不用改本模組。
    """
    s = close.astype("float64").sort_index()
    ma = s.rolling(MA_WINDOW, min_periods=MA_WINDOW).mean()
    ret = s.pct_change(RET_WINDOW)
    dd = s / s.cummax() - 1.0

    bull = (s > ma) & (ret > BULL_RET)
    bear = (s < ma) & ((ret < BEAR_RET) | (dd < BEAR_DD))

    out = pd.Series(np.where(bull, "bull", np.where(bear, "bear", "chop")),
                    index=s.index, dtype="object")
    out[ma.isna() | ret.isna()] = pd.NA
    return out


def regime_at(dates: pd.Series, close: pd.Series) -> pd.Series:
    """查每個日期當日的市況（`dates` 可以有重複，回傳與其等長、同 index）。

    大盤序列缺該日時取**最近一個已知的交易日**（searchsorted 往左找）——訊號日
    一定是交易日，會走到這裡通常代表大盤代理當天停牌或資料缺漏，用前一日的
    市況是唯一不前視的選擇。早於序列起點的日期回 NA，不是猜一個。
    """
    reg = classify(close)
    idx = pd.DatetimeIndex(reg.index)
    order = np.argsort(idx.values)
    idx, vals = idx[order], reg.to_numpy(dtype=object)[order]

    target = pd.DatetimeIndex(dates)
    pos = idx.searchsorted(target, side="right") - 1
    out = np.where(pos >= 0, vals[np.clip(pos, 0, None)], None)
    return pd.Series(out, index=dates.index, dtype="object")


def distribution(reg: pd.Series) -> dict[str, float]:
    """各市況佔比（分母不含暖機期的 NA）。"""
    valid = reg.dropna()
    return {k: float((valid == k).mean()) for k in ORDER}
