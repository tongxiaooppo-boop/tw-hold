"""月營收長表（OpenAPI）＋MOPS 當晚收集的補缺月（全 tw-hold 共用）。

規則：長表已有的 (ticker, month) 以長表為準，MOPS 只補缺的；只收 first_seen_at 日期 ≤ asof；
revenue 缺值或 ≤0 不收；目錄／檔不存在或讀檔失敗 → 不中斷。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

MOPS_COLS = ["ticker", "month", "revenue", "first_seen_at"]


def _empty() -> pd.DataFrame:
    return pd.DataFrame({"ticker": pd.Series(dtype="str"), "month": pd.Series(dtype="str"),
                         "revenue": pd.Series(dtype="float64"),
                         "first_seen_at": pd.Series(dtype="datetime64[ns]")})


def mops_months(mops_dir: Path, asof: pd.Timestamp | None = None) -> pd.DataFrame:
    """讀 mops_dir 全部 *.parquet → [ticker(裸代號), month "YYYY-MM", revenue, first_seen_at(tz-naive)]。"""
    mops_dir = Path(mops_dir)
    files = sorted(mops_dir.glob("*.parquet")) if mops_dir.is_dir() else []
    parts = []
    for f in files:
        try:
            d = pd.read_parquet(f, columns=["code", "period", "revenue", "first_seen_at"])
        except Exception:
            continue
        parts.append(pd.DataFrame({
            "ticker": d["code"].astype(str),
            "month": d["period"].astype(str),
            "revenue": pd.to_numeric(d["revenue"], errors="coerce").astype("float64"),
            "first_seen_at": pd.to_datetime(d["first_seen_at"], errors="coerce", utc=False)}))
    if not parts:
        return _empty()
    out = pd.concat(parts, ignore_index=True)
    seen = out["first_seen_at"]
    if getattr(seen.dt, "tz", None) is not None:
        seen = seen.dt.tz_localize(None)
    out["first_seen_at"] = seen.astype("datetime64[ns]")
    out = out[out["first_seen_at"].notna() & out["revenue"].notna() & (out["revenue"] > 0)]
    if asof is not None:
        out = out[out["first_seen_at"].dt.normalize() <= pd.Timestamp(asof).normalize()]
    out = (out.sort_values(["first_seen_at", "ticker", "month"], kind="stable")
              .drop_duplicates(["ticker", "month"], keep="first"))
    return out.sort_values(["ticker", "month"]).reset_index(drop=True)[MOPS_COLS]


def fill_missing_months(long: pd.DataFrame, mops: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """只加長表沒有的 (ticker, month)；announced＝first_seen_at 當天；欄位／dtype 同 long。"""
    if mops is None or mops.empty:
        return long, 0
    have = pd.MultiIndex.from_frame(long[["ticker", "month"]].astype(str)) if len(long) else \
        pd.MultiIndex.from_arrays([[], []])
    key = pd.MultiIndex.from_frame(mops[["ticker", "month"]].astype(str))
    add = mops[~key.isin(have)]
    if add.empty:
        return long, 0
    new = pd.DataFrame({"ticker": add["ticker"].astype(str).values,
                        "month": add["month"].astype(str).values,
                        "revenue": add["revenue"].astype("float64").values})
    if "announced" in long.columns:
        new["announced"] = add["first_seen_at"].dt.normalize().values
    new = new.reindex(columns=list(long.columns))
    for c in long.columns:
        try:
            new[c] = new[c].astype(long[c].dtype)
        except Exception:
            pass
    out = pd.concat([long, new], ignore_index=True)
    out = out.sort_values(["ticker", "month"], kind="stable").reset_index(drop=True)
    return out, len(new)
MOPS_DIR_DEFAULT = Path(__file__).resolve().parents[1] / "data" / "revenue_mops"
