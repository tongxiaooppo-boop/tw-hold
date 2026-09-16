"""資料新鮮度判斷——「資料到底新不新鮮」跟「為什麼不新鮮」的共用本體。

兩個呼叫端共用同一份容忍天數，不要兩邊各自維護一套：
  - `scripts/freshness_check.py`：CI（`heartbeat.yml` 開盤前守門）的薄 CLI 包裝
  - `app/streamlit_app.py`：表頭右側的新鮮度徽章

2026-09-16 從 `scripts/freshness_check.py` 搬過來（原本 app 執行期 import
`scripts/`，而那個目錄定位是 CI/CLI 工具、沒有 `__init__.py`，靠 namespace
package 硬 import——只要有人在 scripts/ 下任何一支加了 module-level 的重
依賴，就會被拖進 app 冷啟路徑）。

檢查三份資料各自的「最後一筆日期」跟不跟得上最近一個預期交易日：
  - `data/derived/_meta.json` 的 trading_date（三清單／個股查詢底層 bundle）
  - `data/reference/index_0050.parquet`（總經導航上市卡）
  - `data/reference/index_006201.parquet`（總經導航上櫃卡）

後兩者 2026-09-16 起各自獨立落地，**不再跟 bundle 共用同一個時鐘**，要分開檢查。

「預期交易日」只用平日近似（不查行事曆），對國定假日連假多留 `SLACK_DAYS` 天緩衝。
⚠️ 已知限制：蓋不住農曆春節（9~10 天），那段期間每個平日都會誤報——用寬容度換
「不必維護一張每年會過期的假日表、也不必為了一個告警功能接外部行事曆 API」。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SLACK_DAYS = 2  # 連假／國定假日的緩衝天數，不查行事曆，用寬容度換簡單


def expected_trading_date(today: date) -> date:
    """今天日期往前找最近一個平日（不管國定假日，只避開六日）。"""
    d = today - timedelta(days=1)
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d


def check_one(label: str, last_date: date | None, today: date) -> dict:
    expected = expected_trading_date(today)
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


def meta_trading_date() -> date | None:
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
    except Exception:  # noqa: BLE001 — 壞檔等同沒資料，這裡不該把告警本身弄炸
        return None


def run(today: date | None = None) -> dict:
    today = today or date.today()
    ref = REPO / "data" / "reference"
    checks = [
        check_one("三清單／個股查詢（bundle trading_date）", meta_trading_date(), today),
        check_one("上市代理 0050（總經導航）", _parquet_last_date(ref / "index_0050.parquet"), today),
        check_one("上櫃代理 006201（總經導航）", _parquet_last_date(ref / "index_006201.parquet"), today),
    ]
    return {"today": today.isoformat(), "checks": checks,
            "all_ok": all(c["ok"] for c in checks)}
