"""估值卡輸入組裝（估值 2.0 P4，規格 docs/val2/P4_spec.md §2）。

【框架由 Opus 定（2026-11-02），實作者不得改介面】app 個股頁與 scripts/val2_dryrun_cards.py **共用這一支**，
不准另寫第二套組法（避免畫面與乾跑卡片不同）。
"""
from __future__ import annotations

from pathlib import Path
import json

import pandas as pd

DERIVED = Path(__file__).resolve().parent.parent / "data" / "derived"
MOPS_DIR = Path(__file__).resolve().parent.parent / "data" / "revenue_mops"
MH_FILE = "multiples_hist.parquet"
REV_FILE = "eps_revision.parquet"
IND_FILE = "industry_pe.json"
DERIVED_RELEASE = "https://github.com/tongxiaooppo-boop/tw-hold/releases/download/derived-latest"
REFRESH_HOURS = 6


def ensure_multiples(derived: Path = DERIVED, now: float | None = None, fetch=None) -> None:
    """缺檔或超過 6 小時重抓兩個倍數檔；先寫 .part，失敗保留舊檔。"""
    import time
    import urllib.request
    now = time.time() if now is None else now
    fetch = urllib.request.urlretrieve if fetch is None else fetch
    derived = Path(derived)
    derived.mkdir(parents=True, exist_ok=True)
    for name in (MH_FILE, REV_FILE):
        path = derived / name
        if path.exists() and now - path.stat().st_mtime <= REFRESH_HOURS * 3600:
            continue
        part = path.with_suffix(path.suffix + ".part")
        try:
            fetch(f"{DERIVED_RELEASE}/{name}", part)
            part.replace(path)
        except Exception:
            part.unlink(missing_ok=True)


def quarterly(inc: pd.DataFrame, bal: pd.DataFrame, cf: pd.DataFrame) -> pd.DataFrame:
    """單檔三表 → build_card 的 qf：loader.merge_statements(inc, bal, cf)（how 預設 outer，與 load_quarterly 相同）
    → disclosure_date＝period_end＋1 天（live）→ corporate_actions.adjust_eps。不用 factors.quarterly_factors。
    三表任一空 → 照 merge_statements 的行為（inc 空回空表）。"""
    from reference import loader, corporate_actions
    q = loader.merge_statements(inc, bal, cf)
    q["disclosure_date"] = q["period_end"] + pd.Timedelta(days=1)
    return corporate_actions.adjust_eps(q)


def load_mh(code: str, derived: Path = DERIVED) -> pd.DataFrame:
    """multiples_hist.parquet 中該檔的列（pyarrow filters 篩 ticker，不整檔讀進記憶體）；檔不存在或沒有該檔 → 空 DataFrame
    （欄位＝multiples_self.HIST_COLUMNS）。"""
    from screener.multiples_self import HIST_COLUMNS
    return _read_ticker(derived / MH_FILE, code, HIST_COLUMNS)


def load_rev_hist(code: str, derived: Path = DERIVED) -> pd.DataFrame:
    """eps_revision.parquet 中該檔的列；同 load_mh 規則（欄：ticker, month, window, eps_fwd, n_est_q, event）。"""
    return _read_ticker(derived / REV_FILE, code,
                        ("ticker", "month", "window", "eps_fwd", "n_est_q", "event"))


def load_industry_pe(derived: Path = DERIVED) -> dict | None:
    """industry_pe.json 的 "industries"；檔不存在 → None。"""
    path = derived / IND_FILE
    return json.loads(path.read_text(encoding="utf-8"))["industries"] if path.exists() else None


def card_inputs(code: str, asof: pd.Timestamp, cls: dict | None, derived: Path = DERIVED,
                bundle=None) -> dict:
    """回傳 build_card 的關鍵字參數 {qf, rev, px, cls, mh, rev_hist, industry_pe, asof, basic}；
    derived 下三個倍數檔任一不存在 → {"missing": val_view.MSG_NO_MULTIPLES}。
    bundle＝提供 income／balance／cashflow／revenue／prices_raw_close 單檔讀取的物件（app 傳 bundle_data 模組；
    乾跑傳讀 data/upstream 的轉接物件），介面：bundle.read(name: str, code: str) -> pd.DataFrame。
    None → 用 app/bundle_data。px＝prices_raw_close 的 date／close，只留 date ≤ asof。
    cls 由呼叫端給（app 讀 stock_class.json），None 照傳（build_card 自己給 D）。"""
    from app.val_view import MSG_NO_MULTIPLES
    if not all((derived / name).exists() for name in (MH_FILE, REV_FILE, IND_FILE)):
        return {"missing": MSG_NO_MULTIPLES}
    if bundle is None:
        from app import bundle_data
        bundle = bundle_data
    if not hasattr(bundle, "read"):
        bundle = _AppBundle(bundle)
    q = quarterly(*(bundle.read(name, code) for name in ("income", "balance", "cashflow")))
    px = bundle.read("prices_raw_close", code).copy()
    px["date"] = pd.to_datetime(px["date"])
    px = px.loc[px["date"] <= asof, ["date", "close"]].sort_values("date").reset_index(drop=True)
    try:
        per = bundle.read("per", code)
        exch = px.merge(per[["date", "pbr"]].assign(date=lambda d: pd.to_datetime(d.date)), on="date")
    except (OSError, KeyError, ValueError):
        exch = None
    return dict(qf=q, rev=merge_mops_revenue(bundle.read("revenue", code), code, asof), px=px, cls=cls,
                exch=exch,
                mh=load_mh(code, derived), rev_hist=load_rev_hist(code, derived),
                industry_pe=load_industry_pe(derived), asof=asof,
                basic=bundle.company_basic(code) if hasattr(bundle, "company_basic") else None)


def merge_mops_revenue(rev: pd.DataFrame, code: str, asof: pd.Timestamp,
                       mops_dir: Path = MOPS_DIR) -> pd.DataFrame:
    """bundle 月營收（官方 OpenAPI 快照，每月 10 日截止後才整市場換期）併入 MOPS 當晚收集
    （data/revenue_mops/<月>.parquet）已公告的月份，讓早公布的個股前瞻窗口先動（2026-11-03 使用者要求）。
    - bundle 已有的月份以 bundle 為準，MOPS 只補缺的月份。
    - 只收 first_seen_at 的日期 ≤ asof 的列（乾跑用過去的 asof 時不偷看未來）。
    - 目錄或檔案不存在、讀檔失敗 → 原樣回傳。格式同 bundle_data.revenue：[month(月初 Timestamp), revenue]。"""
    files = sorted(Path(mops_dir).glob("*.parquet")) if Path(mops_dir).is_dir() else []
    have = set(pd.to_datetime(rev["month"]).dt.to_period("M")) if len(rev) else set()
    add = []
    for f in files:
        try:
            d = pd.read_parquet(f, columns=["code", "period", "revenue", "first_seen_at"])
        except Exception:
            continue
        d = d[d["code"].astype(str) == str(code)]
        for r in d.itertuples():
            m = pd.Period(str(r.period), "M")
            seen = pd.Timestamp(r.first_seen_at) if pd.notna(r.first_seen_at) else None
            if (m in have or seen is None or seen.normalize() > pd.Timestamp(asof)
                    or not pd.notna(r.revenue) or r.revenue <= 0):
                continue
            add.append({"month": m, "revenue": float(r.revenue)})
            have.add(m)
    if not add:
        return rev
    is_ts = pd.api.types.is_datetime64_any_dtype(rev["month"]) or not len(rev)
    for a in add:   # 沿用輸入的月份格式（app＝月初 Timestamp；乾跑 LocalBundle＝"YYYY-MM" 字串）
        a["month"] = a["month"].start_time if is_ts else str(a["month"])
    out = pd.concat([rev, pd.DataFrame(add)], ignore_index=True)
    order = pd.to_datetime(out["month"].astype(str)).argsort(kind="stable")
    return out.iloc[order].reset_index(drop=True)


def _read_ticker(path, code, columns):
    if not path.exists():
        return pd.DataFrame(columns=columns)
    rows = pd.read_parquet(path, filters=[("ticker", "==", str(code))])
    return rows if not rows.empty else pd.DataFrame(columns=columns)


class _AppBundle:
    """將既有 bundle 模組的單檔函式接到共用 read 介面。"""

    def __init__(self, module):
        self.module = module

    def read(self, name, code):
        if name == "revenue":
            return self.module.revenue(code)
        return self.module._read(name + ".parquet", code, name == "prices_raw_close")

    def company_basic(self, code):
        return self.module.company_basic(code) if hasattr(self.module, "company_basic") else None
