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


def merge(base: str) -> None:
    parts = [SH / f"{base}_{m}.parquet" for m in ("TW", "TWO")]
    parts = [p for p in parts if p.exists()]
    if not parts:
        print(f"{base}：沒有單市場檔，略過")
        return
    out = SH / f"{base}.parquet"
    frames = ([pd.read_parquet(out)] if out.exists() else []) + [pd.read_parquet(p) for p in parts]
    df = pd.concat(frames, ignore_index=True).drop_duplicates(KEYS, keep="last").sort_values(["date", "market", "ticker"])
    df.to_parquet(out, index=False, compression="zstd")
    print(f"{base}：合併 {len(parts)} 個單市場檔 → {len(df)} 列、{df['date'].nunique()} 天（{pd.Timestamp(df['date'].min()).date()}～{pd.Timestamp(df['date'].max()).date()}）")


if __name__ == "__main__":
    for b in ("raw_prices", "inst", "margin"):
        merge(b)
    sys.exit(0)
