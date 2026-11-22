"""調研①：還原後 EPS 的分界季有沒有判錯。
隱含股數 S_adj＝歸母淨利 ÷ 還原 EPS；分界判對 → 事件前後 S_adj 平穩；判錯 → 事件附近某相鄰兩季 S_adj 比值 ≈ m 或 1/m。
只看 m 偏離 1 ≥5% 的事件（小配股被 EPS 四捨五入淹沒）、相鄰兩季 |EPS|≥0.3。
輸出 boundary_suspects.csv 與摘要。"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from reference import corporate_actions as ca

OUT = Path(__file__).with_name("boundary_suspects.csv")
inc = pd.read_parquet(r"D:\g\claude\tw-swing\data\fundamentals\income.parquet")
inc = inc.rename(columns={"equity_parent": "ni_parent"})  # income 的 equity_parent＝歸母淨利
inc["period_end"] = pd.to_datetime(inc["period_end"])
inc = inc[inc["period_end"] >= "2015-01-01"]
rows, n_ev, n_tk = [], 0, 0
for t, g in inc.groupby("ticker"):
    evs = [(ts, m) for ts, m in ca._events(t) if abs(np.log(m)) >= np.log(1.05) and ts >= pd.Timestamp("2015-06-01")]
    if not evs:
        continue
    n_tk += 1
    g = g.sort_values("period_end").reset_index(drop=True)
    a = ca.adjust_eps(g.copy())
    ni = pd.to_numeric(g["ni_parent"], errors="coerce").where(lambda x: x.notna(), g["net_income"])
    raw, adj = g["eps"].astype(float), a["eps"].astype(float)
    s_adj, s_raw = ni / adj, ni / raw
    for ts, m in evs:
        n_ev += 1
        win = g.index[(g["period_end"] >= ts - pd.DateOffset(months=9)) & (g["period_end"] <= ts + pd.DateOffset(months=6))]
        for i in win:
            if i == 0:
                continue
            ok = all(abs(x) >= 0.3 for x in (raw[i - 1], raw[i])) and s_adj[i - 1] > 0 and s_adj[i] > 0
            if not ok:
                continue
            r = s_adj[i] / s_adj[i - 1]
            # 持續性：跳動前 3 季與後 3 季（含本季）中位數之比也要 ≈ target，排除單季尖峰（特別股股利、Q4 倒算雜訊）
            pre = s_adj[max(0, i - 3):i][lambda x: x > 0]
            post = s_adj[i:i + 3][lambda x: x > 0]
            if len(pre) < 2 or len(post) < 2:
                continue
            step = post.median() / pre.median()
            for target, kind in ((m, "還原後仍跳 m（該除沒除）"), (1 / m, "還原後跳 1/m（不該除卻除）")):
                if abs(np.log(r) - np.log(target)) <= 0.03 and abs(np.log(r)) >= np.log(1.04)                         and abs(np.log(step) - np.log(target)) <= 0.03:
                    rows.append(dict(ticker=t, event=ts.date(), m=m, q_prev=g["period_end"][i - 1].date(),
                                     q=g["period_end"][i].date(), eps_raw_prev=raw[i - 1], eps_raw=raw[i],
                                     eps_adj_prev=round(adj[i - 1], 3), eps_adj=round(adj[i], 3),
                                     s_adj_ratio=round(r, 4), s_raw_ratio=round(s_raw[i] / s_raw[i - 1], 4), step=round(step, 4), kind=kind))
df = pd.DataFrame(rows).drop_duplicates(["ticker", "event", "q"])
df.to_csv(OUT, index=False, encoding="utf-8")
print(f"檢查 {n_tk} 檔、{n_ev} 個事件（m≥5%）；疑似分界錯 {len(df)} 筆／{df['ticker'].nunique() if len(df) else 0} 檔")
if len(df):
    print(df["kind"].value_counts().to_string())
    print(df.groupby(df["event"].astype(str).str[:4]).size().to_string())
