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
台灣季報法定期限：Q1 5/15、Q2 8/14、Q3 11/14、Q4 年報次年 3/31。
回測／重播每一季掛 `disclosure_date = 法定期限`——「某天看得到
哪一期財報」的判斷都用這個，不用 `period_end`。線上產品（`live=True`）資料在就算
已公布（`period_end + 1 天`），提早公布的公司抓到就用。
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

#: 舊常數（期末 +45 天），只留給還在引用它的研究腳本；loader 回測模式已改用法定期限。
STATEMENT_LAG_DAYS = 45

#: 各季財報法定公布期限（季末月 → (月, 日)）；Q4 年報在隔年 3/31。
#: 與 `corporate_actions._DEADLINE` 同一份規則。金融業半年報期限 8/31 較晚，這裡沒分產業
#: （金融股回測 Q2 最多早 17 天看到，已知缺口）。
STATEMENT_DEADLINE = {3: (5, 15), 6: (8, 14), 9: (11, 14), 12: (3, 31)}


def statement_deadline(period_end: pd.Series) -> pd.Series:
    """每季財報的法定公布期限（向量化）；非季末月份（異常資料）退回期末 +45 天。"""
    pe = pd.to_datetime(period_end)
    year = pe.dt.year + (pe.dt.month == 12).astype(int)
    md = pe.dt.month.map(STATEMENT_DEADLINE)
    out = pd.to_datetime(dict(year=year, month=md.str[0], day=md.str[1]), errors="coerce")
    return out.fillna(pe + pd.Timedelta(days=STATEMENT_LAG_DAYS))


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


def load_quarterly(live: bool = False) -> pd.DataFrame:
    """三表合併成季度面板，依 (ticker, period_end) 排序並加公告日。

    live=True（線上產品，asof＝今天）：資料裡有的季就是已經公布，`disclosure_date`
    設成期末隔天，提早公布的公司抓到就用（跟月營收一樣搶時間差）。
    live=False（回測／重播，預設）：用法定公布期限（Q1 5/15、Q2 8/14、Q3 11/14、
    Q4 隔年 3/31），不會用到當時還沒公布的財報。
    """
    q = merge_statements(_read("income"), _read("balance"), _read("cashflow"))
    if live:
        q["disclosure_date"] = q["period_end"] + pd.Timedelta(days=1)
    else:
        q["disclosure_date"] = statement_deadline(q["period_end"])
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
    sum_cols = ["cash_earnings", "stock_earnings"]
    if "cash_surplus" in d.columns:
        sum_cols.append("cash_surplus")
    grouped = d.groupby(["ticker", "year"])
    out = grouped[sum_cols].sum(min_count=1)
    dates = ["pay_date", "announce_date", "ex_date"]
    out = out.join(grouped[dates].max())
    cols = ["cash_earnings", "stock_earnings", *dates]
    if "cash_surplus" in d.columns:
        cols.append("cash_surplus")
    out = out[cols].reset_index().sort_values(["ticker", "year"]).reset_index(drop=True)
    cash_cols = [c for c in ["cash_earnings", "cash_surplus"] if c in out.columns]
    out["cash_dividend"] = out[cash_cols].sum(axis=1, min_count=1)
    return out
