"""自建上游資料健檢閘門：新版資料要「不比舊版差」才允許覆蓋 Release。

比對 `--base`（從 Release 下載的上一版）與 `--live`（這輪跑完的版本）：
1. 列數不得減少（容許 0.1% 浮動：去重）；最新日期不得倒退。
2. 最新一個資料日、每個市場的檔數 ≥ 該市場前 20 個資料日中位數的 90%
   （上游曾發生 .TWO 融資券整批缺／某日只有 57% 檔數；我們不重蹈，見 UPSTREAM_PRACTICES_AUDIT M4）。
3. 實價每日檔數絕對下限（上市 ≥ 900、上櫃 ≥ 700）。

4. 內容恆等式（最近 20 個資料日，逐市場）：法人「外資＋投信＋自營＝合計」不符比例／自營缺值比例 ≤ 5%、
   實價 OHLC 一致性（0 < low ≤ min(open, close) ≤ max(open, close) ≤ high）違反比例 ≤ 1%——欄位位置解析錯位或
   整欄空白時列數／檔數都正常，只有這層看得到（2026-08-27 上櫃自營整欄空白五週沒人發現）。
   融資恆等式（前日餘額＋買進−賣出−現償＝今日餘額）：逐日不符比例的**中位數** ≤ 5%，否則擋上傳（上市 2015–2026 全量驗證 99.4%+ 成立；
   官方會「隔日調帳」，個別日子有五成個股不連續，所以單日只警告、不用整窗平均）。

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
            "corp_actions": "corp_actions.parquet",
            # 累積型旁表（補不回）：一樣要「不得變少、最新日不得倒退」
            "notrade": "notrade.parquet", "refmark": "refmark.parquet", "stophalt": "stophalt.parquet"}
DAILY = {"raw_prices", "inst", "margin"}
ABS_MIN = {"raw_prices": {"TW": 900, "TWO": 700}}
RATIO_MIN = 0.90
SHRINK_TOL = 0.001
IDENT_DAYS = 20
IDENT_MAX = 0.05       # 法人恆等式不符／自營缺值 比例上限
OHLC_MAX = 0.01        # OHLC 違反比例上限


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


def _recent(df: pd.DataFrame) -> pd.DataFrame:
    d = pd.to_datetime(df["date"])
    cut = sorted(d.unique())[-IDENT_DAYS:][0]
    return df[d >= cut]


def content_checks(name: str, live: pd.DataFrame) -> tuple[list[str], list[str]]:
    """內容恆等式。回傳 (errors, warnings)；空表或缺欄＝略過（缺欄由別處處理）。"""
    errs: list[str] = []
    warns: list[str] = []
    if live is None or not len(live) or "market" not in live.columns:
        return errs, warns
    r = _recent(live)
    for m, g in r.groupby("market"):
        if name == "inst" and {"foreign_net", "trust_net", "dealer_net", "total_net"} <= set(g.columns):
            g = g[pd.to_numeric(g["total_net"], errors="coerce").notna()]
            if not len(g):
                continue
            dl = pd.to_numeric(g["dealer_net"], errors="coerce")
            miss = float(dl.isna().mean())
            s = (pd.to_numeric(g["foreign_net"], errors="coerce").fillna(0)
                 + pd.to_numeric(g["trust_net"], errors="coerce").fillna(0) + dl.fillna(0))
            ok = ~dl.isna()
            bad = float(((s - pd.to_numeric(g["total_net"], errors="coerce")).abs() > 1)[ok].mean()) if ok.any() else 0.0
            if miss > IDENT_MAX:
                errs.append(f"inst/{m}：近 {IDENT_DAYS} 日自營缺值 {miss:.1%} > {IDENT_MAX:.0%}（欄位整欄空白／錯位？）")
            if bad > IDENT_MAX:
                errs.append(f"inst/{m}：近 {IDENT_DAYS} 日 外資＋投信＋自營≠合計 {bad:.1%} > {IDENT_MAX:.0%}（欄位錯位？）")
        elif name == "raw_prices" and {"open", "high", "low", "close"} <= set(g.columns):
            o, h, l, c = (pd.to_numeric(g[k], errors="coerce") for k in ("open", "high", "low", "close"))
            valid = o.notna() & h.notna() & l.notna() & c.notna()
            if not valid.any():
                continue
            lo, hi = pd.concat([o, c], axis=1).min(axis=1), pd.concat([o, c], axis=1).max(axis=1)
            viol = ((l <= 0) | (l > lo + 1e-9) | (h < hi - 1e-9))[valid]
            if float(viol.mean()) > OHLC_MAX:
                errs.append(f"raw_prices/{m}：近 {IDENT_DAYS} 日 OHLC 不一致 {viol.mean():.1%} > {OHLC_MAX:.0%}")
        elif name == "margin" and {"margin_balance", "margin_buy", "margin_sell", "margin_redeem", "ticker"} <= set(g.columns):
            g = g.sort_values(["ticker", "date"]).copy()
            for k in ("margin_balance", "margin_buy", "margin_sell", "margin_redeem"):
                g[k] = pd.to_numeric(g[k], errors="coerce")
            g["_prev"] = g.groupby("ticker")["margin_balance"].shift()
            x = g.dropna(subset=["_prev", "margin_balance", "margin_buy", "margin_sell", "margin_redeem"])
            if len(x):
                # 官方「隔日調帳」：個別日子（長假後、調帳高峰）會有五成個股「前日餘額≠昨日今日餘額」（實測 2019-02-11、2026-04-09），
                # 所以不用整窗平均，改看「逐日不符比例的中位數」——欄位錯位幾乎每天都壞，單日調帳不會
                badrow = ((x["_prev"] + x["margin_buy"] - x["margin_sell"] - x["margin_redeem"]
                           - x["margin_balance"]).abs() > 1)
                per_day = badrow.groupby(x["date"]).mean()
                med = float(per_day.median())
                if med > IDENT_MAX:
                    errs.append(f"margin/{m}：近 {IDENT_DAYS} 日融資餘額恆等式逐日不符比例中位數 {med:.1%} > {IDENT_MAX:.0%}（欄位錯位？）")
                elif float(per_day.max()) > 0.3:
                    warns.append(f"margin/{m}：{per_day.idxmax():%Y-%m-%d} 融資餘額恆等式不符 {per_day.max():.0%}（可能是官方隔日調帳，單日不擋）")
    return errs, warns


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--live", required=True)
    ap.add_argument("--assets", help="Release 上實際有的檔名清單（一行一個）。清單有、但 --base 缺檔＝下載失敗，一律擋（不可當成「尚無舊版」）")
    ap.add_argument("--status", default=str(ROOT / "data" / "derived" / "selfhost_status.json"))
    a = ap.parse_args(argv)
    base_dir, live_dir = Path(a.base), Path(a.live)
    errs: list[str] = []
    warns: list[str] = []
    # 不放時間戳：資料沒變時狀態檔內容也不變，workflow 就不會每天為此 commit（噪音）
    status = {"datasets": {}}
    if a.assets and Path(a.assets).exists():
        listed = {x.strip() for x in Path(a.assets).read_text(encoding="utf-8").splitlines() if x.strip()}
        for fn in DATASETS.values():
            if fn in listed and not (base_dir / fn).exists():
                errs.append(f"{fn}：Release 上有、但舊版基準缺檔（下載失敗？）——不可當成『尚無舊版』放行")
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
        ce, cw = content_checks(name, live)
        errs += ce
        warns += cw
        status["datasets"][name] = _summary(live, name in DAILY)
    status["gate_ok"] = not errs
    status["errors"] = errs
    status["warnings"] = warns
    Path(a.status).parent.mkdir(parents=True, exist_ok=True)
    Path(a.status).write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    for w in warns:
        print(f"::warning::{w}")
    for e in errs:
        print(f"::error::{e}")
    print("閘門", "通過" if not errs else f"未通過（{len(errs)} 項）", json.dumps(status["datasets"], ensure_ascii=False))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
