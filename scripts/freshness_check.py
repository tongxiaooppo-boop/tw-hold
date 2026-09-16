"""開盤前新鮮度守門的 CLI——2026-09-16 因「常被問為什麼沒更新、卻很難找原因」而加。

只做一件事：把「資料到底新不新鮮」跟「為什麼不新鮮」一次講清楚，讓 heartbeat.yml
的告警訊息本身就是診斷起點，不用再回頭挖 workflow log。

判斷本體在 `reference/freshness.py`（app 表頭徽章也吃同一份，容忍天數只有一處）——
這支只是薄 CLI 包裝。

用法：
    python scripts/freshness_check.py            # 印報告，有 stale 項目 exit 1
    python scripts/freshness_check.py --json      # 只印 JSON（給 workflow 組告警訊息用）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reference.freshness import run  # noqa: E402


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
