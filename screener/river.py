"""本益比／股價淨值比河流圖資料（估值 2.0 P4，upgrade_guide §15-4，規格 docs/val2/P4_spec.md §4）。

【框架由 Opus 定（2026-11-02），實作者不得改介面、常數】純函式，不讀檔（share_basis 事件表例外）。
- 股價：原始收盤 ÷ share_basis.share_factor_after(ticker, t)（只做股數調整、不含息；向量化結果須與逐日呼叫相同）。
- PE 路線 EPS：每個月底 t 的 eps_windows.reported_window(q, t, live=False).eps（當時可見的已公布 4 季，不用試算、
  不反推），日線向前填；不 ok → NaN。PB 路線：mh 的 bvps 月底值向前填。
- 河道倍數＝card["prices"]["mults"]（與估值卡同一組，截斷後）。
"""
from __future__ import annotations

import pandas as pd

LEGEND_PE = "已公布 4 季 EPS × 歷史 20%／50%／80% 本益比"
LEGEND_PB = "每股淨值 × 歷史 20%／50%／80% 股價淨值比"
NOTE_BASE_DIFF = "估值卡三價用{base_name}，河道用已公布 4 季 EPS，兩者可能不同"
NO_MULT = "沒有估值倍數"


def river_frame(q: pd.DataFrame, px_raw: pd.DataFrame, mh: pd.DataFrame | None, card: dict,
                ticker: str, asof: pd.Timestamp) -> dict:
    """回傳 {
        "ok": bool（有股價就 True）, "metric": "pe"|"pb", "frame": DataFrame[date, price, base, p20, p50, p80]
        （base＝EPS 或每股淨值；沒河道時 p20/p50/p80 全 NaN）, "mults": tuple|None, "legend": str,
        "reason": str|None（沒河道的原因：card["price_note"] 或 NO_MULT）, "note": str|None（NOTE_BASE_DIFF）}
    metric：card["route"]=="PB" → "pb"，其餘 "pe"。px_raw＝date／close，只用 date ≤ asof。
    card["prices"] 為 None 或 mults 任一 None → 不畫河道。
    note：metric pe 且有河道時給 NOTE_BASE_DIFF.format(base_name=prices.base_name)；**例外**：base_name=="近 4 季 EPS"
    且 card["eps"]["ttm"]["n_est"]==0（兩者同口徑）→ None。PB → None。"""
    raise NotImplementedError
