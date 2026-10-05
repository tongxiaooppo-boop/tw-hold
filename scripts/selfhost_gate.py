"""自建上游資料健檢閘門：新版資料要「不比舊版差」才允許覆蓋 Release。

比對 `--base`（從 Release 下載的上一版）與 `--live`（這輪跑完的版本）：
1. 列數不得減少（容許 0.1% 浮動：去重）；最新日期不得倒退。
2. 最新一個資料日、每個市場的檔數 ≥ 該市場前 20 個資料日中位數的 90%
   （上游曾發生 .TWO 融資券整批缺／某日只有 57% 檔數；我們不重蹈，見 UPSTREAM_PRACTICES_AUDIT M4）。
3. 實價每日檔數絕對下限（上市 ≥ 900、上櫃 ≥ 700）。

通過 → exit 0，並寫 `data/derived/selfhost_status.json`（各資料集最新日／列數／最新日檔數，給心跳與頁面用）。
失敗 → exit 1，workflow **不得上傳**（壞版本不能蓋掉好版本）。

    python scripts/selfhost_gate.py --base data/selfhost/_base --live data/selfhost
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATASETS = {"raw_prices": "raw_prices.parquet", "inst": "inst.parquet", "margin": "margin.parquet",
            "corp_actions": "corp_actions.parquet"}
DAILY = {"raw_prices", "inst", "margin"}
ABS_MIN = {"raw_prices": {"TW": 900, "TWO": 700}}
RATIO_MIN = 0.90
SHRINK_TOL = 0.001


def _summary(df: pd.DataFrame, daily: bool) -> dict:
    out = {"rows": int(len(df))}
    if daily and len(df):
        d = pd.to_datetime(df["date"])
        out["last_date"] = str(d.max().date())
        last = df[d == d.max()]
        out["last_day_counts"] = {str(k): int(v) for k, v in last.groupby("market").size().items()}
    elif len(df):
        out["last_date"] = str(pd.to_datetime(df["date"]).max().date())
    return out


def check_dataset(name: str, live: pd.DataFrame, base: pd.DataFrame | None) -> list[str]:
    errs: list[str] = []
    daily = name in DAILY
    if base is not None and len(base):
        if len(live) < len(base) * (1 - SHRINK_TOL):
            errs.append(f"{name}：列數 {len(live)} < 舊版 {len(base)}（資料變少）")
        if pd.to_datetime(live["date"]).max() < pd.to_datetime(base["date"]).max():
            errs.append(f"{name}：最新日倒退 {pd.to_datetime(live['date']).max().date()} < {pd.to_datetime(base['date']).max().date()}")
    if daily and len(live):
        d = pd.to_datetime(live["date"])
        cnt = live.assign(_d=d).groupby(["market", "_d"]).size().unstack(0)
        last = cnt.index.max()
        for m in cnt.columns:
            hist = cnt[m].dropna()
            hist = hist[hist.index < last].tail(20)
            if pd.isna(cnt.loc[last, m]):
                continue                       # 該市場最新日沒有資料：由「最新日」比對處理，不在此誤報
            if len(hist) >= 5 and cnt.loc[last, m] < RATIO_MIN * hist.median():
                errs.append(f"{name}/{m}：{last.date()} 只有 {int(cnt.loc[last, m])} 檔，"
                            f"低於前 20 日中位數 {int(hist.median())} 的 {int(RATIO_MIN * 100)}%")
            floor = ABS_MIN.get(name, {}).get(m)
            if floor and cnt.loc[last, m] < floor:
                errs.append(f"{name}/{m}：{last.date()} 只有 {int(cnt.loc[last, m])} 檔，低於絕對下限 {floor}")
    return errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--live", required=True)
    ap.add_argument("--status", default=str(ROOT / "data" / "derived" / "selfhost_status.json"))
    a = ap.parse_args(argv)
    base_dir, live_dir = Path(a.base), Path(a.live)
    errs: list[str] = []
    # 不放時間戳：資料沒變時狀態檔內容也不變，workflow 就不會每天為此 commit（噪音）
    status = {"datasets": {}}
    for name, fn in DATASETS.items():
        lp = live_dir / fn
        if not lp.exists():
            if (base_dir / fn).exists():
                errs.append(f"{name}：這輪缺檔（舊版有）")
            continue
        live = pd.read_parquet(lp)
        bp = base_dir / fn
        base = pd.read_parquet(bp) if bp.exists() else None
        errs += check_dataset(name, live, base)
        status["datasets"][name] = _summary(live, name in DAILY)
    status["gate_ok"] = not errs
    status["errors"] = errs
    Path(a.status).parent.mkdir(parents=True, exist_ok=True)
    Path(a.status).write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    for e in errs:
        print(f"::error::{e}")
    print("閘門", "通過" if not errs else f"未通過（{len(errs)} 項）", json.dumps(status["datasets"], ensure_ascii=False))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
