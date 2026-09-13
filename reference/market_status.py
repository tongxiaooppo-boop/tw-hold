"""大盤多空狀態卡（「總經羅盤」用）——純顯示，跟 `regime.py` 完全獨立。

## 為什麼另開一支，不是改 `regime.py`

`regime.py` 的 bull/chop/bear 是**回測分層的既有量測基準**（`research/backtest_longswing.py`
拿它做分市況報表），改規則等於讓歷史報表全部要重跑、失去可比性——PRD §6.5 也把它定調成
「顯示旗標、不進公式」的既有物件，不該再疊加新語意上去。

這支模組是 2026-09-13 新談的另一個顯示需求：使用者想在畫面上**同時看到 MA60 版跟 MA200 版**
的多空判斷（不是分層用的三態綜合判斷），且要涵蓋上市（0050）與上櫃（006201）兩個市場。
兩者用途不同、门槛不同，硬塞進同一支模組只會讓两套語意互相污染，所以獨立成檔。

## 判斷規則（單一均線 + 乖離帶，不是 ADX）

沒有導入 ADX（原始設計稿 `market-regime.html` 的版本）——那需要額外算趨勢強度指標，
而這裡的功能定位是「一眼看盤中小工具」，不是分析頁。改用最簡單的「乖離帶」：

    乖離% = 收盤 / MA - 1
    乖離% >  BAND  → 多頭
    乖離% < -BAND  → 空頭
    其餘（貼線）    → 盤整

⚠️ **BAND 是憑感覺定的示意門檻**（±2%），不是回測調出來的，因為這支純顯示、不影響任何
清單或判斷，沒有「調门槛去讓某個判斷好看」的風險，但也因此**不能拿來當進出場依據**。
"""

from __future__ import annotations

import pandas as pd

BAND = 0.02  # 乖離帶：|close/MA - 1| 在這區間內視為盤整

LABELS = {"bull": "多頭", "bear": "空頭", "chop": "盤整"}


def ma_verdict(close: pd.Series, window: int, band: float = BAND) -> dict | None:
    """單一均線窗口（60 或 200）的多空判斷。

    `close` 需按日期由舊到新排序。資料不足 `window` 天回傳 `None`（暖機期不猜）。
    回傳 `{"state": "bull"/"bear"/"chop", "gap_pct": 乖離%, "ma": MA值, "close": 收盤}`。
    """
    s = close.astype("float64")
    if len(s) < window:
        return None
    ma = s.rolling(window, min_periods=window).mean()
    last_ma = ma.iloc[-1]
    if pd.isna(last_ma):
        return None
    last_close = s.iloc[-1]
    gap = last_close / last_ma - 1.0
    if gap > band:
        state = "bull"
    elif gap < -band:
        state = "bear"
    else:
        state = "chop"
    return {"state": state, "gap_pct": gap, "ma": last_ma, "close": last_close}


def market_card(close: pd.Series) -> dict:
    """一個市場的完整卡片資料：MA60 + MA200 兩個判斷，供畫面直接渲染。

    回傳 `{"ma60": ma_verdict結果或None, "ma200": ma_verdict結果或None}`。
    """
    s = close.sort_index() if isinstance(close.index, pd.DatetimeIndex) else close
    return {"ma60": ma_verdict(s, 60), "ma200": ma_verdict(s, 200)}


def latest_change(close: pd.Series) -> dict | None:
    """最新一筆收盤 + 對前一筆的漲跌（絕對值與 %）——卡片頭顯示現價用，
    跟 MA 判斷是兩件事：這個不看均線，純粹前一交易日比較。資料不足兩筆回 None。
    """
    s = close.dropna()
    if len(s) < 2:
        return None
    last, prev = s.iloc[-1], s.iloc[-2]
    return {"value": last, "chg": last - prev, "chg_pct": last / prev - 1.0}
