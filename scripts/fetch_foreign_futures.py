"""外資台指期（臺股期貨）未平倉——總經導航「外資空單」卡。

## 資料源（為什麼不用 OpenAPI 當主力）

TAIFEX OpenAPI `MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate`
**只回最新一天**（帶 `date` 參數無效，實測），要自己每天累加、漏一天就補不回來。

所以主力改用 TAIFEX 網站「期貨三大法人-區分各期貨契約」的 **CSV 下載**
（`futContractsDateDown`，POST 日期區間 + `commodityId=TXF`，編碼 Big5/MS950，單次區間實測
3 個月可用）：**每次跑都重抓近 N 天、upsert**——漏跑自癒、首次跑自動回補歷史，
不需要「前一天一定要有跑」的假設。CSV 掛了才退回 OpenAPI 抓最新一天。

## 欄位（CSV 位置，header 共 15 欄）

0 日期｜1 商品名稱｜2 身份別｜…｜9 多方未平倉口數｜11 空方未平倉口數｜13 多空未平倉口數淨額。
只留身份別「外資及陸資」、商品「臺股期貨」（大台）。

用法：
    python scripts/fetch_foreign_futures.py
"""
from __future__ import annotations

import csv
import io
import json
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

CSV_URL = "https://www.taifex.com.tw/cht/3/futContractsDateDown"
API_URL = ("https://openapi.taifex.com.tw/v1/"
           "MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate")
OUT = Path(__file__).resolve().parents[1] / "data" / "reference" / "foreign_futures.parquet"
IDENTITY = "外資及陸資"
PRODUCT = "臺股期貨"
BACKFILL_DAYS = 90     # 首次（沒有檔案）回補；TAIFEX 單次區間上限約 3 個月，95 天會回錯誤頁
REFRESH_DAYS = 14      # 平時每次重抓近 N 天（自癒漏跑）
UA = {"User-Agent": "Mozilla/5.0"}


def _num(x: str) -> int:
    return int(str(x).replace(",", "").strip())


def parse_csv(text: str) -> list[dict]:
    """CSV 全文 → `[{date, long_oi, short_oi, net_oi}]`（只取外資及陸資×臺股期貨）。"""
    rows = list(csv.reader(io.StringIO(text)))
    out = []
    for r in rows[1:]:
        if len(r) < 14 or r[2].strip() != IDENTITY or r[1].strip() != PRODUCT:
            continue
        rec = {"date": pd.Timestamp(r[0].strip().replace("/", "-")),
               "long_oi": _num(r[9]), "short_oi": _num(r[11]), "net_oi": _num(r[13])}
        if rec["long_oi"] - rec["short_oi"] != rec["net_oi"]:     # 欄位錯位／格式改了 → 不收
            print(f"::warning::{rec['date'].date()} 多−空≠淨額，略過：{rec}")
            continue
        out.append(rec)
    return out


def fetch_csv(start: date, end: date) -> list[dict]:
    body = urllib.parse.urlencode({
        "queryStartDate": start.strftime("%Y/%m/%d"),
        "queryEndDate": end.strftime("%Y/%m/%d"),
        "commodityId": "TXF"}).encode()
    req = urllib.request.Request(CSV_URL, data=body, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("cp950", errors="replace")
    return parse_csv(text)


def fetch_api_latest() -> list[dict]:
    req = urllib.request.Request(API_URL, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
    out = []
    for r in rows:
        if r.get("ContractCode", "").strip() != PRODUCT or r.get("Item", "").strip() != IDENTITY:
            continue
        lo, sh, ne = (_num(r["OpenInterest(Long)"]), _num(r["OpenInterest(Short)"]),
                      _num(r["OpenInterest(Net)"]))
        if lo - sh == ne:
            out.append({"date": pd.Timestamp(r["Date"]), "long_oi": lo, "short_oi": sh, "net_oi": ne})
    return out


def main() -> None:
    old = pd.read_parquet(OUT) if OUT.exists() else None
    today = date.today()
    start = today - timedelta(days=REFRESH_DAYS if old is not None else BACKFILL_DAYS)
    # ⚠️ 結束日超過 TAIFEX 最新資料日（例如今天還沒公布／週末）會回錯誤頁而不是空表，
    #    所以從今天起往前退幾天重試（傍晚班可能已有當日資料），第一個有資料的就用（2026-10-03 實測踩到）。
    recs, src = [], "API"
    for back in (0, 1, 2, 3, 4):
        end = today - timedelta(days=back)
        try:
            recs = fetch_csv(start, end)
        except Exception as e:  # noqa: BLE001
            print(f"::warning::CSV 抓取失敗（{type(e).__name__}: {e}）——退回 OpenAPI 最新一天")
            break
        if recs:
            src = "CSV"
            break
    if not recs:
        try:
            recs = fetch_api_latest()
            src = "API"
        except Exception as e:  # noqa: BLE001
            print(f"::warning::OpenAPI 也失敗：{type(e).__name__}: {e}")
    if not recs:
        print("⚠️ 這次沒抓到外資台指期資料（假日或 TAIFEX 還沒更新）")
        return
    new = pd.DataFrame.from_records(recs)
    comb = new if old is None else pd.concat([old, new], ignore_index=True)
    comb = (comb.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    comb.to_parquet(OUT, index=False)
    last = comb.iloc[-1]
    print(f"[{src}] 外資臺股期貨 {last['date'].date()} 空 {last['short_oi']:,} 口 · 淨 {last['net_oi']:,} 口"
          f"（累積 {len(comb)} 天）→ {OUT}")


if __name__ == "__main__":
    main()
