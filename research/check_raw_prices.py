"""§1.3 守門員 G2：F3 抓完未還原收盤後**立刻驗一條**。

抽 0056 / 2412 的除息日：
  未還原序列 → 除息當天應有 −4% ~ −7% 的跳空
  還原序列   → 沒有跳空（tw-swing PRD §5.2.1 實測 +0.36% ~ +1.14%）
跳空不見了 = 抓錯序列 → 停下來。

理由：若 prices_raw 被誤填成還原序列，填息率會恆等於 100%、定存清單全綠、
且沒有任何東西會報錯。這是整條路上最毒的靜默錯誤。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

TWSWING = Path(r"d:\g\claude\tw-swing")
sys.path.insert(0, str(TWSWING / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from twswing.data import store
from twswing.value import loader

RAW = TWSWING / "data" / "fundamentals" / "prices_raw.parquet"


def main() -> int:
    if not RAW.exists():
        print(f"[FAIL] {RAW} 不存在——先跑 scripts/fetch_raw_prices.py")
        return 1
    raw = pd.read_parquet(RAW)
    raw["code"] = raw["ticker"].astype(str).str.split(".").str[0]
    adj = store.read_daily(recent=False, columns=["date", "ticker", "open", "close"])
    adj["code"] = adj["ticker"].astype(str).str.split(".").str[0]
    div = loader.load_dividends()
    div["ticker"] = div["ticker"].astype(str)

    ok = True
    for code in ("0056", "2412", "2882"):
        exs = sorted(div[(div["ticker"] == code) & (div["cash_dividend"] > 0)
                         & (div["ex_date"] >= "2020-01-01")]["ex_date"])
        if not exs:
            print(f"{code}: 無 2020 後除息紀錄，跳過")
            continue
        r = raw[raw["code"] == code].set_index("date").sort_index()
        a = adj[adj["code"] == code].set_index("date").sort_index()
        print(f"\n{code}（{len(exs)} 個除息日，2020+）")
        for ex in exs:
            ex = pd.Timestamp(ex)
            rp = r.loc[r.index < ex, "close"]
            ro = r.loc[r.index >= ex, "open"]
            ap = a.loc[a.index < ex, "close"]
            ao = a.loc[a.index >= ex, "open"]
            if rp.empty or ro.empty or ap.empty or ao.empty:
                continue
            raw_gap = ro.iloc[0] / rp.iloc[-1] - 1
            adj_gap = ao.iloc[0] / ap.iloc[-1] - 1
            flag = "OK" if raw_gap < -0.005 and abs(adj_gap) < abs(raw_gap) else "⚠️ 檢查"
            if flag != "OK":
                ok = False
            print(f"  {ex.date()}  未還原跳空 {raw_gap:+.2%} | 還原跳空 {adj_gap:+.2%}  [{flag}]")

    print("\n" + ("[OK] 未還原序列在除息日確實有跳空、還原序列沒有——抓對了。"
                  if ok else "🔴 [FAIL] 有除息日未還原序列沒跳空——可能抓到還原序列，停下來查。"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
