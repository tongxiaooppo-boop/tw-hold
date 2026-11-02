"""估值卡輸入組裝（估值 2.0 P4，規格 docs/val2/P4_spec.md §2）。

【框架由 Opus 定（2026-11-02），實作者不得改介面】app 個股頁與 scripts/val2_dryrun_cards.py **共用這一支**，
不准另寫第二套組法（避免畫面與乾跑卡片不同）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DERIVED = Path(__file__).resolve().parent.parent / "data" / "derived"
MH_FILE = "multiples_hist.parquet"
REV_FILE = "eps_revision.parquet"
IND_FILE = "industry_pe.json"


def quarterly(inc: pd.DataFrame, bal: pd.DataFrame, cf: pd.DataFrame) -> pd.DataFrame:
    """單檔三表 → build_card 的 qf：loader.merge_statements(inc, bal, cf)（how 預設 outer，與 load_quarterly 相同）
    → disclosure_date＝period_end＋1 天（live）→ corporate_actions.adjust_eps。不用 factors.quarterly_factors。
    三表任一空 → 照 merge_statements 的行為（inc 空回空表）。"""
    raise NotImplementedError


def load_mh(code: str, derived: Path = DERIVED) -> pd.DataFrame:
    """multiples_hist.parquet 中該檔的列（pyarrow filters 篩 ticker，不整檔讀進記憶體）；檔不存在或沒有該檔 → 空 DataFrame
    （欄位＝multiples_self.HIST_COLUMNS）。"""
    raise NotImplementedError


def load_rev_hist(code: str, derived: Path = DERIVED) -> pd.DataFrame:
    """eps_revision.parquet 中該檔的列；同 load_mh 規則（欄：ticker, month, window, eps_fwd, n_est_q, event）。"""
    raise NotImplementedError


def load_industry_pe(derived: Path = DERIVED) -> dict | None:
    """industry_pe.json 的 "industries"；檔不存在 → None。"""
    raise NotImplementedError


def card_inputs(code: str, asof: pd.Timestamp, cls: dict | None, derived: Path = DERIVED,
                bundle=None) -> dict:
    """回傳 build_card 的關鍵字參數 {qf, rev, px, cls, mh, rev_hist, industry_pe, asof}；
    derived 下三個倍數檔任一不存在 → {"missing": val_view.MSG_NO_MULTIPLES}。
    bundle＝提供 income／balance／cashflow／revenue／prices_raw_close 單檔讀取的物件（app 傳 bundle_data 模組；
    乾跑傳讀 data/upstream 的轉接物件），介面：bundle.read(name: str, code: str) -> pd.DataFrame。
    None → 用 app/bundle_data。px＝prices_raw_close 的 date／close，只留 date ≤ asof。
    cls 由呼叫端給（app 讀 stock_class.json），None 照傳（build_card 自己給 D）。"""
    raise NotImplementedError
