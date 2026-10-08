"""自建資料包停滯紅燈：已發佈 zip 的完整日落後預期交易日太多 → exit 1（workflow 變紅）。

為什麼需要：沒有設告警 webhook，workflow 變紅是唯一會被看到的訊號。資料停滯（官方改版回「沒有資料」、
price_target 算錯日、某來源整個壞掉）時各步驟都是「正常的沒有新資料」→ 全綠，完整日停住、併入雜湊不變、datapack 直接跳過。

判準：完整日之後、今天（台北）之前的交易日數 ≥ LAG_ERROR（預設 2）→ 紅；＝1 → 只警告（例：長假後第一個交易日）。
交易日＝平日且不在證交所休市表；休市表抓不到（None）時只排除週末（fail-open：長假期間可能多報警告，不會漏報）。

    python scripts/selfhost_freshness.py --manifest published/merge_manifest.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

LAG_ERROR = 2


def lag_trading_days(complete_day: date, today: date, closed: set[date] | None) -> int:
    """完整日之後、今天之前（不含兩端）的交易日數。"""
    n, d = 0, complete_day + timedelta(days=1)
    while d < today:
        if d.weekday() < 5 and not (closed and d in closed):
            n += 1
        d += timedelta(days=1)
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    a = ap.parse_args(argv)
    p = Path(a.manifest)
    if not p.exists():
        print("::warning::還沒有已發佈的 manifest（首次發佈前），略過新鮮度檢查", file=sys.stderr)
        return 0
    cday = date.fromisoformat(json.loads(p.read_text(encoding="utf-8"))["complete_day"])
    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import last_trading_day_guard as g  # noqa: PLC0415
        closed = g.fetch_closed()
    except Exception:       # noqa: BLE001
        closed = None
    lag = lag_trading_days(cday, today, closed)
    print(f"[fresh] 已發佈完整日 {cday}、今天 {today}、落後 {lag} 個交易日")
    if lag >= LAG_ERROR:
        print(f"::error::自建資料包停滯：完整日 {cday} 落後 {lag} 個交易日（≥{LAG_ERROR}）——查日線／法人／融資哪一項沒進來"
              "（openapi_fetch_log、selfhost_status.json、merge_manifest 的 last_dates）", file=sys.stderr)
        return 1
    if lag == 1:
        print(f"::warning::自建資料包完整日 {cday} 落後 1 個交易日", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
