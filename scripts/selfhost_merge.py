"""把平行回補的各市場檔合併回正式檔（raw_prices／inst／margin）。

平行回補時 TWSE 線與 TPEx 線各寫各的檔（`raw_prices_TW.parquet`、`raw_prices_TWO.parquet`、`inst_TW.parquet` …），
避免兩個進程整份覆寫同一個檔。回補完成後跑這支合併；每日排程（selfhost_collect.yml）用的是合併後的正式檔。

    python scripts/selfhost_merge.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

SH = Path(__file__).resolve().parents[1] / "data" / "selfhost"
KEYS = ["date", "ticker", "market"]


def _drop_cross_market_dups(df: pd.DataFrame) -> pd.DataFrame:
    """同日同代號在上市、上櫃各有一列（上櫃轉上市當天兩邊報表都列；或端點殘列）→ 留「當日實價所在市場」那列。
    實測 2026-10-06：4739 在 2017-09-07（上櫃最後交易日）兩邊數值完全相同；6201 在 2016-09-26 上櫃端點多一列殘列。"""
    dup = df.duplicated(["date", "ticker"], keep=False)
    if not dup.any():
        return df
    raw = SH / "raw_prices.parquet"
    if not raw.exists():
        return df
    px = pd.read_parquet(raw, columns=["date", "ticker", "market"]).drop_duplicates()
    d = df[dup].merge(px.assign(_px=True), on=["date", "ticker", "market"], how="left")
    drop_idx = d.index[(d["_px"] != True)]            # noqa: E712 — 這個市場當天沒有實價的那列
    keys = d.loc[drop_idx, ["date", "ticker", "market"]]
    # 兩邊都沒有實價（例：實價缺料）→ 不動，避免誤刪
    both_missing = d.groupby(["date", "ticker"])["_px"].transform(lambda s: (s != True).all())  # noqa: E712
    keys = d.loc[drop_idx[~both_missing.loc[drop_idx].to_numpy()], ["date", "ticker", "market"]]
    if keys.empty:
        return df
    key = list(zip(keys["date"], keys["ticker"], keys["market"]))
    print(f"  跨市場同日重複：丟掉 {len(key)} 列（留當日實價所在市場）：{[(str(k[0])[:10], k[1], k[2]) for k in key][:6]}")
    mask = pd.Series(list(zip(df["date"], df["ticker"], df["market"])), index=df.index).isin(set(key))
    return df[~mask]


def merge(base: str) -> None:
    parts = [SH / f"{base}_{m}.parquet" for m in ("TW", "TWO")]
    parts = [p for p in parts if p.exists()]
    if not parts:
        print(f"{base}：沒有單市場檔，略過")
        return
    out = SH / f"{base}.parquet"
    frames = ([pd.read_parquet(out)] if out.exists() else []) + [pd.read_parquet(p) for p in parts]
    df = pd.concat(frames, ignore_index=True).drop_duplicates(KEYS, keep="last").sort_values(["date", "market", "ticker"])
    if base == "margin":
        df = _drop_cross_market_dups(df)
    df.to_parquet(out, index=False, compression="zstd")
    print(f"{base}：合併 {len(parts)} 個單市場檔 → {len(df)} 列、{df['date'].nunique()} 天（{pd.Timestamp(df['date'].min()).date()}～{pd.Timestamp(df['date'].max()).date()}）")


if __name__ == "__main__":
    for b in ("raw_prices", "inst", "margin", "notrade", "refmark"):
        merge(b)
    sys.exit(0)
