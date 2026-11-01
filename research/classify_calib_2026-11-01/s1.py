import dataclasses
from common import *

inputs, res, names, ind, m = load()
T = list(inputs)
print("baseline types:", pd.Series({t: res[t].type for t in T}).value_counts().to_dict())
amp = pd.Series({t: res[t].metrics["oroa_amp"] for t in T})
med = pd.Series({t: cl.oroa_series(inputs[t].quarters).tail(40).dropna().median() for t in T})
FLOOR = 0.02
rel = amp / med.abs().clip(lower=FLOOR)
pa = pd.Series({t: inputs[t].oroa_amp_pct for t in T})
pb = cl.cross_section_pct(rel)
# (c) 產業內分位
pc = pa.copy()
indS = pd.Series(ind)
for g, idx in indS.groupby(indS):
    a = amp.reindex(idx.index)
    if a.notna().sum() >= 8:
        pc.loc[a.dropna().index] = cl.cross_section_pct(a.dropna())
THR = 0.70 - 1e-12
nec1 = {"a": pa >= THR, "b": pb >= THR, "c": pc >= THR}
# 重跑 classify：把分位換成 1.0/0.0（nec1 成立/不成立），NaN 保持
newres = {"a": res}
for k in "bc":
    pct = {"b": pb, "c": pc}[k]
    d = {}
    for t in T:
        v = float("nan") if pd.isna(pct[t]) else (1.0 if nec1[k][t] else 0.0)
        d[t] = cl.classify(dataclasses.replace(inputs[t], oroa_amp_pct=v))
    newres[k] = d
rows = []
for k in "abc":
    r = newres[k]
    nec = pd.Series({t: r[t].metrics["cyclical_necessary"] for t in T})
    aux = pd.Series({t: r[t].metrics["cyclical_aux"] for t in T})
    n1 = nec1[k]
    rows.append({"做法": k, "必要①成立": int(n1.sum()), "必要①+②": int(nec.sum()),
                 "輔助成立(確認循環)": int((nec & aux).sum()), "輔助未過(疑似)": int((nec & ~aux).sum()),
                 "最終type=循環": sum(r[t].type == "cyclical" for t in T),
                 "最終type=高成長": sum(r[t].type == "growth" for t in T),
                 "最終type=一般": sum(r[t].type == "normal" for t in T)})
summ = pd.DataFrame(rows); print(tab(summ))
summ.to_csv(OUT / "s1_summary.csv", index=False, encoding="utf-8-sig")
# 差異
diff = []
for k in "bc":
    add = sorted(set(nec1[k][nec1[k]].index) - set(nec1["a"][nec1["a"]].index))
    rem = sorted(set(nec1["a"][nec1["a"]].index) - set(nec1[k][nec1[k]].index))
    print(f"\n({k}) 相對(a) 必要①新增 {len(add)} 檔、移除 {len(rem)} 檔")
    for lab, lst in (("新增", add), ("移除", rem)):
        for t in lst:
            diff.append({"做法": k, "變動": lab, "ticker": t, "name": names.get(t), "industry": ind[t],
                         "amp": amp[t], "rel": rel[t], "nec2": res[t].metrics["contraction"] and res[t].metrics["max_dd"] >= .5})
dd = pd.DataFrame(diff); dd.to_csv(OUT / "s1_diff.csv", index=False, encoding="utf-8-sig")
# 新增/移除中，必要②也成立（真正影響循環判定）者
for k in "bc":
    sub = dd[(dd["做法"] == k) & dd["nec2"]]
    print(f"\n({k}) 新增/移除且必要②成立（會影響必要①+②）:")
    print(tab(sub[["變動", "ticker", "name", "industry", "amp", "rel"]]))
# 重點檔
kr = []
for t in KEY1:
    if t not in inputs: print("missing", t); continue
    mm = res[t].metrics
    kr.append({"ticker": t, "name": names.get(t), "industry": ind[t], "amp": amp[t], "pct_a": pa[t],
               "med": med[t], "rel": rel[t], "pct_b": pb[t], "pct_c": pc[t],
               "n1a": bool(nec1["a"][t]), "n1b": bool(nec1["b"][t]), "n1c": bool(nec1["c"][t]),
               "max_dd": mm["max_dd"], "contr": mm["contraction"], "aux": mm["cyclical_aux"],
               "type_a": res[t].type, "type_b": newres["b"][t].type, "type_c": newres["c"][t].type})
kr = pd.DataFrame(kr); print(tab(kr)); kr.to_csv(OUT / "s1_key.csv", index=False, encoding="utf-8-sig")
# 產業占比 (樣本>=12)
ind_n = indS.value_counts(); big = ind_n[ind_n >= 12].index
ir = []
for g in big:
    ts = indS[indS == g].index
    row = {"industry": g, "n": len(ts)}
    for k in "abc":
        r = newres[k]
        nec = [r[t].metrics["cyclical_necessary"] for t in ts]
        aux = [r[t].metrics["cyclical_aux"] for t in ts]
        n = sum(nec); c = sum(a and b for a, b in zip(nec, aux))
        row[f"{k}_n1"] = int(nec1[k][ts].sum()); row[f"{k}_必要①②"] = n; row[f"{k}_確認"] = c; row[f"{k}_疑似"] = n - c
        row[f"{k}_占比%"] = 100 * n / len(ts)
    ir.append(row)
ir = pd.DataFrame(ir).sort_values("n", ascending=False); print(tab(ir, 1)); ir.to_csv(OUT / "s1_industry.csv", index=False, encoding="utf-8-sig")
# 產業占比：循環檔中各產業佔比（a vs b vs c）
for k in "abc":
    cyc = [t for t in T if newres[k][t].metrics["cyclical_necessary"]]
    print(k, "必要①②檔產業分布 top8:", pd.Series([ind[t] for t in cyc]).value_counts().head(8).to_dict())
