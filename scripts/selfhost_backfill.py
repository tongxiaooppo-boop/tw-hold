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

# 平行回補：TWSE、TPEx 是不同主機、限流分開，各跑一條線（互不拖累；同一主機內仍保持 ~2 秒間隔）。
# 每條線依序：實價 → 近兩年法人融資券 → 2015–2023 法人融資券。完成後跑 selfhost_merge.py。
def lane_steps(m: str) -> dict:
    return {
        f"raw-{m}": [PY, "scripts/selfhost_raw_prices.py", "--market", m, "--start", "2015-01-05", "--end", TODAY],
        f"chips-recent-{m}": [PY, "scripts/selfhost_chips.py", "--markets", m, "--start", "2024-01-01", "--end", TODAY],
        f"chips-old-{m}": [PY, "scripts/selfhost_chips.py", "--markets", m, "--start", "2015-01-05", "--end", "2023-12-31"],
    }


LANES = {"twse": lane_steps("TW"), "tpex": lane_steps("TWO")}

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
    ap.add_argument("--lane", choices=list(LANES), help="平行回補：只跑單一主機的線（twse／tpex）")
    a = ap.parse_args()
    steps = LANES[a.lane] if a.lane else STEPS
    for name, cmd in steps.items():
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
