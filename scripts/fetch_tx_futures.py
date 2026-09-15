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

## 排程

不用另開 workflow——TAIFEX 夜盤 05:00 收盤，跟 `global_macro.yml`（台北 06:00
跑）的時間點本來就對得上，直接掛在同一個 job 裡當一個額外步驟。

⚠️ **這支 API 只回傳「目前最新一天」，`date` 查詢參數是裝飾用的**（實測帶任何
日期都回傳同一天）——代表**沒有回補機制**：如果 06:00 那次抓取時夜盤資料剛好
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
        else float(r["SettlementPrice"]),
    }


def main() -> None:
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

    for rec in records:
        label = "日盤" if rec["session"] == "day" else "夜盤"
        print(f"  {rec['date'].date()} {label}（{rec['contract_month']}）收 {rec['last']}")
    print(f"寫入 {OUT}：累積 {len(combined)} 筆")

    fetched_date = records[0]["date"].strftime("%Y-%m-%d")
    sessions = {r["session"] for r in records}
    missing_night = "night" not in sessions
    if missing_night:
        print(f"::warning::{fetched_date} 沒有夜盤資料——這支 API 沒有回補機制，"
              "這天的夜盤收盤可能永久遺失，等隔天正常有資料就沒事，連續發生才需要人工介入")
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
