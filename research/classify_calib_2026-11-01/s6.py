from common import *

inputs, res, names, ind, m = load()
T = list(inputs)
rows = []
for t in T:
    r = res[t]
    if r.type in ("insufficient",) : continue
    q = inputs[t].quarters
    op = q["op_income"].astype(float); opt = qp.ttm(op).tail(3).to_numpy(dtype=float)
    e1 = bool(pd.notna(op.iloc[-1]) and op.iloc[-1] > 0)
    e2 = bool(len(opt) == 3 and not np.isnan(opt).any() and opt[2] > opt[1] > opt[0])
    g3 = inputs[t].g3
    e3 = bool(pd.notna(g3) and g3 > 0)
    rows.append({"ticker": t, "name": names.get(t), "industry": ind[t], "type": r.type,
                 "loss": cl.STATE_LOSS in r.state, "turn_now": (cl.STATE_TURNAROUND in r.state) or (cl.STATE_TROUGH_RECOVERY in r.state),
                 "e_op>0": e1, "e_ttm_up2": e2, "e_g3>0": e3, "n_evid": int(e1) + int(e2) + int(e3),
                 "ttm_eps": r.metrics["ttm_eps"], "display": cl.display_type(r)})
d = pd.DataFrame(rows)
print("狀態『轉機』(含谷底回升) 目前:", int(d.turn_now.sum()), " 其中型態:", d[d.turn_now].type.value_counts().to_dict())
print("state『虧損』全體:", int(d.loss.sum()), d[d.loss].type.value_counts().to_dict())
print("display_type=='轉機':", int((d.display == "轉機").sum()))
L = d[d.loss & (d.type != "cyclical")]
print("\n非循環且 TTM 虧損:", len(L), L.type.value_counts().to_dict())
print("  其中 轉機狀態(現行條件)成立:", int(L.turn_now.sum()))
out = []
for lab, mask in (("全成立(3)", L.n_evid == 3), ("成立兩項", L.n_evid == 2), ("成立一項", L.n_evid == 1), ("皆不成立", L.n_evid == 0)):
    x = L[mask]
    out.append({"組": lab, "檔數": len(x), "其中現行轉機": int(x.turn_now.sum())})
print(tab(pd.DataFrame(out)))
print("evidence 各項成立數:", {c: int(L[c].sum()) for c in ("e_op>0", "e_ttm_up2", "e_g3>0")})
two = L[L.n_evid == 2]
print("兩項時缺哪一項:", {c: int((~two[c]).sum()) for c in ("e_op>0", "e_ttm_up2", "e_g3>0")})
for lab, mask in (("全成立(3)", L.n_evid == 3), ("成立兩項", L.n_evid == 2), ("成立一項", L.n_evid == 1), ("皆不成立", L.n_evid == 0)):
    print("\n", lab, "前10:"); print(tab(L[mask][["ticker", "name", "industry", "type", "ttm_eps", "e_op>0", "e_ttm_up2", "e_g3>0"]].head(10), 2))
# 現行轉機 vs 草案(三證據全成立+近4季曾虧損)：非循環全體
N = d[d.type != "cyclical"]
print("\n非循環全體: 現行轉機", int(N.turn_now.sum()), "；其中虧損中", int((N.turn_now & N.loss).sum()), "；非虧損(TTM EPS>0 但近4季有負)", int((N.turn_now & ~N.loss).sum()))
print("display=='轉機' 非循環:", int((N.display == "轉機").sum()), "；其中 現行轉機狀態 / 只是虧損:", int(((N.display == "轉機") & N.turn_now).sum()), int(((N.display == "轉機") & ~N.turn_now).sum()))
d.to_csv(OUT / "s6_detail.csv", index=False, encoding="utf-8-sig")
