"""B1 第二輪調查：照 Opus 提議改標籤規則（不改 app），比較各版本分布與指定檔。
需要先有 labels.csv（classify_all.py 產出）。輸出 relabel.md、relabel.csv。"""
import sys, warnings; warnings.filterwarnings("ignore")
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import numpy as np, pandas as pd
import bundle_data as bd, valuation as v
from factors.factors import quarterly_factors

KNOWN_CYC = "2603 2609 2615 2002 2014 1301 1303 1326 6505 3481 2409 2408 2344 1907".split()
KNOWN_NOT = "2330 2412 3045 4904 1216 2912 2207 2317 6669 3661 2345 2059 2454 2308".split()

df = pd.read_csv(OUT / "labels.csv", dtype={"ticker": str})
feat = []
for t in df["ticker"]:
    q = v._quarters(quarterly_factors(bd.financials(t)))
    ey = v.stock_label(q, None)["eps_years"]
    e = [d["eps"] for d in ey]
    peak = max(e) if e else np.nan
    yoy = sum(1 for a, b in zip(e, e[1:]) if a > 0 and b <= a * 0.7)     # 年對年跌 ≥30% 的次數
    feat.append({"ticker": t, "eps_peak": peak, "yoy_drops": yoy, "n_years": len(e)})
df = df.merge(pd.DataFrame(feat), on="ticker")

# 轉機：虧損兩條照舊；「預估 ≥ 近四季 2 倍」加條件：近四季 ≤ 過去完整年度最高 EPS × 0.5
loss = df["turn_why"].fillna("").str.contains("≤ 0|虧損季")
x2 = df["turn_why"].fillna("").str.contains("2 倍")
df["turn_new"] = loss | (x2 & (df["ttm_eps"] <= 0.5 * df["eps_peak"]))

spread = df["om_max"] - df["om_min"]
om_rel = (df["om_min"] <= 0.5 * df["om_max"]) & (spread >= 0.10)       # 最低季營益率不到最高的一半（且至少差 10 點）
drop = df["max_drop"]
V = {
    "V0 現行（OM差≥20 或 跌≥40%）": (spread >= 0.20) | (drop >= 0.40),
    "V1 OM相對 或 跌≥40%": om_rel | (drop >= 0.40),
    "V2 OM相對 且 跌≥40%": om_rel & (drop >= 0.40),
    "V3 OM相對 且 跌≥50%": om_rel & (drop >= 0.50),
    "V4 跌≥40% 且 年跌≥30%至少2次": (drop >= 0.40) & (df["yoy_drops"] >= 2),
    "V5 OM相對 且 跌≥40% 且 年跌2次": om_rel & (drop >= 0.40) & (df["yoy_drops"] >= 2),
}
rows, picks = [], {}
for name, cyc in V.items():
    lab = np.where(df["turn_new"], "turnaround", np.where(cyc.fillna(False), "cyclical", "normal"))
    s = pd.Series(lab, index=df["ticker"])
    picks[name] = s
    kc = s.reindex(KNOWN_CYC)
    kn = s.reindex(KNOWN_NOT)
    rows.append({"版本": name, "轉機": int((s == "turnaround").sum()), "循環": int((s == "cyclical").sum()),
                 "一般": int((s == "normal").sum()),
                 "已知循環股判對（循環或轉機）": f"{int((kc != 'normal').sum())}/{len(KNOWN_CYC)}",
                 "已知非循環股判成一般": f"{int((kn == 'normal').sum())}/{len(KNOWN_NOT)}"})
res = pd.DataFrame(rows)
P = pd.DataFrame(picks)
P.columns = [c.split()[0] for c in P.columns]
P.insert(0, "現行", df.set_index("ticker")["label"])

def md(d):
    d = d.reset_index() if d.index.name else d
    return "\n".join(["| " + " | ".join(map(str, d.columns)) + " |", "|" + "---|" * d.shape[1]] +
                     ["| " + " | ".join(map(str, r)) + " |" for r in d.values])

L = ["# B1 第二輪：標籤規則改版調查（2026-10-30）", "",
     "轉機股全部版本都套新規則：「預估 ≥ 近四季 2 倍」須再滿足 近四季 ≤ 過去完整年度最高 EPS × 0.5。",
     "OM相對＝近 24 季最低營益率 ≤ 最高 × 0.5 且 最高−最低 ≥ 10 個百分點。", "",
     f"轉機股：現行 {int((df['label']=='turnaround').sum())} → 新 {int(df['turn_new'].sum())} 檔。", "",
     "## 各版本分布", "", md(res), "",
     "## 已知循環股", "", md(P.reindex(KNOWN_CYC).rename_axis("ticker")), "",
     "## 已知非循環股", "", md(P.reindex(KNOWN_NOT).rename_axis("ticker")), ""]
el = df[df["high_pe_eligible"].astype(bool)]["ticker"]
L += ["## 高本益比過關 17 檔在各版本的標籤", "", md(P.reindex(el).rename_axis("ticker")), ""]
(OUT / "relabel.md").write_text("\n".join(L), encoding="utf-8")
P.to_csv(OUT / "relabel.csv", encoding="utf-8-sig")
print("\n".join(L))
