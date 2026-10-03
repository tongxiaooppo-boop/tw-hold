"""三大法人買賣超（上市現貨，金額）——總經導航「三大法人」卡。

## 資料源

TWSE `https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&type=day&dayDate=YYYYMMDD`
（「三大法人買賣金額統計表」，免金鑰）。**可帶日期查歷史**，所以每次跑都補近 N 天「檔案裡還沒有
的平日」——首次跑自動回補、漏跑自癒；沒開市的日子 API 回非 OK，直接略過。

⚠️ openapi.twse.com.tw 的同名端點回的是 HTML，不要用；上面這個 www 的 rwd 路徑才是 JSON。
⚠️ 只含**上市**；上櫃（TPEx）不在這支裡。

欄位（單位：元）：外資 ＝ 外資及陸資(不含外資自營商) + 外資自營商；自營商 ＝ 自行買賣 + 避險；
另存 TWSE 自己給的「合計」，不自己加（加了跟官方對不上時才看得出來）。

用法：
    python scripts/fetch_inst_flow.py
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

URL = "https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&type=day&dayDate={d}"
OUT = Path(__file__).resolve().parents[1] / "data" / "reference" / "inst_flow.parquet"
BACKFILL_DAYS = 45     # 首次回補（日曆日）
REFRESH_DAYS = 14      # 平時補近 N 天缺的平日
SLEEP = 1.5            # TWSE 對連續請求會擋，保守間隔
UA = {"User-Agent": "Mozilla/5.0"}


def _num(x: str) -> int:
    return int(str(x).replace(",", "").strip())


def parse(j: dict) -> dict | None:
    """BFI82U JSON → `{date, foreign, trust, dealer, total}`（元）；不是 OK／缺列 → None。"""
    if j.get("stat") != "OK" or not j.get("data"):
        return None
    by = {str(r[0]).strip(): _num(r[3]) for r in j["data"]}

    def _get(prefix: str) -> int | None:
        for k, v in by.items():
            if k.startswith(prefix):
                return v
        return None

    parts = {"dealer_self": _get("自營商(自行買賣)"), "dealer_hedge": _get("自營商(避險)"),
             "trust": _get("投信"), "foreign_main": _get("外資及陸資(不含外資自營商)"),
             "foreign_dealer": _get("外資自營商"), "total": _get("合計")}
    if any(parts[k] is None for k in ("dealer_self", "dealer_hedge", "trust", "foreign_main", "total")):
        return None
    foreign = parts["foreign_main"] + (parts["foreign_dealer"] or 0)
    dealer = parts["dealer_self"] + parts["dealer_hedge"]
    if abs(foreign + parts["trust"] + dealer - parts["total"]) > 1:
        print(f"::warning::{j.get('date')} 外資+投信+自營≠官方合計，略過：{parts}")
        return None
    return {"date": pd.Timestamp(str(j["date"])), "foreign": foreign,
            "trust": parts["trust"], "dealer": dealer, "total": parts["total"]}


def fetch_day(d: date) -> dict | None:
    req = urllib.request.Request(URL.format(d=d.strftime("%Y%m%d")), headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return parse(json.loads(resp.read().decode("utf-8")))


def main() -> None:
    old = pd.read_parquet(OUT) if OUT.exists() else None
    have = set(pd.to_datetime(old["date"]).dt.date) if old is not None else set()
    today = date.today()
    span = REFRESH_DAYS if old is not None else BACKFILL_DAYS
    want = [today - timedelta(days=i) for i in range(span, -1, -1)]
    want = [d for d in want if d.weekday() < 5 and d not in have]
    recs, fails = [], 0
    for d in want:
        try:
            r = fetch_day(d)
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"::warning::{d} 抓取失敗：{type(e).__name__}: {e}")
            time.sleep(SLEEP)
            continue
        if r is not None:
            recs.append(r)
        time.sleep(SLEEP)
    if not recs:
        print(f"這次沒有新增（嘗試 {len(want)} 天，失敗 {fails}；假日或 TWSE 還沒更新）")
        return
    new = pd.DataFrame.from_records(recs)
    comb = new if old is None else pd.concat([old, new], ignore_index=True)
    comb = comb.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    comb.to_parquet(OUT, index=False)
    last = comb.iloc[-1]
    print(f"三大法人 {last['date'].date()} 合計 {last['total'] / 1e8:+.2f} 億"
          f"（外資 {last['foreign'] / 1e8:+.2f}／投信 {last['trust'] / 1e8:+.2f}／自營 {last['dealer'] / 1e8:+.2f}）"
          f"，新增 {len(recs)} 天，累積 {len(comb)} 天 → {OUT}")


if __name__ == "__main__":
    main()
