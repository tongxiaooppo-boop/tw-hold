"""screen 結果 → `data/derived/*_list.json`（Streamlit app 只讀這裡）。

M0.5。價值 / 定存兩清單來自 `build_factors.screen_all()`；長波段（候選池）是 M1，
這裡先寫空 placeholder。

「新進 / 移除」**讀上一期 JSON 的 holdings 比對**，不靠 git diff（PRD §3.2）。
移除 = 掉出清單 = 出場訊號（每期揭露）。

用法：
    python build_lists.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from build_factors import DERIVED, screen_all

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TOP_N = 30

#: 每個清單在 holdings 裡揭露的欄位（存在才帶）。
VALUE_COLS = ["value_score", "f_score", "roe", "norm_pe", "norm_ey", "fcf_yield",
              "ev_ebit", "net_cash_to_mktcap", "gross_margin", "reject_reason"]
DEPOSIT_COLS = ["safety_score", "div_years", "last_cash_dividend", "fcf_yield",
                "ann_vol", "roe", "payout_ratio_ttm", "cyclical_penalty",
                "debt_ratio", "reject_reason"]


def _rows(df: pd.DataFrame, score: str, cols: list[str]) -> list[dict]:
    sub = df[df["passes"] & df["in_top500"]].sort_values(score, ascending=False).head(TOP_N)
    keep = ["ticker"] + [c for c in cols if c in sub.columns]
    out = []
    for _, r in sub[keep].iterrows():
        d = {}
        for c in keep:
            v = r[c]
            if isinstance(v, float):
                d[c] = None if pd.isna(v) else round(v, 4)
            else:
                d[c] = None if pd.isna(v) else v
        out.append(d)
    return out


def _diff(name: str, current: list[dict]) -> dict:
    prev_p = DERIVED / f"{name}_list.json"
    prev_tk: set[str] = set()
    if prev_p.exists():
        try:
            prev_tk = {h["ticker"] for h in json.loads(prev_p.read_text(encoding="utf-8")).get("holdings", [])}
        except Exception:
            pass
    cur_tk = {h["ticker"] for h in current}
    return {"added": sorted(cur_tk - prev_tk), "removed": sorted(prev_tk - cur_tk)}


def _write(name: str, payload: dict) -> None:
    (DERIVED / f"{name}_list.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → data/derived/{name}_list.json　({len(payload.get('holdings', []))} 檔)")


def main() -> int:
    r = screen_all()
    ctx = r["context"]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = {
        "trading_date": ctx["trading_date"],
        "rebuilt_at": now,
        "bundle_schema": ctx["bundle_schema"],
        "universe_filtered": ctx["universe_filtered"],
        "note": ctx["universe_note"],
        "u1b_pending": not ctx["has_prices"],
    }
    DERIVED.mkdir(parents=True, exist_ok=True)

    val_rows = _rows(r["value"], "value_score", VALUE_COLS)
    dep_rows = _rows(r["deposit"], "safety_score", DEPOSIT_COLS)

    _write("value", {"_meta": meta, "holdings": val_rows, "changes": _diff("value", val_rows)})
    _write("deposit", {"_meta": {**meta, "warning":
           "U3 universe 修正前定存線偏誤（PRD §7 / M0_HANDOFF §3）"},
           "holdings": dep_rows, "changes": _diff("deposit", dep_rows)})
    _write("swing", {"_meta": meta, "holdings": [], "changes": {"added": [], "removed": []},
           "note": "M1 主動選股候選池未實作（PLAN §M1，前置 M0b）"})

    (DERIVED / "_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → data/derived/_meta.json　trading_date {meta['trading_date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
