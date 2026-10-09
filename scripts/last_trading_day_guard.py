"""「當週最後交易日」守門：自建上游收集改成每週一次，只在當週最後一個交易日跑（使用者 2026-10-06 決定）。

排程每個平日 23:58（台北）都會觸發，這支判斷「今天是不是當週最後一個交易日」：
  - 是 → 輸出 `run=true`，後面的收集步驟照跑（一次補整週，收集器本來就會補近 14 天缺的）
  - 否 → `run=false`，後面全部跳過（只花幾秒）
手動觸發（workflow_dispatch）一律 `run=true`。

休市日來源：證交所 OpenAPI `holidaySchedule`（官方 OGDL；回傳只含當年度的休市／開始交易／最後交易日）。
**抓不到或解析不出來 → fail-open（`run=true`）**：寧可多跑一次，也不要整週漏掉。
颱風假等臨時休市不在預排表裡：那天若剛好是週五，守門會誤以為它是交易日，但收集器下一週的 14 天窗口會補回，不會留洞。

用法：
    python scripts/last_trading_day_guard.py            # 寫 GITHUB_OUTPUT 的 run=true|false
    python scripts/last_trading_day_guard.py --date 2026-10-08   # 模擬某天（除錯）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

URL = "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"
# 指定一定要跑的日子（不論是不是當週最後交易日）；平時留空。
FORCE_RUN_DATES: set[date] = set()
# 排程（10/7 前 cron 為 23:59、之後 23:58）常被 GitHub 延遲、甚至跨過午夜（2026-10-06 實測延遲約 5 小時，凌晨 04:47 才觸發，被誤判成「10-07 不是最後交易日」而漏收）。
# 所以台北時間這個鐘點以前觸發的排程（實測本 repo 各排程常延遲 2～9 小時，最長 8.8 小時；下一班深夜 23:58 還遠，中午前的都屬於前一晚那班），視為「前一天深夜那班」，用前一天的日期判斷。
LATE_CUTOFF_HOUR = 12
OPEN_MARKERS = ("開始交易日", "最後交易日")      # 名稱含這些的是「有交易」的日子（春節前最後交易日等），不是休市


def _roc(s: str) -> date:
    s = str(s).strip()
    return date(int(s[:-4]) + 1911, int(s[-4:-2]), int(s[-2:]))


def closed_dates(rows: list[dict]) -> set[date]:
    """官方 holidaySchedule 的列 → 休市日集合（排除「開始交易日」「最後交易日」）。"""
    out: set[date] = set()
    for r in rows:
        try:
            if any(m in str(r.get("Name", "")) for m in OPEN_MARKERS):
                continue
            out.add(_roc(r["Date"]))
        except (KeyError, ValueError):
            continue
    return out


def is_trading_day(d: date, closed: set[date]) -> bool:
    return d.weekday() < 5 and d not in closed


def is_last_trading_day_of_week(today: date, closed: set[date]) -> bool:
    """今天是交易日、且今天之後到本週日之間沒有任何交易日。"""
    if not is_trading_day(today, closed):
        return False
    d = today + timedelta(days=1)
    while d.weekday() != 0:                 # 走到下週一為止
        if is_trading_day(d, closed):
            return False
        d += timedelta(days=1)
    return True


def fetch_closed() -> set[date] | None:
    try:
        import requests  # noqa: PLC0415
        r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list) or not rows:
            return None
        return closed_dates(rows)
    except Exception as e:      # noqa: BLE001
        print(f"::warning::抓不到證交所休市日表（{str(e)[:100]}）——fail-open，照常執行", file=sys.stderr)
        return None


def effective_date(now: datetime, event: str = "schedule") -> date:
    """排程班次要判斷的「日期」：延遲跨過午夜（台北 00:00～LATE_CUTOFF_HOUR）→ 算前一天；手動觸發不受影響。"""
    if event == "schedule" and now.hour < LATE_CUTOFF_HOUR:
        return now.date() - timedelta(days=1)
    return now.date()


def published_needs_repair(manifest: dict | None, today: date, closed: set[date]) -> bool:
    """已發佈的自建資料包 manifest 有洞（gaps 非空），或完整日落後「今天之前最近一個交易日」≥1 個交易日。
    updatePRD-opus §11 R2：週收集一週只跑一次，洞不處理會卡到下週五；這裡讓那天當晚多收一次（不加 cron、不改頻率）。"""
    if not manifest:
        return False
    if manifest.get("gaps"):
        return True
    try:
        cday = date.fromisoformat(str(manifest.get("complete_day")))
    except ValueError:
        return False
    d = today - timedelta(days=1)
    while not is_trading_day(d, closed) and d > cday:       # 今天之前最近的交易日
        d -= timedelta(days=1)
    return cday < d


def decide(today: date, closed: set[date] | None, event: str = "schedule",
           published: dict | None = None) -> tuple[bool, str]:
    if event == "workflow_dispatch":
        return True, "手動觸發，一律執行"
    if today in FORCE_RUN_DATES:
        return True, f"{today} 是指定補跑日，執行"
    if closed is None:
        return True, "沒有休市日表，fail-open 執行"
    if is_trading_day(today, closed) and published_needs_repair(published, today, closed):
        return True, f"{today} 自建資料包有洞或落後，當晚補收"
    if is_last_trading_day_of_week(today, closed):
        return True, f"{today}（週{'一二三四五六日'[today.weekday()]}）是當週最後交易日，執行"
    if not is_trading_day(today, closed):
        return False, f"{today} 休市，略過"
    return False, f"{today} 不是當週最後交易日，略過"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD（預設今天，台北時區）")
    a = ap.parse_args(argv)
    event = os.environ.get("EVENT_NAME", "schedule")
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    today = date.fromisoformat(a.date) if a.date else effective_date(now, event)
    if not a.date and today != now.date():
        print(f"[guard] 現在台北 {now:%Y-%m-%d %H:%M}，排程延遲跨午夜 → 以前一天 {today} 判斷")
    published = None
    pm = os.environ.get("PUBLISHED_MANIFEST")
    if pm and os.path.exists(pm):
        try:
            with open(pm, encoding="utf-8") as f:
                published = json.load(f)
        except (OSError, ValueError):
            published = None        # 讀不到＝不啟動自癒，維持原判斷
    run, why = decide(today, fetch_closed(), event, published)
    print(f"[guard] run={'true' if run else 'false'}：{why}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"run={'true' if run else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
