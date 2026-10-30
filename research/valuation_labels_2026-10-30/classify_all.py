"""（第一版標籤介面 label/turn_why/cycle_why；app 已改兩層 type/state，本檔不能直接重跑，留作紀錄。）
B1 全市場分類掃描：每檔跑 valuation.estimate()，收 label／high_pe → labels.csv，再產 summary.md。
執行：cd 專案根目錄；PYTHONIOENCODING=utf-8 python research/valuation_labels_2026-10-30/classify_all.py"""
import sys, warnings; warnings.filterwarnings("ignore")
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import numpy as np, pandas as pd, pyarrow.parquet as pq, pyarrow.compute as pc
import bundle_data as bd, valuation as v
from factors.factors import quarterly_factors

PICK = "2330 2317 2454 2603 2609 2615 1802 2408 2002 3481 6669 6588 8422 1301 2412 3661 3443".split()


def scan() -> tuple[pd.DataFrame, int]:
    tickers = sorted(set(pc.unique(pq.read_table(ROOT / "data/upstream/per.parquet",
                                                 columns=["ticker"])["ticker"]).to_pylist()))
    rows, failed = [], 0
    for t in tickers:
        try:
            fin = bd.financials(t)
            if fin.empty:
                continue
            r = v.estimate(quarterly_factors(fin), bd.revenue(t), bd.prices(t), bd.per_history(t))
            if not r.get("ok"):
                continue
            lb, hp = r["label"], r["high_pe"]
            rows.append({
                "ticker": t, "label": lb["label"], "turn_why": "；".join(lb["turn_why"]),
                "cycle_why": "；".join(lb["cycle_why"]), "ttm_eps": lb["ttm_eps"],
                "est": r["year"]["est"] if r["year"] else np.nan,
                "om_min": lb["om_min"], "om_max": lb["om_max"], "max_drop": lb["max_drop"],
                "cur_pe": r["cur_pe"]["pe"] if r["cur_pe"] else np.nan,
                "buy_state": r["buy"]["state"] if r["buy"] else "",
                "growth_price": r["growth_price"], "price": r["price"],
                "pe_min_3y": hp["pe_min_3y"], "pe_ref_high": hp["pe_ref_high"],
                "eps_fwd_growth": hp["eps_fwd_growth"], "eps_cagr_3y": hp["eps_cagr_3y"],
                "price_high_pe": hp["price_high_pe"], "upside_high_pe": hp["upside_high_pe"],
                "high_pe_eligible": hp["eligible"], "high_pe_fail": "；".join(hp["fail"]),
            })
        except Exception:
            failed += 1
    return pd.DataFrame(rows), failed


def _f(x, pct=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return ""
    if isinstance(x, (bool, np.bool_)):
        return "是" if x else "否"
    if isinstance(x, (int, np.integer)):
        return str(x)
    if isinstance(x, (int, float, np.floating, np.integer)):
        return f"{x:.0%}" if pct else f"{x:.2f}"
    return str(x)


PCT_COLS = {"max_drop", "eps_fwd_growth", "eps_cagr_3y", "upside_high_pe", "share"}


def md(df: pd.DataFrame, cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df[cols].iterrows():
        out.append("| " + " | ".join(_f(r[c], c in PCT_COLS) for c in cols) + " |")
    return "\n".join(out)


def summary(df: pd.DataFrame, failed: int) -> str:
    L = ["# B1 全市場估值標籤掃描（2026-10-30）", "",
         f"- 掃描成功 {len(df)} 檔，例外失敗 {failed} 檔。", ""]
    c = df["label"].value_counts().rename_axis("label").reset_index(name="n")
    c["share"] = c["n"] / len(df)
    L += ["## 三類檔數", "", md(c, ["label", "n", "share"]), ""]
    ct = pd.crosstab(df["label"], df["buy_state"].replace("", "(無)")).reset_index()
    L += ["## 標籤 × buy_state", "", md(ct, list(ct.columns)), ""]
    spread = (df["om_max"] - df["om_min"]).dropna()
    qs = [0.1, 0.25, 0.5, 0.75, 0.9]
    dist = pd.DataFrame({"百分位": [f"P{int(q*100)}" for q in qs],
                         "營益率區間寬": [f"{spread.quantile(q):.0%}" for q in qs],
                         "max_drop": [f"{df['max_drop'].dropna().quantile(q):.0%}" for q in qs]})
    L += ["## 特徵分布", "", md(dist, list(dist.columns)), ""]
    nt = df[df["label"] != "turnaround"]
    sp = nt["om_max"] - nt["om_min"]
    grid = {f"OM≥{s:.2f}": [int(((sp >= s) | (nt["max_drop"] >= d)).sum()) for d in (0.3, 0.4, 0.5)]
            for s in (0.15, 0.20, 0.25)}
    g = pd.DataFrame(grid, index=["DROP≥0.30", "DROP≥0.40", "DROP≥0.50"]).reset_index(names="")
    L += ["## 景氣循環門檻敏感度（非轉機股裡被判 cyclical 的檔數）", "", md(g, list(g.columns)), ""]
    base = ["ticker", "label", "turn_why", "cycle_why", "ttm_eps", "est", "max_drop", "om_min",
            "om_max", "buy_state"]
    pk = df[df["ticker"].isin(PICK)].set_index("ticker").reindex(PICK).dropna(how="all").reset_index()
    L += ["## 指定檔", "", md(pk, base), ""]
    for lab in ("turnaround", "cyclical", "normal"):
        s = df[df["label"] == lab]
        s = s.sample(min(10, len(s)), random_state=0)
        L += [f"### 抽樣：{lab}", "", md(s, base), ""]
    # 高本益比情境價
    hi = df[df["pe_min_3y"] > v.HIGH_PE_GATE]
    el = df[df["high_pe_eligible"]]
    L += ["## 高本益比情境價", "",
          f"- 近 3 年每年年均本益比都 > 30 的有 {len(hi)} 檔，其中全部條件過關 {len(el)} 檔。", ""]
    reasons = (hi[~hi["high_pe_eligible"]]["high_pe_fail"].str.split("；").explode()
               .str.replace(r"-?\d+(\.\d+)?%?", "N", regex=True).str.replace("近 N 年", "近 3 年").value_counts()
               .rename_axis("沒過的原因").reset_index(name="檔數"))
    L += ["### pe_min_3y > 30 但沒過關的原因（一檔可多條）", "", md(reasons, ["沒過的原因", "檔數"]), ""]

    def others_ok(s: str) -> bool:
        return all(x.startswith(("近 3 年年均本益比", "近 3 年最低年均本益比", "算不出情境價", "情境價"))
                   for x in s.split("；") if x)
    ok = df["high_pe_fail"].fillna("").map(others_ok)
    grid2 = {}
    for cap in (40, 50, 60):
        grid2[f"CAP {cap}"] = [int((ok & (df["pe_min_3y"] > gate)
                                    & (df["est"] * np.minimum(df["pe_min_3y"], cap) > df["price"])).sum())
                               for gate in (25, 30, 35)]
    g2 = pd.DataFrame(grid2, index=["GATE 25", "GATE 30", "GATE 35"]).reset_index(names="")
    L += ["### 敏感度：GATE × CAP 下過關檔數", "", md(g2, list(g2.columns)), ""]
    cols = ["ticker", "label", "pe_min_3y", "pe_ref_high", "ttm_eps", "est", "eps_fwd_growth",
            "eps_cagr_3y", "price", "price_high_pe", "upside_high_pe", "growth_price", "buy_state"]
    L += ["### 過關全部（依情境價高出現價幅度排序）", "",
          md(el.sort_values("upside_high_pe", ascending=False), cols), ""]
    L += ["### 指定檔（高本益比）", "",
          md(pk, ["ticker", "pe_min_3y", "price_high_pe", "upside_high_pe", "high_pe_eligible",
                  "high_pe_fail"]), ""]
    return "\n".join(L)


if __name__ == "__main__":
    if "--from-csv" in sys.argv:          # 只重產 summary（失敗檔數沿用 0，見 labels.csv 產出時的輸出）
        df, failed = pd.read_csv(OUT / "labels.csv", dtype={"ticker": str}), 0
        df["high_pe_eligible"] = df["high_pe_eligible"].astype(bool)
        df["buy_state"] = df["buy_state"].fillna("")
    else:
        df, failed = scan()
        df.to_csv(OUT / "labels.csv", index=False, encoding="utf-8-sig")
    (OUT / "summary.md").write_text(summary(df, failed), encoding="utf-8")
    print(len(df), failed)
