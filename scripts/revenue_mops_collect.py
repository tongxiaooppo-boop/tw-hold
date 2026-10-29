"""月營收公布期每晚抓 MOPS 彙總頁，記下每家「第一次看到」的時間。

⚠️ **漏抓補不回來**：頁面只有最新狀態，
今晚沒存，就永遠不知道哪幾家是今晚才出現的。

每次執行：
- 兩個市場各打一發（間隔幾秒、斷線退避重試），MOPS 連打會被斷線。
- 併進 `data/revenue_mops/<期別>.parquet`（見 revenue_mops.merge_seen）。
- 不論成敗都 append 一行到 `data/revenue_mops/runs.csv`——逐次列數就是
  「頁面是不是逐家長出來」的證據（2026-11 第一個公布期要回頭看）。

用法：
    python scripts/revenue_mops_collect.py
    python scripts/revenue_mops_collect.py --period 2026-09 --dry-run
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import requests

from reference import revenue_mops as rm

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://mopsov.twse.com.tw/"}


def _taipei_now() -> pd.Timestamp:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return pd.Timestamp(datetime.now(ZoneInfo("Asia/Taipei")).replace(tzinfo=None))


def fetch(url: str, tries: int = 4) -> tuple[bytes | None, str | None]:
    last = ""
    for i in range(tries):
        if i:
            time.sleep(15 * i)
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            if r.status_code < 500:
                r.raise_for_status()
                return r.content, None
            last = f"HTTP {r.status_code}"
        except requests.HTTPError as e:
            return None, f"{type(e).__name__}: {e}"
        except Exception as e:                       # noqa: BLE001 - 斷線/逾時都重試
            last = f"{type(e).__name__}: {e}"
    return None, last


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", help="YYYY-MM，預設＝台北今天的上個月")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = _taipei_now().floor("min")
    period = (pd.Period(args.period, freq="M") if args.period
              else rm.target_period(now))
    if now.day > rm.WINDOW_LAST_DAY and not args.dry_run:
        # 公布期外抓到的是早就公布完的一期，記成「今天第一次看到」是假的公告時間
        # （2026-10-29 手動觸發就踩到）。只抓、印，不寫——當連線檢查用。
        print(f"今天 {now:%m/%d} 不在公布期（1～{rm.WINDOW_LAST_DAY} 號），只抓不寫")
        args.dry_run = True

    frames, log, failed = [], [], []
    for i, market in enumerate(rm.MARKETS):
        if i:
            time.sleep(5)
        url = rm.page_url(market, period)
        raw, err = fetch(url)
        if err:
            failed.append(market)
            print(f"[FAIL] {market} {err}")
            log.append({"run_at": now, "period": str(period), "market": market,
                        "rows": None, "error": err})
            continue
        df = rm.parse_page(rm.decode(raw), market, period)
        print(f"[OK]   {market:<5} {period} {len(df):>5} 家  ({len(raw):,} bytes)")
        log.append({"run_at": now, "period": str(period), "market": market,
                    "rows": len(df), "error": ""})
        frames.append(df)

    snapshot = (pd.concat(frames, ignore_index=True) if frames
                else pd.DataFrame(columns=rm.COLUMNS[:-3]))
    existing = rm.load_period(period)
    merged = rm.merge_seen(existing, snapshot, now)
    n_new = len(merged) - (0 if existing is None else len(existing))

    print(f"\n{period}：累積 {len(merged)} 家，本次新出現 {n_new} 家")
    if n_new:
        fresh = merged[merged["first_seen_at"] == now].copy()
        fresh["yoy%"] = (fresh["revenue"] / fresh["revenue_last_year"] - 1) * 100
        print(fresh.sort_values("yoy%", ascending=False)
              [["ticker", "name", "revenue", "yoy%"]].head(15)
              .to_string(index=False, float_format=lambda x: f"{x:,.1f}"))

    if args.dry_run:
        print("\n[DRY-RUN] 不寫檔")
        return 0 if not failed else 1

    rm.MOPS_DIR.mkdir(parents=True, exist_ok=True)
    if not snapshot.empty:
        merged.to_parquet(rm.period_path(period), index=False)
    pd.DataFrame(log).to_csv(rm.RUNS_LOG, mode="a", index=False,
                             header=not rm.RUNS_LOG.exists(), encoding="utf-8")
    # 兩個市場都失敗才算失敗；一邊失敗另一邊照存（那一邊仍是今晚唯一的證據）
    return 1 if len(failed) == len(rm.MARKETS) else 0


if __name__ == "__main__":
    sys.exit(main())
