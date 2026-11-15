"""把 MOPS 當晚收集的月營收補進 bundle 長表缺的月份（長表優先）。用法見 --help。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reference.revenue_merge import fill_missing_months, mops_months  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", default=str(ROOT / "data/upstream/revenue.parquet"))
    ap.add_argument("--mops-dir", default=str(ROOT / "data/revenue_mops"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    up = Path(a.upstream)
    if not up.exists():
        print(f"警告：長表不存在 {up}，略過")
        return 0
    asof = pd.Timestamp.now(tz="Asia/Taipei").tz_localize(None).normalize()
    long = pd.read_parquet(up)
    new, n = fill_missing_months(long, mops_months(Path(a.mops_dir), asof))
    if n:
        added = new.merge(long[["ticker", "month"]], on=["ticker", "month"], how="left", indicator=True)
        added = added[added["_merge"] == "left_only"]
        print(f"補 {n} 列（{added['ticker'].nunique()} 家，月份 {sorted(added['month'].unique())}）")
    else:
        print("補 0 列")
    if n and not a.dry_run:
        try:
            new.to_parquet(up, index=False)
        except Exception as exc:
            print(f"寫檔失敗：{exc}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
