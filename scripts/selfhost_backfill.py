"""自建上游一次性全量回補（依序、可續跑、各步失敗不擋下一步）。

為什麼要序列化：TWSE／TPEx 對連續請求會擋（約 3 次／5 秒），平行跑會互相拖累。
每支收集器都「只補檔案裡缺的」，所以中斷後直接再跑一次就是續跑。

    python scripts/selfhost_backfill.py            # 全部
    python scripts/selfhost_backfill.py --only raw # 只跑某一步（raw-recent / events / raw / chips-recent / chips-old）

日誌：data/selfhost/backfill.log
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "data" / "selfhost" / "backfill.log"
PY = sys.executable
TODAY = date.today().isoformat()

STEPS = {
    # 近期優先：讓驗證（接縫偵測、還原對帳）不必等全歷史回補完
    "raw-recent": [PY, "scripts/selfhost_raw_prices.py", "--start", "2026-05-04", "--end", TODAY],
    "events": [PY, "scripts/selfhost_events.py", "--official", "2015-01-01"],
    "raw": [PY, "scripts/selfhost_raw_prices.py", "--start", "2015-01-05", "--end", TODAY],
    "chips-recent": [PY, "scripts/selfhost_chips.py", "--start", "2024-01-01", "--end", TODAY],
    "chips-old": [PY, "scripts/selfhost_chips.py", "--start", "2015-01-05", "--end", "2023-12-31"],
}


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=list(STEPS))
    a = ap.parse_args()
    for name, cmd in STEPS.items():
        if a.only and name != a.only:
            continue
        log(f"開始 {name}：{' '.join(cmd[1:])}")
        t0 = time.time()
        with open(LOG, "a", encoding="utf-8") as f:
            rc = subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                                env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}).returncode
        log(f"結束 {name}：exit {rc}，{int(time.time() - t0)} 秒")
    log("全部步驟結束")
    return 0


if __name__ == "__main__":
    sys.exit(main())
