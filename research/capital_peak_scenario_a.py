"""情境 A 資金峰值試算：14 條 tw-swing 規則各自獨立（不共用資金池），
單筆固定 10 萬元，統計每條規則「同時持有幾檔」的年度峰值 → 峰值 x 10萬 = 那一年
理論上最多要準備的資金。純統計，不重算報酬，複用 backtest_top17_buyable.py 的
事件過濾/回測邏輯拿到 trades（entry_date/exit_date），不落地成報告，只印結果。

用法：python research/capital_peak_scenario_a.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "research"))

import backtest_top17_buyable as B  # noqa: E402

PER_STOCK_CAP = 100_000  # 情境 A：一支股票最多 10 萬


def concurrent_counts(trades: pd.DataFrame, td: pd.DatetimeIndex) -> pd.Series:
    cnt = pd.Series(0, index=td)
    for t in trades.itertuples():
        i0 = td.searchsorted(t.entry_date)
        i1 = td.searchsorted(t.exit_date)
        if i1 < i0:
            continue
        cnt.iloc[i0:i1 + 1] += 1
    return cnt


def main() -> int:
    print("載入 universe…", flush=True)
    universe = B.load_universe()
    print(f"  universe {len(universe)} 檔", flush=True)

    print("跑 14 條 tw-swing 規則事件過濾 + next_open 回測（複用既有邏輯，取 trades）…", flush=True)
    sw_results, _specs = B.run_swing_rules(universe)

    rows = []
    peak_by_year_all = {}
    for rid, name, src in B.TWSWING_CANDIDATES:
        res = sw_results[rid]
        trades = res["trades"]
        if not len(trades):
            rows.append({"rule": rid, "name": name, "peak_overall": 0, "capital_needed": 0})
            continue
        td = pd.date_range(trades["entry_date"].min(), trades["exit_date"].max(), freq="B")
        cnt = concurrent_counts(trades, td)
        peak_overall = int(cnt.max())
        cnt_by_year = cnt.groupby(cnt.index.year).max()
        peak_by_year_all[rid] = cnt_by_year
        rows.append({
            "rule": rid, "name": name,
            "peak_overall": peak_overall,
            "capital_needed": peak_overall * PER_STOCK_CAP,
            "median_concurrent": int(cnt[cnt > 0].median()) if (cnt > 0).any() else 0,
        })

    df = pd.DataFrame(rows).sort_values("capital_needed", ascending=False)
    pd.set_option("display.unicode.east_asian_width", True)
    print("\n=== 情境 A：14 條規則各自獨立、單筆固定 10 萬，資金峰值需求（全期） ===\n")
    print(df.to_string(index=False, formatters={
        "capital_needed": lambda v: f"{v:,.0f}"
    }))

    total_if_independent = df["capital_needed"].sum()
    print(f"\n若 14 條規則各自準備獨立資金池、互不共用："
          f"總峰值需求 = {total_if_independent:,.0f} 元"
          f"（這是保守上界：假設所有規則同時都撞到自己的年度峰值，實際不會 14 條同天都最擁擠）")

    print("\n=== 各規則逐年峰值（同時持倉檔數） ===\n")
    year_tbl = pd.DataFrame(peak_by_year_all).fillna(0).astype(int)
    print(year_tbl.to_string())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
