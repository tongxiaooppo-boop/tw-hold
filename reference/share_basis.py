"""股數基準（估值 2.0，upgrade_guide §4-2）：事件倍數、面額推回、現金減資剔除區間。

【框架由 Opus 定，實作者不得改介面】函式本體由 P1 實作。

事件來源一律 `reference.corporate_actions.SPLITS`（{裸代號: [ {date, type, m, pf, src} ]}），
type ∈ {ex_both, ex_rights, cap_reduction, par_change, split}。m＝股數倍數（1 股變 m 股），
m=None 表示無法換算股數（cap_reduction 多為現金減資）。
SPLITS 載入失敗時 corporate_actions 會設 EVENTS_OK=False；這裡遇到 EVENTS_OK=False 一律 raise
EventsUnavailable（T-17：不得靜默當成「沒有事件」）。
"""
from __future__ import annotations

import pandas as pd


class EventsUnavailable(RuntimeError):
    """事件表讀不到；依賴股數事件的估值要停用，不可當成無事件。"""


def events(ticker: str) -> list[dict]:
    """該檔全部事件（date 轉 Timestamp），依日期排序；裸代號比對（"2330.TW" → "2330"）。"""
    raise NotImplementedError


def share_factor_after(ticker: str, t: pd.Timestamp) -> float:
    """t 之後（事件日 > t，不含 t）所有 m 有限且 >0 的事件 m 之乘積；無事件 = 1.0。
    用途：price_adj(t) = 原始收盤(t) ÷ share_factor_after(t)，把歷史價換到今天的股數基準（不做股利還原）。"""
    raise NotImplementedError


def par_value_at(ticker: str, t: pd.Timestamp, today_par: float | None) -> float | None:
    """t 當時面額 = today_par × Π(事件日 > t 的 par_change 事件 m)；today_par 為 None → None。"""
    raise NotImplementedError


def excluded_months(ticker: str) -> set[pd.Period]:
    """現金減資等無法換算的區間（月）。對每筆 type=="cap_reduction" 且 m 為 None 的事件 e：
    Q＝第一個 period_end ≥ e.date 的曆季季末；V＝report_deadline(Q)；
    剔除月份＝[e.date 所在月, V 所在月的前一個月]（V 當月月底財報已可見，不剔除）。
    回傳 pd.Period("M") 的集合。"""
    raise NotImplementedError
