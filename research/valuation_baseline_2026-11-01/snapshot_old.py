"""舊版價格卡片基準快照（2026-11-01）：對樣本股跑現行 va.estimate()，
各存「停用版（線上現況）」與「未停用版（BUY_RANGE_PAUSED=False，買進區間＋成長價）」兩份。
新版做完後，用同一批樣本比較。只讀資料，不改任何程式。"""
import json, sys, importlib
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "app"))
import pandas as pd
import build_revenue_watch as brw
brw._install_preloaded_reader()
import bundle_data as bd
import valuation as va
from factors.factors import quarterly_factors

SAMPLES = ["2330","2317","2603","2609","3661","6669","1815","2881","2377","3717",
           "2454","8422","3443","2002","2353","1802","2412","1216","2308","3008"]
OUT = Path(__file__).parent

def run(code):
    qf = quarterly_factors(bd.financials(code))
    return va.estimate(qf, bd.revenue(code), bd.prices(code), bd.per_history(code))

def safe(v):
    return brw._json_safe(v)

for tag, paused in (("paused", True), ("unpaused", False)):
    va.BUY_RANGE_PAUSED = paused
    res = {}
    for c in SAMPLES:
        try:
            res[c] = safe(run(c))
        except Exception as e:  # noqa
            res[c] = {"ok": False, "reason": f"例外：{e!r}"[:200]}
    (OUT / f"old_snapshot_{tag}.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(tag, sum(1 for r in res.values() if r.get("ok")), "/", len(res))
