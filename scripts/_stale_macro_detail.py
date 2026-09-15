"""給 global_macro.yml「部分過期才告警」步驟用：印出人看得懂的過期明細。

抽成獨立檔是因為多行 python -c 直接寫進 YAML 的 `run: |` 區塊很容易因為
縮排跟 shell 引號互相打架（2026-09-15 就親自撞過一次：內文縮排一旦跟區塊
基準縮排對不齊，GitHub 會整份 workflow 解析失敗，連 workflow_dispatch 都
會被忽略且不會有任何肉眼可見的錯誤訊息）。
"""
from __future__ import annotations

import json
from pathlib import Path

META = Path(__file__).resolve().parents[1] / "data" / "reference" / "global_macro_meta.json"


def main() -> None:
    m = json.loads(META.read_text(encoding="utf-8"))
    for s in m.get("stale", []):
        print(f"  {s['symbol']}（{s['name']}）落後 {s['lag_days']} 天，最新只到 {s['latest']}")


if __name__ == "__main__":
    main()
