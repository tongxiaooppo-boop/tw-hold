"""把 bundle 的四張整併表組成「季度財報面板」與「股利表」。

## 來源

M0.3 從 `tw-swing/src/twswing/value/loader.py` 搬走（tw-swing 端已刪除；2026-09-07
opus 審核改判「一起搬走」——搬完 factors/screen/build_factors/test_value 之後
loader 在 tw-swing 零消費者、零測試覆蓋）。與 tw-swing 唯一差異：不再
`from twswing.data import store`，改讀 tw-hold 拉下來的上游 bundle。

bundle 目錄由 `TWHOLD_BUNDLE_DIR` 環境變數指定，預設 `<repo>/data/upstream`
（`fetch_bundle.py` 會把 tw-swing Release 的資產解到這裡；PRD §3.2）。

## 公告日安全邊界

`income`／`balance`／`cashflow` 的 `period_end` 是**期別結束日不是公告日**。
台灣季報法定期限約季末 +45 天（Q4 是次年 3/31，更晚，但用 45 天保守估）。
因此每一季掛一個 `disclosure_date = period_end + 45 天`——任何「某天看得到
哪一期財報」的判斷都用這個，不用 `period_end`。
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: 上游 bundle 根目錄。`fetch_bundle.py` 解壓到這裡；不進版控（`.gitignore`）。
BUNDLE_DIR = Path(os.environ.get("TWHOLD_BUNDLE_DIR", _REPO_ROOT / "data" / "upstream"))
FUND_DIR = BUNDLE_DIR / "fundamentals"

#: 季報公告落後（季末 → 看得到）。保守：法定 Q1-Q3 是季末 +45 天，Q4 更長，
#: 一律用 45 天不夠保守的季末（Q4）就晚一點才納入，寧可晚不可早。
STATEMENT_LAG_DAYS = 45


def _read(name: str) -> pd.DataFrame:
    p = FUND_DIR / f"{name}.parquet"
    if not p.exists():
        raise FileNotFoundError(
            f"{p} 不存在——先跑 `python fetch_bundle.py` 拉上游 bundle，"
            f"或設 TWHOLD_BUNDLE_DIR 指向 bundle 目錄")
    return pd.read_parquet(p)


def merge_statements(inc: pd.DataFrame, bal: pd.DataFrame, cf: pd.DataFrame,
                     how: str = "outer") -> pd.DataFrame:
    """三表去重合併；歸母淨利與業主權益分開，權益只取資產負債表。"""
    keys = ["ticker", "period_end"]

    def prep(frame):
        out = frame.copy() if len(frame.columns) else pd.DataFrame(columns=keys)
        out["period_end"] = pd.to_datetime(out["period_end"])
        return out.drop_duplicates(keys, keep="last")

    inc, bal, cf = map(prep, (inc, bal, cf))
    # 維持既有面板欄序：淨利另置末欄，權益保留原欄位位置。
    order = list(inc.columns)
    inc = inc.rename(columns={"equity_parent": "ni_parent"})
    if "ni_parent" not in inc.columns:
        inc["ni_parent"] = np.nan
    equity = bal["equity_parent"] if "equity_parent" in bal.columns else pd.Series(np.nan, index=bal.index)
    bal["equity_parent"] = equity.fillna(bal["equity"] if "equity" in bal.columns else np.nan)
    q = inc.merge(bal, on=keys, how=how, suffixes=("", "_b"), validate="one_to_one")
    q = q.merge(cf, on=keys, how=how, suffixes=("", "_c"), validate="one_to_one")
    q = q.drop(columns=[c for c in q.columns if c.endswith(("_b", "_c"))])
    order = [c for c in order if c in q.columns and c != "ni_parent"]
    order += [c for c in q.columns if c not in order and c != "ni_parent"] + ["ni_parent"]
    return q[order].sort_values(keys).reset_index(drop=True)


def load_quarterly() -> pd.DataFrame:
    """三表合併成季度面板，依 (ticker, period_end) 排序並加公告日。"""
    q = merge_statements(_read("income"), _read("balance"), _read("cashflow"))
    q["disclosure_date"] = q["period_end"] + pd.Timedelta(days=STATEMENT_LAG_DAYS)
    return q


def load_dividends() -> pd.DataFrame:
    """股利政策表：`[ticker, year, pay_date, cash_earnings, cash_surplus, stock_earnings,
    announce_date, ex_date, ...]`，依 (ticker, year) 排序。

    同一 `year` 可能有多列（季配息、補充決議）——加總成一年一列。
    """
    d = _read("dividend").rename(columns={
        "CashEarningsDistribution": "cash_earnings",
        "CashStatutorySurplus": "cash_surplus",
        "StockEarningsDistribution": "stock_earnings",
        "AnnouncementDate": "announce_date",
        "CashExDividendTradingDate": "ex_date",
        "CashDividendPaymentDate": "pay_settle_date",
    })
    d = d[d["year"].notna()].copy()
    d["year"] = d["year"].astype("int64")
    # 配股／分割前的每股現金股利 ÷ m 搬到最新股本基準（逐筆、加總前做：同一年可能跨事件）
    from reference.corporate_actions import adjust_dividends
    d = adjust_dividends(d, ["cash_earnings", "cash_surplus"])
    agg = {"cash_earnings": "sum", "stock_earnings": "sum",
           "pay_date": "max", "announce_date": "max", "ex_date": "max"}
    if "cash_surplus" in d.columns:
        agg["cash_surplus"] = "sum"
    out = (d.groupby(["ticker", "year"], as_index=False).agg(agg)
             .sort_values(["ticker", "year"]).reset_index(drop=True))
    out["cash_dividend"] = out["cash_earnings"] + out.get("cash_surplus", 0.0)
    return out
