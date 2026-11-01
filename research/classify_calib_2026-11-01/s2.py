from common import *

inputs, res, names, ind, m = load()
T = list(inputs)

def scan(win, yoy):
    """複製 op_drawdown 的逐點掃描；回傳 (contraction, dd, peak, trough)。win 內 NaN 跳過。"""
    peak_val = peak_t = None; best = None
    for t, v in win.items():
        if pd.isna(v): continue
        if peak_val is None or v >= peak_val: peak_val, peak_t = float(v), t
        if peak_val > 0:
            dd = 1 - float(v) / peak_val
            if dd >= cl.CYCLE_DRAWDOWN - 1e-12 and (best is None or dd > best[0]):
                seg = yoy.loc[peak_t:t].dropna()
                if len(seg) and float(seg.min()) < cl.CYCLE_REV_CONTRACTION:
                    best = (dd, peak_t, t)
    return (best is not None, *(best if best else (np.nan, None, None)))

def variants(q, lo, hi):
    op = qp.ttm(q["op_income"].astype(float)); rv = qp.ttm(q["revenue"].astype(float))
    yoy = cl._ttm_yoy(rv); win = op.tail(40)
    full = scan(win, yoy)
    inw = (win.index >= lo) & (win.index <= hi)
    masked = scan(win.mask(inw), yoy.mask((yoy.index >= lo) & (yoy.index <= hi)))
    # strict：只評估整段（高點到低點）都在窗外：窗前、窗後各自獨立掃描
    bef = scan(win[win.index < lo], yoy); aft = scan(win[win.index > hi], yoy)
    strict = (bef[0] or aft[0])
    return full, masked, strict

W = {"2022-23": (pd.Timestamp("2022-01-01"), pd.Timestamp("2023-12-31")),
     "2020-21": (pd.Timestamp("2020-01-01"), pd.Timestamp("2021-12-31"))}
cyc = [t for t in T if res[t].type == "cyclical"]
print("cyclical", len(cyc))
rows = []
for t in cyc:
    q = inputs[t].quarters
    r = {"ticker": t, "name": names.get(t), "industry": ind[t], "max_dd": res[t].metrics["max_dd"],
         "dd_peak": res[t].metrics["dd_peak"], "dd_trough": res[t].metrics["dd_trough"]}
    for k, (lo, hi) in W.items():
        full, masked, strict = variants(q, lo, hi)
        assert full[0] == res[t].metrics["contraction"], t
        r[f"masked_{k}"] = masked[0]; r[f"strict_{k}"] = strict
    rows.append(r)
d = pd.DataFrame(rows)
print("sanity ok（無遮罩 scan 與 baseline contraction 一致）")
out = []
for k in W:
    for v in ("masked", "strict"):
        n = int(d[f"{v}_{k}"].sum()); out.append({"排除": k, "做法": v, "仍成立": n, "比例%": 100 * n / len(d)})
print(tab(pd.DataFrame(out), 1))
# 峰谷年份分布
print("trough 年份:", d["dd_trough"].dt.year.value_counts().sort_index().to_dict())
print("peak 年份:", d["dd_peak"].dt.year.value_counts().sort_index().to_dict())
inwin = lambda s, lo, hi: (s >= lo) & (s <= hi)
lo, hi = W["2022-23"]
print("峰或谷落在2022-23:", int((inwin(d.dd_peak, lo, hi) | inwin(d.dd_trough, lo, hi)).sum()),
      " 谷在2022-23:", int(inwin(d.dd_trough, lo, hi).sum()), " 峰在2022-23:", int(inwin(d.dd_peak, lo, hi).sum()))
# 產業分布
for k in W:
    dep = d[~d[f"masked_{k}"]]; keep = d[d[f"masked_{k}"]]
    g = pd.DataFrame({"循環檔": d.groupby("industry").size(), f"仍成立": keep.groupby("industry").size(),
                      f"只靠{k}": dep.groupby("industry").size()}).fillna(0).astype(int)
    g["只靠%"] = 100 * g[f"只靠{k}"] / g["循環檔"]
    g = g.sort_values("循環檔", ascending=False)
    print(f"\n產業分布（masked {k}）"); print(tab(g.reset_index().head(14), 1))
    g.to_csv(OUT / f"s2_industry_{k}.csv", encoding="utf-8-sig")
dep = d[~d["masked_2022-23"]].sort_values("max_dd", ascending=False)
print("\n只靠 2022-23（masked 後不成立）檔數", len(dep), "；前20（依 max_dd）:")
print(tab(dep[["ticker", "name", "industry", "max_dd", "dd_peak", "dd_trough"]].head(20)))
dep2 = d[~d["strict_2022-23"]]
print("strict 後不成立檔數", len(dep2), " 其中前20:"); print(tab(dep2[["ticker", "name", "industry", "max_dd", "dd_peak", "dd_trough"]].head(20)))
d.to_csv(OUT / "s2_detail.csv", index=False, encoding="utf-8-sig")
# 同時只靠 2022-23 與 2020-21 皆不成立者
print("兩窗皆需要(masked 任一不成立):", int((~d["masked_2022-23"] | ~d["masked_2020-21"]).sum()))
