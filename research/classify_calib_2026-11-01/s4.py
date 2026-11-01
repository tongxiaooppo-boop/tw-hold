from common import *

inputs, res, names, ind, m = load()
T = list(inputs)
rows = []
for t in T:
    q = inputs[t].quarters
    op = qp.ttm(q["op_income"].astype(float)); rv = qp.ttm(q["revenue"].astype(float))
    win = op.tail(40); rwin = rv.tail(40)
    mm = res[t].metrics
    pk = win.max() if win.notna().any() else np.nan
    dp = mm["dd_peak"]
    peak_at_dd = float(win.loc[dp]) if dp is not None and dp in win.index else np.nan
    rows.append({"ticker": t, "name": names.get(t), "industry": ind[t], "type": res[t].type,
                 "max_dd": mm["max_dd"], "contr": mm["contraction"], "peak_max": pk, "peak_dd": peak_at_dd,
                 "rev_med": rwin.median(), "nec": mm["cyclical_necessary"]})
d = pd.DataFrame(d for d in rows)
d["peak_dd_rev_pct"] = 100 * d.peak_dd / d.rev_med
med_peak = d.loc[d.peak_max > 0, "peak_max"].median()
print("全體前高(窗內 TTM 營業利益最大值,正值者)中位數 =", med_peak, " 5% =", 0.05 * med_peak)
print("max_dd 可算檔數", int(d.max_dd.notna().sum()))
# 1. 全市場：記錄那段前高 <= 5% 全體前高中位數 且 回撤>=100%
small = d.peak_dd <= 0.05 * med_peak
big = d.max_dd >= 1.0
print("全市場: 記錄段前高<=5%中位 且 max_dd>=100%:", int((small & big).sum()), " (前高<=5%中位 共", int(small.sum()), "; max_dd>=100% 共", int(big.sum()), ")")
d["peak_max_small"] = d.peak_max <= 0.05 * med_peak
print("  以窗內最大前高判定(peak_max<=5%中位 且 max_dd>=100%):", int((d.peak_max_small & big).sum()))
# 比較用：前高 <1% 該檔 TTM 營收
tiny = d.peak_dd < 0.01 * d.rev_med
print("全市場: 記錄段前高<1%營收 共", int(tiny.sum()), "；且 max_dd>=100%:", int((tiny & big).sum()), "；且 contraction&max_dd>=0.5:", int((tiny & d.nec).sum()))
print("全市場 max_dd > 100% 檔數:", int((d.max_dd > 1.0).sum()), " >=100%:", int(big.sum()))
cyc = d[d.type == "cyclical"].copy()
print("\nbaseline cyclical n =", len(cyc))
print("  前高(記錄段) <=0:", int((cyc.peak_dd <= 0).sum()), "  (op_drawdown 只認前高>0，故理論為 0)")
t1 = cyc[cyc.peak_dd < 0.01 * cyc.rev_med].sort_values("peak_dd_rev_pct")
print("  記錄段前高 < 窗內TTM營收中位數的1%:", len(t1))
print(tab(t1[["ticker", "name", "industry", "max_dd", "peak_dd", "rev_med", "peak_dd_rev_pct"]].head(15)))
t5 = cyc[cyc.peak_dd <= 0.05 * med_peak]
print("  記錄段前高 <= 5% 全體前高中位數:", len(t5))
print("  max_dd>1(回撤超過100%) 檔數:", int((cyc.max_dd > 1).sum()), " 占", f"{100*(cyc.max_dd>1).mean():.1f}%")
print("  max_dd>2:", int((cyc.max_dd > 2).sum()), " max_dd>=1.5:", int((cyc.max_dd >= 1.5).sum()))
ov = cyc[cyc.max_dd > 1].sort_values("max_dd", ascending=False)
print(tab(ov[["ticker", "name", "industry", "max_dd", "peak_dd_rev_pct"]].head(15)))
# 反事實：把 >100%（低點為負）封頂的話？ 若回撤 cap 在 100% 或把「前高<1%營收」排除，循環檔剩幾
print("\n反事實（只描述）: 排除『記錄段前高<1%營收』後 baseline 循環檔剩", int(len(cyc) - len(t1)))
print("反事實: 排除『記錄段前高<=5%全體中位』後剩", int(len(cyc) - len(t5)))
# 這些小前高檔的 dd 是否換一個更合理的段仍會過？ 用 '僅考慮前高>=1%營收' 重掃
def scan_floor(q, floor_pct):
    op = qp.ttm(q["op_income"].astype(float)); rv = qp.ttm(q["revenue"].astype(float))
    yoy = cl._ttm_yoy(rv); win = op.tail(40); revmed = rv.tail(40).median()
    pv = None; pt = None; ok = False
    for tt, v in win.items():
        if pd.isna(v): continue
        if pv is None or v >= pv: pv, pt = float(v), tt
        if pv > 0 and pv >= floor_pct * revmed:
            dd = 1 - v / pv
            if dd >= 0.5 - 1e-12:
                seg = yoy.loc[pt:tt].dropna()
                if len(seg) and seg.min() < -0.10: ok = True
    return ok
cyc["ok_floor1"] = [scan_floor(inputs[t].quarters, 0.01) for t in cyc.ticker]
print("反事實(前高須>=1%窗內營收中位才算回撤段): baseline 循環檔仍成立", int(cyc.ok_floor1.sum()), "/", len(cyc))
cyc["ok_floor3"] = [scan_floor(inputs[t].quarters, 0.03) for t in cyc.ticker]
print("反事實(前高須>=3%): 仍成立", int(cyc.ok_floor3.sum()))
print("不成立者(1%)前15:"); print(tab(cyc[~cyc.ok_floor1][["ticker", "name", "industry", "max_dd", "peak_dd_rev_pct"]].head(15)))
d.to_csv(OUT / "s4_detail.csv", index=False, encoding="utf-8-sig")
print("\n循環檔中記錄段前高<=5%全體前高中位 的清單(前15):")
print(tab(t5.sort_values("peak_dd")[["ticker", "name", "industry", "max_dd", "peak_dd", "peak_dd_rev_pct"]].head(15)))
print("前高須>=3%營收即不成立者:"); print(tab(cyc[~cyc.ok_floor3][["ticker", "name", "industry", "max_dd", "peak_dd_rev_pct"]]))
print("循環檔 peak_dd_rev_pct 分位:", cyc.peak_dd_rev_pct.quantile([0, .05, .1, .25, .5]).round(2).to_dict())
