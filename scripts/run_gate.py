"""自動班開跑前的新鮮度閘門 CLI（判斷本體在 reference/run_gate.py）。

    python scripts/run_gate.py --workflow global_macro

讀環境變數 GITHUB_EVENT_NAME、GATE_SOURCE；輸出 `run=true|false` 到 $GITHUB_OUTPUT，
理由印 stdout 並附加到 $GITHUB_STEP_SUMMARY。任何例外 → run=true（fail-open）：
閘門只能讓班「少跑」，不能害它「不跑」。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reference import run_gate as rg  # noqa: E402

REF = ROOT / "data" / "reference"


def _read_json(p: Path) -> dict | None:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _max_date(p: Path):
    import pandas as pd
    return pd.to_datetime(pd.read_parquet(p, columns=["date"])["date"]).max().date()


def load_fresh(workflow: str, now_utc: datetime) -> tuple[bool, str] | None:
    if workflow == "global_macro":
        import pandas as pd
        from scripts.fetch_global_macro import ALL_SYMBOLS
        meta = _read_json(REF / "global_macro_meta.json")
        pq = REF / "global_macro.parquet"
        symbols = set(pd.read_parquet(pq, columns=["symbol"])["symbol"]) if pq.exists() else None
        tx_meta = _read_json(REF / "tx_futures_meta.json")
        return rg.macro_fresh(meta, symbols, tx_meta, set(ALL_SYMBOLS), now_utc)
    if workflow == "chip_flow_evening":
        dates = {}
        for k in ("foreign_futures", "inst_flow"):
            p = REF / f"{k}.parquet"
            dates[k] = _max_date(p) if p.exists() else None
        return rg.chip_fresh(dates, now_utc)
    return None


def load_last_dispatch_success(workflow: str) -> datetime | None:
    r = subprocess.run(
        ["gh", "run", "list", "--workflow", f"{workflow}.yml", "--event", "workflow_dispatch",
         "--status", "success", "--limit", "1", "--json", "createdAt"],
        capture_output=True, text=True, timeout=60, check=True)
    rows = json.loads(r.stdout or "[]")
    if not rows:
        return None
    return datetime.fromisoformat(rows[0]["createdAt"].replace("Z", "+00:00")).astimezone(timezone.utc)


def evaluate(workflow: str, event: str, source: str | None, now_utc: datetime) -> tuple[bool, str]:
    fresh = last = None
    if workflow in ("global_macro", "chip_flow_evening"):
        fresh = load_fresh(workflow, now_utc)
    elif event == "schedule":
        last = load_last_dispatch_success(workflow)
    return rg.decide(workflow, event, source or None, now_utc,
                     fresh=fresh, last_dispatch_success_utc=last)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", required=True)
    a = ap.parse_args(argv)
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    source = os.environ.get("GATE_SOURCE") or None
    now = datetime.now(timezone.utc)
    try:
        run, reason = evaluate(a.workflow, event, source, now)
    except Exception as e:  # noqa: BLE001  fail-open
        run, reason = True, f"gate 出錯，照跑：{e}"
    line = f"{'▶ 執行' if run else '⏭ 跳過'}（{a.workflow}／{event or '-'}／{source or '-'}）：{reason}"
    print(line)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"run={'true' if run else 'false'}\n")
    else:
        print(f"run={'true' if run else 'false'}")
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
