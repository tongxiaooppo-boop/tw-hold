from common import *

inputs, res, names, ind, m = load()
T = list(inputs)
# 每家個股的月頻 TTM YoY（全部有月營收的 ticker）
yoy = {}
for t, g in m.groupby("ticker"):
    s = g.set_index("month")["revenue"].sort_index()
    yoy[t] = ri.stock_ttm_yoy(s)
W = pd.DataFrame(yoy)
print("月營收股票數", W.shape[1], "月數", W.shape[0])
cnt = W.notna().sum(axis=1)
mk = W.median(axis=1).where(cnt >= ri.MIN_MEMBERS)
mk_base = bc.ri.build_market_index(m)["ttm_yoy"]
print("等權市場指數 vs 加權: 相關", float(pd.concat([mk, mk_base], axis=1).dropna().corr().iloc[0, 1]))
print("最近12月 等權/加權:\n", pd.concat([mk.rename("ew"), mk_base.rename("cap")], axis=1).tail(12).round(3).to_string())
low = pd.concat([mk.rename("ew"), mk_base.rename("cap")], axis=1).dropna()
print("市場指數<0月數: ew", int((low.ew < 0).sum()), " cap", int((low.cap < 0).sum()), "/", len(low))
# 產業等權（排除自己）
indS = pd.Series(ind)
members = {g: [t for t in idx.index if t in W.columns] for g, idx in indS.groupby(indS)}
def ind_ew_excl(t):
    g = ind.get(t)
    if g is None: return pd.Series(dtype=float)
    oth = [x for x in members.get(g, []) if x != t]
    sub = W[oth]
    c = sub.notna().sum(axis=1)
    return sub.median(axis=1).where(c >= ri.MIN_MEMBERS)
rows = []
for t in T:
    sy = yoy.get(t, pd.Series(dtype=float))
    rows.append({"ticker": t, "name": names.get(t), "industry": ind[t],
                 "beta_cap": inputs[t].rev_beta, "sync_cap": inputs[t].ind_sync,
                 "beta_ew": ri.revenue_beta(sy, mk), "sync_ew": ri.industry_sync(sy, ind_ew_excl(t)),
                 "nec": res[t].metrics["cyclical_necessary"], "type": res[t].type})
d = pd.DataFrame(rows)
def aux(b, s):
    return ((b >= 1.5) & b.notna()) | ((s >= 0.6) & s.notna())
d["aux_cap"] = aux(d.beta_cap, d.sync_cap); d["aux_ew"] = aux(d.beta_ew, d.sync_ew)
d["beta_ok_cap"] = d.beta_cap >= 1.5; d["beta_ok_ew"] = d.beta_ew >= 1.5
d["sync_ok_cap"] = d.sync_cap >= 0.6; d["sync_ok_ew"] = d.sync_ew >= 0.6
d.to_csv(OUT / "s3_detail.csv", index=False, encoding="utf-8-sig")
def summ(x, lab):
    return {"範圍": lab, "檔數": len(x), "beta≥1.5 cap": int(x.beta_ok_cap.sum()), "beta≥1.5 ew": int(x.beta_ok_ew.sum()),
            "sync≥0.6 cap": int(x.sync_ok_cap.sum()), "sync≥0.6 ew": int(x.sync_ok_ew.sum()),
            "輔助成立 cap": int(x.aux_cap.sum()), "輔助成立 ew": int(x.aux_ew.sum()),
            "兩者皆成立": int((x.aux_cap & x.aux_ew).sum()), "僅cap": int((x.aux_cap & ~x.aux_ew).sum()), "僅ew": int((~x.aux_cap & x.aux_ew).sum()),
            "beta_cap中位": x.beta_cap.median(), "beta_ew中位": x.beta_ew.median(),
            "sync_cap中位": x.sync_cap.median(), "sync_ew中位": x.sync_ew.median()}
S = pd.DataFrame([summ(d, "全體"), summ(d[d.nec], "必要①②成立(baseline)")])
print(tab(S))
print("beta 相關(cap vs ew):", float(d[["beta_cap", "beta_ew"]].corr().iloc[0, 1]), " sync 相關:", float(d[["sync_cap", "sync_ew"]].corr().iloc[0, 1]))
print("NaN 數 beta cap/ew:", int(d.beta_cap.isna().sum()), int(d.beta_ew.isna().sum()), " sync:", int(d.sync_cap.isna().sum()), int(d.sync_ew.isna().sum()))
# 產業
big = indS.value_counts(); big = big[big >= 12].index
ir = []
for g in big:
    x = d[d.industry == g]
    ir.append({"industry": g, "n": len(x), "aux_cap": int(x.aux_cap.sum()), "aux_ew": int(x.aux_ew.sum()),
               "aux_cap%": 100 * x.aux_cap.mean(), "aux_ew%": 100 * x.aux_ew.mean(),
               "beta_cap中位": x.beta_cap.median(), "beta_ew中位": x.beta_ew.median(),
               "sync_cap中位": x.sync_cap.median(), "sync_ew中位": x.sync_ew.median()})
ir = pd.DataFrame(ir).sort_values("n", ascending=False); print(tab(ir, 2)); ir.to_csv(OUT / "s3_industry.csv", index=False, encoding="utf-8-sig")
# 必要①②成立者中，確認/疑似
nec = d[d.nec]
print("必要①②成立", len(nec), " 確認(cap)", int(nec.aux_cap.sum()), " 確認(ew)", int(nec.aux_ew.sum()))
K = ["2330", "2317", "2454", "2603", "2609", "2002", "1301", "1101", "3008"]
print(tab(d[d.ticker.isin(K)].set_index("ticker").loc[K].reset_index()[["ticker", "name", "industry", "beta_cap", "beta_ew", "sync_cap", "sync_ew", "aux_cap", "aux_ew"]], 2))
