"""調研①驗證：用 XBRL「首次申報單季 EPS ÷ 隔年同季比較數」判斷該季申報時是舊／新股數，
對照 adjust_eps 對這個事件有沒有除那一季。只驗 boundary_suspects.csv 的事件、Q1～Q3（Q4 年報沒有單季數）。"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from reference import corporate_actions as ca

FACTS = Path(r"D:\g\claude\p6_study\xbrl_facts")
HERE = Path(__file__).parent
sus = pd.read_csv(HERE / "boundary_suspects.csv", dtype={"ticker": str})
inc = pd.read_parquet(r"D:\g\claude\tw-swing\data\fundamentals\income.parquet").rename(columns={"equity_parent": "ni_parent"})
inc["period_end"] = pd.to_datetime(inc["period_end"])
_cache = {}

def facts(filing, t):
    key = (filing, t)
    if key not in _cache:
        p = FACTS / f"facts_{filing}.parquet"
        if not p.exists():
            _cache[key] = None
        else:
            f = pd.read_parquet(p, filters=[("ticker", "==", t)])
            _cache[key] = f[f["concept"] == "ifrs-full:BasicEarningsLossPerShare"]
    return _cache[key]

def q_eps(filing, t, pe):
    f = facts(filing, t)
    if f is None or f.empty:
        return None
    start = (pe - pd.offsets.QuarterBegin(startingMonth=1)).strftime("%Y%m%d") if pe.month != 3 else f"{pe.year}0101"
    start = (pe.to_period("Q").start_time).strftime("%Y%m%d")
    v = f[(f["start"].astype(str) == start) & (f["end"].astype(str) == pe.strftime("%Y%m%d"))]["value"]
    return float(v.iloc[0]) if len(v) else None

rows = []
for (t, ev), _ in sus.groupby(["ticker", "event"]):
    ts = pd.Timestamp(ev)
    g = inc[inc["ticker"] == t].sort_values("period_end").reset_index(drop=True)
    before = ca.adjust_eps(g.copy(), upto=ts - pd.Timedelta(days=1))["eps"]
    after = ca.adjust_eps(g.copy(), upto=ts)["eps"]
    m = dict(ca._events(t))[ts]
    for i, pe in enumerate(g["period_end"]):
        if not (ts - pd.DateOffset(months=12) <= pe <= ts + pd.DateOffset(months=3)) or pe.month == 12:
            continue
        fq = f"{pe.year}Q{pe.quarter}"
        cq = f"{pe.year + 1}Q{pe.quarter}"
        first, comp = q_eps(fq, t, pe), q_eps(cq, t, pe - pd.DateOffset(years=0))
        if first is None or comp is None or abs(first) < 0.2 or abs(comp) < 0.05:
            continue
        r = first / comp
        truth = "舊（該除）" if abs(np.log(abs(r)) - np.log(m)) <= 0.03 else "新（不該除）" if abs(np.log(abs(r))) <= 0.02 else "看不出"
        did = before[i] / after[i] if after[i] else np.nan
        ours = "有除" if abs(np.log(abs(did)) - np.log(m)) <= 0.01 else "沒除" if abs(np.log(abs(did))) <= 0.01 else f"×{did:.3f}"
        ok = (truth.startswith("舊") and ours == "有除") or (truth.startswith("新") and ours == "沒除")
        rows.append(dict(ticker=t, event=ev, m=round(m, 4), quarter=fq, first=first, comparative=comp,
                         ratio=round(r, 4), truth=truth, ours=ours, verdict="對" if ok else "看不出" if truth == "看不出" else "錯"))
out = pd.DataFrame(rows)
out.to_csv(HERE / "boundary_verified.csv", index=False, encoding="utf-8")
print(out["verdict"].value_counts().to_string())
bad = out[out["verdict"] == "錯"]
print(f"判錯 {len(bad)} 季／{bad['ticker'].nunique()} 檔；其中 2021 年後事件 {len(bad[bad['event'] >= '2021'])} 季")
pd.set_option("display.width", 220)
print(bad.to_string(index=False))
