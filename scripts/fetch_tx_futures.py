"""台指期（TX）近月合約日盤／夜盤收盤——總經導航「加上台股期貨夜盤收盤指數」。

## 資料源

TAIFEX 官方 OpenAPI `https://openapi.taifex.com.tw/v1/DailyMarketReportFut`——
免金鑰、免登入，JSON。這支只回傳「目前最新一天」的全期貨市場行情，不是歷史
序列，所以要像 `tdcc.py` 的週快照一樣**每天呼叫、自己累加成長表**。

每個契約月份（如 `202609`）在同一天會有兩列，用 `TradingSession` 區分：
「一般」= 日盤（13:45 收盤，`SettlementPrice` 有值）；「盤後」= 夜盤（跨夜到
隔天 05:00，`Last` 就是夜盤最後成交價，`SettlementPrice` 是 NULL——夜盤沒有
獨立結算價，隔天日盤收盤才會重新結算）。

近月合約：`ContractMonth(Week)` 有些是價差單的複合月份（如 `202609/202610`），
只留純六碼月份，取最小值當近月（TAIFEX 回傳順序本身就是近到遠，但排序更保險）。

## 主來源改為網站「每日行情下載」CSV（2026-10-16）

`POST https://www.taifex.com.tw/cht/3/futDataDown`（down_type=1、commodity_id=TX、起訖日）回 Big5 CSV，
**可指定日期區間（能回補）**，而且**夜盤一結束就有**：實測 10/16 09:25 已有「2026/10/16 盤後」
（＝10/15 15:00→10/16 05:00），OpenAPI 同時間還停在 10/15。OpenAPI 要等當天日盤收盤後才換日，
早上只拿得到「前一晚之前那一場」夜盤，總經頁的夜盤就失去意義（使用者 2026-10-16 指出）。
OpenAPI 保留當備援（CSV 失敗才用）。

⚠️ **夜盤歸屬下一個交易日**：交易日 D 的「盤後」＝前一交易日 15:00 → D 05:00，發生在 D 日盤之前。
CSV 每次抓近 `BACKFILL_DAYS` 天，漏抓的日子下一輪自動補回。

## 排程

不用另開 workflow——TAIFEX 夜盤 05:00 收盤，跟 `global_macro.yml`（台北 06:37
跑）的時間點本來就對得上，直接掛在同一個 job 裡當一個額外步驟。

⚠️ **這支 API 只回傳「目前最新一天」，`date` 查詢參數是裝飾用的**（實測帶任何
日期都回傳同一天）——代表**沒有回補機制**：如果 06:37 那次抓取時夜盤資料剛好
還沒發布完成，當天的夜盤收盤就永久遺失，隔天再抓到的已經是下一個交易日。
`main()` 因此會在夜盤缺席時寫一份 `tx_futures_meta.json` 給 workflow 告警用
（2026-09-15 使用者要求「隔天更新務必帶入新資料」，這是唯一做得到的保證：
抓不到不會沉默，會立刻被看見）。

用法：
    python scripts/fetch_tx_futures.py
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

URL = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
CSV_URL = "https://www.taifex.com.tw/cht/3/futDataDown"
BACKFILL_DAYS = 10
OUT = Path(__file__).resolve().parents[1] / "data" / "reference" / "tx_futures.parquet"
META_OUT = OUT.with_name("tx_futures_meta.json")

_MONTH_RE = re.compile(r"^\d{6}$")


def fetch_front_month_rows() -> list[dict]:
    """回傳今天 TX 近月合約的日盤／夜盤兩列（原始 API 欄位，字串）。"""
    # 不加 requests 依賴——跟 reference/finmind_client.py 一樣用標準庫（PRD「刻意控依賴」）。
    with urllib.request.urlopen(URL, timeout=20) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
    tx = [r for r in rows if r.get("Contract", "").strip() == "TX"
          and _MONTH_RE.match(r.get("ContractMonth(Week)", ""))]
    if not tx:
        return []
    front = min(r["ContractMonth(Week)"] for r in tx)
    return [r for r in tx if r["ContractMonth(Week)"] == front]


def _num(x: str) -> float | None:
    x = (x or "").strip()
    try:
        return float(x)
    except ValueError:
        return None


def _settle(x: float | None) -> float | None:
    """結算價 ≤ 0 當沒有：最後交易日期交所結算價欄填 0（2026-10-21 10 月合約）。"""
    return x if x is not None and x > 0 else None


def parse_csv(text: str) -> list[dict]:
    """futDataDown 的 CSV → 每個 (交易日, 時段) 的近月 TX 一筆。近月＝同一交易日內最小的純六碼月份。"""
    import csv
    import io
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    head = [h.strip() for h in rows[0]]
    try:
        ix = {k: head.index(k) for k in ("交易日期", "契約", "到期月份(週別)", "收盤價", "結算價", "交易時段")}
    except ValueError:
        return []
    cand = []
    for r in rows[1:]:
        if len(r) <= max(ix.values()) or r[ix["契約"]].strip() != "TX":
            continue
        month = r[ix["到期月份(週別)"]].strip()
        session = {"一般": "day", "盤後": "night"}.get(r[ix["交易時段"]].strip())
        last = _num(r[ix["收盤價"]])
        if not _MONTH_RE.match(month) or session is None or last is None:
            continue
        cand.append({"date": pd.Timestamp(r[ix["交易日期"]].strip().replace("/", "-")), "session": session,
                     "contract_month": month, "last": last, "settlement": _settle(_num(r[ix["結算價"]]))})
    front = {}
    for c in cand:
        front[c["date"]] = min(front.get(c["date"], c["contract_month"]), c["contract_month"])
    return [c for c in cand if c["contract_month"] == front[c["date"]]]


def fetch_csv_records(days: int = BACKFILL_DAYS) -> list[dict]:
    """網站 CSV 抓近 `days` 天（含今天）；任何失敗回 []，由呼叫端退回 OpenAPI。"""
    from urllib.parse import urlencode
    end = pd.Timestamp.now(tz="Asia/Taipei").normalize()
    start = end - pd.Timedelta(days=days)
    body = urlencode({"down_type": "1", "commodity_id": "TX", "commodity_id2": "",
                      "queryStartDate": f"{start:%Y/%m/%d}", "queryEndDate": f"{end:%Y/%m/%d}"}).encode()
    # UA 比照 fetch_foreign_futures（同網站、CI 上抓得到）；自訂 UA 在 runner 上曾逾時（2026-10-16）。
    err = None
    for _ in range(2):
        try:
            req = urllib.request.Request(CSV_URL, data=body, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read()
            return parse_csv(raw.decode("big5", errors="replace"))
        except Exception as e:  # noqa: BLE001
            err = e
    print(f"::warning::期交所 CSV 下載失敗（{type(err).__name__}），改用 OpenAPI 備援")
    return []


def _to_record(r: dict) -> dict | None:
    session = {"一般": "day", "盤後": "night"}.get(r.get("TradingSession", "").strip())
    if session is None:
        return None
    last = r.get("Last", "").strip()
    if not last or last in ("-", "NULL"):
        return None
    return {
        "date": pd.Timestamp(r["Date"]),
        "session": session,
        "contract_month": r["ContractMonth(Week)"],
        "last": float(last),
        "settlement": None if r.get("SettlementPrice") in (None, "", "NULL", "-")
        else _settle(float(r["SettlementPrice"])),
    }


def main() -> None:
    records = fetch_csv_records()
    if not records:
        rows = fetch_front_month_rows()
        records = [rec for r in rows if (rec := _to_record(r)) is not None]
    if not records:
        print("⚠️ 今天沒抓到 TX 近月合約資料（假日或 TAIFEX 還沒更新）")
        _write_meta(None, missing_night=True, note="整批沒抓到")
        return
    new = pd.DataFrame.from_records(records)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        old = pd.read_parquet(OUT)
        combined = pd.concat([old, new], ignore_index=True)
        combined = combined.drop_duplicates(subset=["date", "session"], keep="last")
    else:
        combined = new
    combined = combined.sort_values(["date", "session"]).reset_index(drop=True)
    combined.to_parquet(OUT, index=False)

    for rec in sorted(records, key=lambda r: (r["date"], r["session"]))[-4:]:
        label = "日盤" if rec["session"] == "day" else "夜盤"
        print(f"  {rec['date'].date()} {label}（{rec['contract_month']}）收 {rec['last']}")
    print(f"寫入 {OUT}：累積 {len(combined)} 筆")

    fetched_date = max(r["date"] for r in records).strftime("%Y-%m-%d")
    # 最新日盤之前那一晚都沒有夜盤（night 最新日 < day 最新日）才算缺。CSV 早上會多一筆「下一交易日的盤後」，那是正常的。
    last_day = max((r["date"] for r in records if r["session"] == "day"), default=None)
    last_night = max((r["date"] for r in records if r["session"] == "night"), default=None)
    missing_night = last_night is None or (last_day is not None and last_night < last_day)
    if missing_night:
        print(f"::warning::{fetched_date} 最新日盤之前那一晚沒有夜盤資料——CSV 會回補近 {BACKFILL_DAYS} 天，"
              "下一輪通常會補上；走的是 OpenAPI 備援時沒有回補，連續發生才需要人工介入")
    _write_meta(fetched_date, missing_night, note="" if not missing_night else "只有日盤")


def _write_meta(date: str | None, missing_night: bool, note: str) -> None:
    META_OUT.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "date": date,
        "missing_night": missing_night,
        "note": note,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
