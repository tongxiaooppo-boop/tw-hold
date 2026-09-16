"""開盤前新鮮度守門——2026-09-16 因「常被問為什麼沒更新、卻很難找原因」而加。

只做一件事：把「資料到底新不新鮮」跟「為什麼不新鮮」一次講清楚，讓 heartbeat.yml
的告警訊息本身就是診斷起點，不用再回頭挖 workflow log。

檢查兩份台股相關資料各自的「最後一筆日期」是否跟得上最近一個預期交易日：
  - data/derived/_meta.json 的 trading_date（三清單／個股查詢底層 bundle 的日期戳）
  - data/reference/index_006201.parquet 的最後一筆日期（總經導航上櫃卡）

「預期交易日」只用平日近似（不查行事曆），對國定假日連假會多留 2 天緩衝，
避免連假期間誤報——見 _expected_trading_date 的 SLACK_DAYS。

用法：
    python scripts/freshness_check.py            # 印報告，有 stale 項目 exit 1
    python scripts/freshness_check.py --json      # 只印 JSON（給 workflow 組告警訊息用）
"""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SLACK_DAYS = 2  # 連假／國定假日的緩衝天數，不查行事曆，用寬容度換簡單


def _expected_trading_date(today: date) -> date:
    """今天日期往前找最近一個平日（不管國定假日，只避開六日）。"""
    d = today - timedelta(days=1)
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d


def _check_one(label: str, last_date: date | None, today: date) -> dict:
    expected = _expected_trading_date(today)
    if last_date is None:
        return {"label": label, "ok": False, "reason": "找不到資料／檔案不存在",
                 "last_date": None, "expected": expected.isoformat()}
    gap = (expected - last_date).days
    ok = gap <= SLACK_DAYS
    return {
        "label": label, "ok": ok, "last_date": last_date.isoformat(),
        "expected": expected.isoformat(), "gap_days": gap,
        "reason": None if ok else f"落後預期交易日 {gap} 天（緩衝 {SLACK_DAYS} 天）",
    }


def _meta_trading_date() -> date | None:
    p = REPO / "data" / "derived" / "_meta.json"
    if not p.exists():
        return None
    try:
        td = json.loads(p.read_text(encoding="utf-8")).get("trading_date")
        return date.fromisoformat(td) if td else None
    except (ValueError, json.JSONDecodeError):
        return None


def _parquet_last_date(p: Path) -> date | None:
    if not p.exists():
        return None
    try:
        import pandas as pd  # noqa: PLC0415
        d = pd.read_parquet(p, columns=["date"])
        if d.empty:
            return None
        return pd.to_datetime(d["date"]).max().date()
    except Exception:
        return None


def run(today: date | None = None) -> dict:
    today = today or date.today()
    ref = REPO / "data" / "reference"
    checks = [
        _check_one("三清單／個股查詢（bundle trading_date）", _meta_trading_date(), today),
        # 0050／006201 2026-09-16 起都改讀各自獨立落地的小檔（見
        # reference/index_proxy.py、scripts/promote_index_0050.py），不再跟
        # bundle trading_date 共用同一個時鐘，要分開檢查。
        _check_one("上市代理 0050（總經導航）", _parquet_last_date(ref / "index_0050.parquet"), today),
        _check_one("上櫃代理 006201（總經導航）", _parquet_last_date(ref / "index_006201.parquet"), today),
    ]
    return {"today": today.isoformat(), "checks": checks,
            "all_ok": all(c["ok"] for c in checks)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result = run()
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        for c in result["checks"]:
            status = "OK" if c["ok"] else "STALE"
            print(f"[{status}] {c['label']}：最後 {c.get('last_date')}，"
                  f"預期交易日 {c['expected']}"
                  + (f"　→ {c['reason']}" if c["reason"] else ""))
    return 0 if result["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
