"""給 global_macro.yml「台指期夜盤缺失才告警」步驟用：印出人看得懂的訊息。

抽成獨立檔的理由跟 `_stale_macro_detail.py` 一樣——多行 python -c 直接寫進
YAML 的 `run: |` 區塊，縮排一旦跟區塊基準對不齊，GitHub 會整份 workflow
解析失敗且沒有肉眼可見的錯誤（2026-09-15 撞過）。
"""
from __future__ import annotations

import json
from pathlib import Path

META = Path(__file__).resolve().parents[1] / "data" / "reference" / "tx_futures_meta.json"


def main() -> None:
    m = json.loads(META.read_text(encoding="utf-8"))
    date = m.get("date") or "（整批沒抓到）"
    note = m.get("note") or ""
    print(f"  {date}　{note}")


if __name__ == "__main__":
    main()
