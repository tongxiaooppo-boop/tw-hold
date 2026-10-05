"""自建上游 P1：官方**未還原**日線（上市 + 上櫃）依日期收集 → `data/selfhost/raw_prices.parquet`。

## 為什麼存在
上游 data_pack 的還原價有「還原接縫」缺陷（見 `tw-swing/docs/analysis/tw-stock-scanner-1005-analysis.md`）：
`updater.py` 只重抓最近 7 天，除息日前 ~8 天以上的歷史留在舊基準。要偵測／訂正，需要官方未還原價當裁判。
`PLAN_OWN_UPSTREAM.md` P1 本來就要做這件事；這支是它的第一個 collector（只收價，法人／融資券之後再加）。

## 資料源（2026-10-05 實測，見 `tw-swing/docs/reference/twse_tpex_pitfalls.md` §G）
- 上市：`www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=YYYYMMDD&type=ALLBUT0999&response=json`
  取 title 含「每日收盤行情」那張表；回應頂層 `date` 必須等於請求日。
- 上櫃：`www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date=YYYY/MM/DD&response=json`
  （⚠️ 不是只回最新日的 openapi 版）；回應頂層 `date` 必須等於請求日；休市日 `totalCount=0`。

## 規矩
- 請求帶日期就斷言回應日期（日期不符 → 丟棄並警告，絕不存）。
- 只存「檔案裡還沒有的平日」→ 重複跑冪等、漏跑自癒；休市日（空表）略過、不重試。
- 單日上市或上櫃任一邊失敗 → 該日**整天不寫**（all-or-nothing），下次再補，不留半邊。
- 代號只留 4 碼純數字（跟上游宇宙規則一致，見 UPSTREAM_PRACTICES_AUDIT P5）。

用法：
    python scripts/selfhost_raw_prices.py                       # 補近 REFRESH_DAYS 天缺的
    python scripts/selfhost_raw_prices.py --start 2026-06-01    # 首次回補
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

TWSE = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALLBUT0999&response=json"
TPEX = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={d}&response=json"
OUT = Path(__file__).resolve().parents[1] / "data" / "selfhost" / "raw_prices.parquet"
REFRESH_DAYS = 14
SLEEP = 2.0
UA = {"User-Agent": "Mozilla/5.0"}
COLS = ["ticker", "market", "date", "open", "high", "low", "close", "volume", "value"]


def _get(url: str, retries: int = 3) -> dict | None:
    """用 requests（certifi 憑證庫）——TPEx 憑證鏈缺中繼憑證，urllib 的系統憑證庫會驗證失敗。"""
    for i in range(retries):
        try:
            r = requests.get(url, headers=UA, timeout=40)
            r.raise_for_status()
            return r.json()
        except Exception as e:   # 網路／JSON 錯誤 → 退避重試
            print(f"  請求失敗（第 {i + 1} 次）：{str(e)[:80]}", file=sys.stderr)
            time.sleep(3 * (i + 1))
    return None


def _num(x) -> float | None:
    s = str(x).replace(",", "").strip()
    if s in ("", "--", "---", "----", "X0.00", "nan"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def _rows(table: dict, idx: dict[str, str], market: str, d: str) -> pd.DataFrame:
    """`idx`: 標準欄名 → 官方欄名。用欄名（不是固定位置）取欄，耐改版。"""
    fields = table["fields"]
    pos = {k: fields.index(v) for k, v in idx.items()}
    out = []
    for r in table["data"]:
        code = str(r[0]).strip()
        if not (code.isdigit() and len(code) == 4):
            continue
        close = _num(r[pos["close"]])
        if close is None:         # 當日無成交
            continue
        out.append({
            "ticker": code, "market": market, "date": pd.Timestamp(d),
            "open": _num(r[pos["open"]]) or close, "high": _num(r[pos["high"]]) or close,
            "low": _num(r[pos["low"]]) or close, "close": close,
            "volume": _num(r[pos["volume"]]) or 0.0, "value": _num(r[pos["value"]]) or 0.0,
        })
    return pd.DataFrame(out, columns=COLS)


def fetch_twse(d: date) -> pd.DataFrame | None:
    """None＝抓取失敗；空表＝休市。"""
    ymd = d.strftime("%Y%m%d")
    j = _get(TWSE.format(d=ymd))
    if j is None:
        return None
    if j.get("stat") != "OK":
        return pd.DataFrame(columns=COLS)           # 休市（非錯誤）
    if str(j.get("date")) != ymd:
        print(f"::warning::TWSE {ymd} 回應日期 {j.get('date')} 不符，丟棄", file=sys.stderr)
        return None
    for t in j.get("tables", []):
        if t.get("title") and "每日收盤行情" in t["title"] and t.get("data"):
            return _rows(t, {"open": "開盤價", "high": "最高價", "low": "最低價", "close": "收盤價",
                             "volume": "成交股數", "value": "成交金額"}, "TW", ymd)
    return pd.DataFrame(columns=COLS)


def fetch_tpex(d: date) -> pd.DataFrame | None:
    ymd = d.strftime("%Y%m%d")
    j = _get(TPEX.format(d=d.strftime("%Y/%m/%d")))
    if j is None:
        return None
    if str(j.get("date")) != ymd:
        print(f"::warning::TPEx {ymd} 回應日期 {j.get('date')} 不符，丟棄", file=sys.stderr)
        return None
    tabs = j.get("tables") or []
    if not tabs or not tabs[0].get("totalCount") or not tabs[0].get("data"):
        return pd.DataFrame(columns=COLS)           # 休市
    return _rows(tabs[0], {"open": "開盤", "high": "最高", "low": "最低", "close": "收盤",
                           "volume": "成交股數", "value": "成交金額(元)"}, "TWO", ymd)


def collect_day(d: date) -> pd.DataFrame | None:
    """上市＋上櫃合併；任一邊失敗 → None（整天不寫）；兩邊都空 → 空表（休市）。"""
    a = fetch_twse(d)
    time.sleep(SLEEP)
    b = fetch_tpex(d)
    time.sleep(SLEEP)
    if a is None or b is None:
        return None
    if a.empty != b.empty:       # 只有一邊有資料 = 異常（其中一邊壞了），不存
        print(f"::warning::{d} 上市 {len(a)} 檔 / 上櫃 {len(b)} 檔，只有單邊有資料，整天不寫", file=sys.stderr)
        return None
    return pd.concat([a, b], ignore_index=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", help="YYYY-MM-DD；預設今天往前 REFRESH_DAYS 天")
    ap.add_argument("--end", help="YYYY-MM-DD；預設今天")
    a = ap.parse_args(argv)
    end = datetime.strptime(a.end, "%Y-%m-%d").date() if a.end else date.today()
    start = datetime.strptime(a.start, "%Y-%m-%d").date() if a.start else end - timedelta(days=REFRESH_DAYS)

    old = pd.read_parquet(OUT) if OUT.exists() else pd.DataFrame(columns=COLS)
    have = set(pd.to_datetime(old["date"]).dt.date) if len(old) else set()
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    todo = [d for d in days if d.weekday() < 5 and d not in have]
    print(f"範圍 {start}~{end}；檔案已有 {len(have)} 天；待抓平日 {len(todo)} 天")

    new, failed, closed = [], [], 0

    def flush() -> None:
        """寫檔（續跑友善：每 10 天存一次，被中斷也不白跑）。"""
        nonlocal old, new
        if not new:
            return
        OUT.parent.mkdir(parents=True, exist_ok=True)
        allp = pd.concat([old] + new, ignore_index=True)
        allp = allp.drop_duplicates(["ticker", "market", "date"], keep="last")
        allp = allp.sort_values(["date", "market", "ticker"]).reset_index(drop=True)
        allp.to_parquet(OUT, index=False, compression="zstd")
        old, new = allp, []
        print(f"  已寫入 {OUT.name}（{len(allp)} 列，{allp['date'].nunique()} 天）", flush=True)

    for i, d in enumerate(todo, 1):
        df = collect_day(d)
        if df is None:
            failed.append(d)
        elif df.empty:
            closed += 1
        else:
            new.append(df)
            print(f"  {d} 上市 {int((df.market == 'TW').sum())} 檔 / 上櫃 {int((df.market == 'TWO').sum())} 檔", flush=True)
        if i % 10 == 0:
            flush()
    flush()
    print(f"休市 {closed} 天；失敗 {len(failed)} 天 {[str(x) for x in failed]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
