"""第三輪：兩層標籤原型（類型 V2＋狀態）＋高峰回測（只用當時已公布的季報）。
另算第 3 題影響：一般型裡近 5 年年均 PE 不可用（無或太寬）的檔數。輸出 peak_backtest.md。"""
import sys, warnings; warnings.filterwarnings("ignore")
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import numpy as np, pandas as pd
import bundle_data as bd, valuation as v
from factors.factors import quarterly_factors

OM_REL = 0.5; OM_MIN_SPREAD = 0.10; DROP = 0.40; BASE = 0.5


def type_of(q: pd.DataFrame) -> tuple[str, dict]:
    lb = v.stock_label(q, None)
    om_ok = (lb["om_min"] is not None and lb["om_max"] > 0
             and lb["om_min"] <= OM_REL * lb["om_max"] and lb["om_max"] - lb["om_min"] >= OM_MIN_SPREAD)
    dr_ok = ((lb["max_drop"] is not None and lb["max_drop"] >= DROP)
             or any(d["eps"] <= 0 for d in lb["eps_years"]))          # 近 6 年有虧損年也算大跌
    return ("cyclical" if (om_ok and dr_ok) else "normal"), lb


# 高峰季（period_end）：當時能看到的最後一季財報
PEAKS = {"2603": "2022-03-31", "2609": "2022-03-31", "2615": "2022-03-31", "2637": "2021-12-31",
         "3481": "2021-06-30", "2409": "2021-06-30", "2408": "2021-09-30", "2344": "2021-09-30",
         "2002": "2021-09-30", "2014": "2021-06-30", "1301": "2021-09-30", "1303": "2021-06-30",
         "1326": "2021-06-30", "6505": "2021-06-30", "1907": "2021-06-30", "2603@2018": "2018-03-31",
         "2408@2018": "2018-09-30", "2002@2018": "2018-06-30"}
rows = []
for key, pe_ in PEAKS.items():
    t = key.split("@")[0]
    q = v._quarters(quarterly_factors(bd.financials(t)))
    q = q[q["period_end"] <= pe_]
    ty, lb = type_of(q)
    rows.append({"ticker": key, "高峰季": pe_, "類型": ty,
                 "營益率": f"{lb['om_min']:.0%}～{lb['om_max']:.0%}" if lb["om_min"] is not None else "",
                 "max_drop": f"{lb['max_drop']:.0%}" if lb["max_drop"] is not None else "",
                 "季數": len(q)})
bt = pd.DataFrame(rows)

# 現在全市場：類型＋狀態；第 3 題影響
df = pd.read_csv(OUT / "labels.csv", dtype={"ticker": str})
recs = []
for t in df["ticker"]:
    q = v._quarters(quarterly_factors(bd.financials(t)))
    ty, lb = type_of(q)
    r = df.loc[df["ticker"] == t].iloc[0]
    ttm, est = lb["ttm_eps"], r["est"]
    peak = max([d["eps"] for d in lb["eps_years"]], default=np.nan)
    t4 = q.tail(4)["eps"]
    if ttm is not None and ttm <= 0:
        st = "loss"
    elif ttm is not None and (t4 < 0).any():
        st = "unstable"
    elif ttm is not None and pd.notna(est) and est >= 2 * ttm and ttm <= BASE * peak:
        st = "low_base"
    else:
        st = ""
    pe = v._pe_block(bd.per_history(t), None)
    pe_ok = pe is not None and not pe["wide"]
    recs.append({"ticker": t, "type": ty, "state": st, "pe_ok": pe_ok,
                 "pe_mid": pe["mid"] if pe else np.nan,
                 "growth_ok": bool(ttm and ttm > 0 and pd.notna(est) and est >= ttm / v.BUY_C)})
cur = pd.DataFrame(recs)
cur.to_csv(OUT / "two_layer.csv", index=False, encoding="utf-8-sig")


def md(d):
    return "\n".join(["| " + " | ".join(map(str, d.columns)) + " |", "|" + "---|" * d.shape[1]] +
                     ["| " + " | ".join(map(str, r)) + " |" for r in d.values])

ct = pd.crosstab(cur["type"], cur["state"].replace("", "（無）")).reset_index()
nm = cur[(cur["type"] == "normal") & (cur["state"] == "")]
L = ["# 第三輪：兩層標籤＋高峰回測（2026-10-30）", "",
     f"類型 V2：營益率最低季 ≤ 最高季×{OM_REL} 且差 ≥{OM_MIN_SPREAD:.0%}、最高 >0，且（年 EPS 最大跌幅 ≥{DROP:.0%} 或 近 6 個完整年度有虧損年）。",
     "狀態：虧損中 loss（近四季合計 ≤0）＞獲利不穩 unstable（有虧損季）＞低基期回升 low_base（預估 ≥ 近四季 2 倍且近四季 ≤ 最高年 ×0.5）。", "",
     "## 高峰回測（只用當時已公布季報）", "", md(bt), "",
     "## 現在全市場：類型 × 狀態", "", md(ct), "",
     "## 第 3 題影響（一般型、沒有狀態的那群）", "",
     f"- 共 {len(nm)} 檔；近 5 年年均 PE 可用 {int(nm['pe_ok'].sum())} 檔、不可用（無或太寬）{int((~nm['pe_ok']).sum())} 檔。",
     f"- 預估成長 ≥11% 的 {int(nm['growth_ok'].sum())} 檔；其中 PE 可用 {int((nm['growth_ok'] & nm['pe_ok']).sum())} 檔。",
     f"- 年均 PE 中位數 > 30（會被 30 倍蓋住）的 {int((nm['pe_mid'] > 30).sum())} 檔。", ""]
(OUT / "peak_backtest.md").write_text("\n".join(L), encoding="utf-8")
print("\n".join(L))
