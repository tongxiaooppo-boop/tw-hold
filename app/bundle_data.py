"""個股查詢的資料層（M4）——雲端執行期從 tw-swing Release 拉 bundle、按需讀。

🔴 **Streamlit Cloud 只有 1GB RAM**（PRD §M4）：
  - bundle parquet 檔一次性下載到容器暫存磁碟（`data/upstream/`），`st.cache_resource`
    只跑一次。
  - 每次查詢用 `pyarrow` 的 `filters=[("ticker","==",x)]` + `columns=[...]` **只讀那一檔
    那幾欄**，絕不整張 `pd.read_parquet()`。

PAT：`fetch_bundle._read_pat()`（.env / 環境變數 / `st.secrets["TWSWING_BUNDLE_PAT"]`）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import fetch_bundle as fb   # noqa: E402  reuse _read_pat / _api / _release_assets

UPSTREAM = _REPO / "data" / "upstream"

#: 個股頁要的檔（不含 chips——法人買賣超個股頁 v1 先不畫）
_ASSETS = ["prices_adj.parquet", "prices_raw_close.parquet", "per.parquet",
           "income.parquet", "balance.parquet", "cashflow.parquet", "dividend.parquet"]
_FUND = {"income.parquet", "balance.parquet", "cashflow.parquet", "dividend.parquet"}


def _dest(name: str) -> Path:
    return UPSTREAM / ("fundamentals" / Path(name) if name in _FUND else Path(name))


def ensure_assets() -> dict:
    """把個股頁要的 bundle 檔下載到 `data/upstream/`（已存在且非空就跳過）。
    回傳 `{name: bool 有沒有}`。呼叫端用 `st.cache_resource` 包一次。"""
    pat = fb._read_pat()
    if not pat:
        return {n: _dest(n).exists() for n in _ASSETS}
    by_name = {a["name"]: a for a in fb._release_assets(pat)}
    got = {}
    for name in _ASSETS:
        d = _dest(name)
        if d.exists() and d.stat().st_size > 0:
            got[name] = True
            continue
        asset = by_name.get(name)
        if asset is None:
            got[name] = False
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_bytes(fb._api(asset["url"], pat, accept="application/octet-stream"))
        got[name] = True
    return got


def _t(code: str) -> str:
    return str(code).strip().split(".")[0]


def _read(name: str, code: str, suffixed: bool, columns: list[str] | None = None
          ) -> pd.DataFrame:
    """`suffixed` = 這張表的 ticker 帶 .TW/.TWO（prices）；否則裸代號（per / 財報 / 股利）。"""
    p = _dest(name)
    if not p.exists():
        return pd.DataFrame(columns=columns or [])
    c = _t(code)
    vals = [f"{c}.TW", f"{c}.TWO", c] if suffixed else [c]
    try:
        df = pd.read_parquet(p, filters=[("ticker", "in", vals)], columns=columns)
    except Exception:
        df = pd.read_parquet(p, columns=columns)
        df = df[df["ticker"].astype(str).map(_t) == c]
    return df.reset_index(drop=True)


def prices(code: str, lookback_days: int = 900) -> pd.DataFrame:
    d = _read("prices_adj.parquet", code, True,
              ["date", "ticker", "open", "high", "low", "close", "volume"])
    if d.empty:
        return d
    d["date"] = pd.to_datetime(d["date"])
    cut = d["date"].max() - pd.Timedelta(days=lookback_days)
    return d[d["date"] >= cut].sort_values("date").reset_index(drop=True)


def per_history(code: str) -> pd.DataFrame:
    d = _read("per.parquet", code, False, ["date", "ticker", "per", "pbr", "dividend_yield"])
    if not d.empty:
        d["date"] = pd.to_datetime(d["date"])
    return d.sort_values("date").reset_index(drop=True) if not d.empty else d


def financials(code: str) -> pd.DataFrame:
    """income ∪ balance ∪ cashflow，對齊 period_end。"""
    inc = _read("income.parquet", code, False)
    bal = _read("balance.parquet", code, False)
    cf = _read("cashflow.parquet", code, False)
    if inc.empty:
        return inc
    df = inc.merge(bal, on=["ticker", "period_end"], how="left", suffixes=("", "_b")) \
            .merge(cf, on=["ticker", "period_end"], how="left", suffixes=("", "_c"))
    df["period_end"] = pd.to_datetime(df["period_end"])
    return df.sort_values("period_end").reset_index(drop=True)


def dividends(code: str) -> pd.DataFrame:
    d = _read("dividend.parquet", code, False)
    if d.empty:
        return d
    for c in ("pay_date", "CashExDividendTradingDate"):
        if c in d.columns:
            d[c] = pd.to_datetime(d[c], errors="coerce")
    return d.sort_values("year").reset_index(drop=True)
