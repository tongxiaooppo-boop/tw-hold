"""自建歷史倍數（估值 2.0，upgrade_guide §4）：PE、前瞻 PE、PB 月度序列與有效月數。

【框架由 Opus 定，實作者不得改介面、常數、欄位】函式本體由 P2 實作。
每個月底 t：price_adj = 原始收盤 ÷ share_basis.share_factor_after(t)（不做股利還原）；
EPS 用 eps_windows.ttm_window／fwd_window(asof=t, live=False)；bvps＝最近可見季歸母權益 ÷ 該季隱含股數
（換到最新基準）。T-4／T-5：窗口以估值日錨定、先取完整月份月底觀測再判有效，當月未結束不算。
"""
from __future__ import annotations

import pandas as pd

MULT_MAX_PE = 100.0
EPS_MIN = 0.05
VALID_MIN = {"normal": 36, "growth": 30, "pb": 60}
VALID_EXIT = {"normal": 33, "growth": 27, "pb": 54}
WINDOW_MONTHS = {"normal": 60, "cyclical": 60, "growth": 36, "pb": None}   # None＝全部歷史
MULT_CAP = {"normal": 30.0, "normal_exc": 50.0, "growth": 50.0, "pb": None}
PCTS = (0.20, 0.50, 0.80)

HIST_COLUMNS = ("ticker", "month", "date", "price_adj", "eps_ttm", "eps_fwd", "bvps",
                "n_est_ttm", "n_est_fwd", "pe", "pe_fwd", "pb",
                "valid_pe", "valid_pe_fwd", "valid_pb", "excluded", "pe_exchange")


def monthly_closes(raw_close: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """日線原始收盤（ticker, date, close）→ 每個完整月份最後一個交易日（ticker, month, date, close）。
    asof 所在月未結束 → 不含該月。"""
    raise NotImplementedError


def build_history(ticker: str, q: pd.DataFrame, monthly_rev: pd.Series, closes: pd.DataFrame,
                  per: pd.DataFrame | None, financial: bool = False) -> pd.DataFrame:
    """單檔月度倍數序列，欄位＝HIST_COLUMNS。closes＝該檔 monthly_closes 結果；per＝交易所 PER（核對用）。"""
    raise NotImplementedError


def window_stats(mh: pd.DataFrame, kind: str, metric: str, asof: pd.Timestamp,
                 cap: float | None) -> dict:
    """倍數窗統計。kind ∈ WINDOW_MONTHS；metric ∈ {"pe","pe_fwd","pb"}。
    回傳 {start, end, n_valid, n_loss, mults:(p20,p50,p80) 截斷後, raw_mults:(…) 未截斷, capped: bool}。"""
    raise NotImplementedError


def is_valid_tier_a(n_valid: int, kind: str, was_a: bool) -> bool:
    """A 層門檻含緩衝：was_a 時 ≥ VALID_EXIT[kind]，否則 ≥ VALID_MIN[kind]。"""
    raise NotImplementedError
