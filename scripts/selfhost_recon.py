"""自建上游 P3 對帳：自建還原價（adj_prices.parquet）vs 上游 data_pack 還原價，只比近 250 個交易日。

## 為什麼只比近 250 日、而且要「歸因」
上游有已知缺陷（還原接縫、現增口徑不同、單日異常、2015–16 舊歷史雜訊，見 docs/data-qu.md §2），
所以「兩邊不一致」不等於我們錯。這支腳本只回答：**不一致的檔，是不是都能歸到已知原因？歸不到的（unexplained）才是要人看的。**

## 方法
對每檔：r(d) = 上游收盤 / 自建還原收盤，除以最後一日的 r（兩邊最後一天都等於未還原收盤，理論上 r=1）；
`max_dev` = 窗內 |r−1| 最大值。分類（優先序）：
| status | 條件 |
| :-- | :-- |
| `ok` | max_dev ≤ TOL（0.2%） |
| `upstream_seam` | 已先把 `status=seam` 的上游接縫用官方因子訂正；訂正後仍對不上、且該檔窗內有 `seam_unverifiable`（無法驗證，人工看）才放行 |
| `factor_diff` | 該檔窗內事件為 `seam_factor_diff`（現增口徑：上游階梯約官方 0.81 倍）或事件含現增 |
| `single_day` | 偏離只出現在 ≤ 2 個交易日（母表單日異常） |
| `upstream_unadjusted` | 上游在窗內整段＝官方未還原價（完全沒還原；自建有事件、上游沒套）→ 上游缺陷 |
| `upstream_no_capital_adj` | 把該檔窗內減資／面額變更／分割的官方因子乘到上游 ex 日之前就對上（≤ TOL）→ 上游沒還原這類事件 |
| `pending_event` | 事件日晚於最後實價日（或事件表尚無該檔事件），且最近 10 個交易日之前完全一致、只有尾端才偏離 → 多半是「明天除權息」，上游前一晚已套用；隔天重跑事件表後應變 ok |
| `upstream_stepwise` | r 為分段常數（每段 ≥2 天），段數 ≤ 窗內事件數＋1 → 上游只把事件套到最近幾天（階梯式接縫），自建一致、上游不一致 |
| `unexplained` | 以上皆非 → **要人看** |

## 輸入／輸出
- 上游快照：`--upstream-dir`（預設 `D:\\g\\claude\\books\\n\\data`，內含 `<代號>.TW(O).csv`，欄 Date,Open,High,Low,Close,Volume）
- 自建：`data/selfhost/adj_prices.parquet`；事件分類：`data/selfhost/seam_events.csv`（先跑 `selfhost_seam_check.py`）
- 輸出：`data/derived/selfhost_recon.json`（彙總＋ unexplained 清單前 200 檔）、`data/selfhost/recon_detail.csv`（逐檔）

用法：
    python scripts/selfhost_recon.py [--upstream-dir DIR] [--days 250] [--tol 0.002]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "data" / "selfhost"
OUT_JSON = ROOT / "data" / "derived" / "selfhost_recon.json"
OUT_CSV = SH / "recon_detail.csv"
DEFAULT_UP = Path(r"D:\g\claude\books\n\data")


def load_upstream(d: Path) -> pd.DataFrame:
    rows = []
    for f in d.glob("*.csv"):
        parts = f.name.split(".")
        if len(parts) != 3 or parts[1] not in ("TW", "TWO") or not parts[0].isdigit():
            continue                                    # 非價格檔（benchmark、log…）
        u = pd.read_csv(f)
        if "Date" not in u or "Close" not in u:
            continue
        rows.append(pd.DataFrame({"date": pd.to_datetime(u["Date"]), "ticker": parts[0], "up": u["Close"]}))
    return pd.concat(rows, ignore_index=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream-dir", default=str(DEFAULT_UP))
    ap.add_argument("--days", type=int, default=250)
    ap.add_argument("--tol", type=float, default=0.002)
    a = ap.parse_args(argv)

    ours = pd.read_parquet(SH / "adj_prices.parquet", columns=["ticker", "date", "close", "raw_close"])
    ours["date"] = pd.to_datetime(ours["date"])
    ours["ticker"] = ours["ticker"].astype(str)
    up = load_upstream(Path(a.upstream_dir))
    j = ours.merge(up, on=["ticker", "date"])
    cal = np.sort(j["date"].unique())
    last = pd.Timestamp(cal[-1])
    win = pd.Timestamp(cal[-a.days]) if len(cal) >= a.days else pd.Timestamp(cal[0])
    j = j[j["date"] >= win].sort_values(["ticker", "date"])
    # 先把上游「已偵測到的接縫」還原：status=seam 的事件，階梯日 S 之前的上游列乘官方因子（與 selfhost_seam_check 的訂正同法）。
    # 這樣 upstream_seam 不再是「一律放過」，而是「訂正後仍對不上才算問題」
    ev0 = pd.read_csv(SH / "seam_events.csv", dtype={"ticker": str})
    sm = ev0[(ev0["status"] == "seam")].dropna(subset=["seam_date"])
    j["up_raw"] = j["up"]
    for t, g in sm.groupby("ticker"):
        m = j["ticker"] == t
        if not m.any():
            continue
        for _, e in g.iterrows():
            j.loc[m & (j["date"] < pd.Timestamp(e["seam_date"])), "up"] *= e["fac"]
    j["r"] = j["up"] / j["close"]
    j["rn"] = j["r"] / j.groupby("ticker")["r"].transform("last")
    j["dev"] = (j["rn"] - 1).abs()
    print(f"窗口 {win.date()}～{last.date()}（{a.days} 個交易日）；上游檔 {up['ticker'].nunique()}、自建 {ours['ticker'].nunique()}、對上 {j['ticker'].nunique()} 檔")

    ev = pd.read_csv(SH / "seam_events.csv", dtype={"ticker": str})
    ev["ex_eff"] = pd.to_datetime(ev["ex_eff"])
    ev = ev[ev["ex_eff"] >= win - pd.Timedelta(days=20)]
    seam_t = set(ev.loc[ev["status"] == "seam_unverifiable", "ticker"])   # seam 已在上面訂正；只有「無法驗證」的才放行
    fdiff_t = set(ev.loc[(ev["status"] == "seam_factor_diff") | (ev["type"].isin(["ex_rights", "ex_both"])), "ticker"])

    # 上游沒還原「減資／面額變更／分割」（Close＝未還原價，見 data-qu.md；tw-hold 另有手動對照表補）：
    # 對 unexplained 的檔，把這類事件的官方因子乘到上游 ex 日之前，若因此對上（≤ tol）→ 確認為 upstream_no_capital_adj，不是我們錯
    ca = pd.read_parquet(SH / "corp_actions.parquet", columns=["ticker", "date", "type", "factor"])
    ca["ticker"] = ca["ticker"].astype(str)
    ca["date"] = pd.to_datetime(ca["date"])
    ca = ca[ca["type"].isin(["cap_reduction", "par_change", "split"]) & (ca["date"] > win)]
    ca = ca.drop_duplicates(["ticker", "date", "type"])

    def cap_adj_dev(g: pd.DataFrame, t: str) -> float:
        up2 = g["up"].to_numpy().copy()
        for _, e in ca[ca["ticker"] == t].iterrows():
            up2[(g["date"] < e["date"]).to_numpy()] *= e["factor"]
        r = up2 / g["close"].to_numpy()
        return float(np.abs(r / r[-1] - 1).max())

    # 窗內（官方）事件數：上游「只套最近幾天」會讓 r 變成分段常數，段數不超過事件數＋1
    allev = pd.read_parquet(SH / "corp_actions.parquet", columns=["ticker", "date"])
    allev["ticker"] = allev["ticker"].astype(str)
    allev["date"] = pd.to_datetime(allev["date"])
    future_t = set(allev.loc[allev["date"] > last, "ticker"])          # 事件日晚於最後一個實價日（例 2614 於 10-06 除權息）
    allev = allev[(allev["date"] > win) & (allev["date"] <= last)].drop_duplicates()
    evn = allev.groupby("ticker").size().to_dict()

    def _stepwise(rn: np.ndarray, max_runs: int) -> bool:
        lv = np.round(rn, 3)
        runs = 1 + int((lv[1:] != lv[:-1]).sum())
        # 每段至少 2 天（單日跳動不算階梯）
        idx = np.flatnonzero(np.r_[True, lv[1:] != lv[:-1], True])
        return runs <= max_runs and int(np.diff(idx).min()) >= 2

    recent_cut = pd.Timestamp(cal[-10])

    def _tail_only(g: pd.DataFrame, cut: pd.Timestamp, tol: float) -> bool:
        """最近 10 日之前上游與自建完全一致（以窗口起點為基準），只有尾端才偏離（r 最後一日不等於 1）。"""
        r = g["r"].to_numpy()
        head = g["date"].to_numpy() < np.datetime64(cut)
        return bool(head.sum() >= 20 and np.abs(r[head] / r[head][0] - 1).max() <= tol and abs(r[-1] / r[head][0] - 1) > tol)

    recs = []
    for t, g in j.groupby("ticker"):
        dev = g["dev"].to_numpy()
        bad = dev > a.tol
        mx = float(dev.max())
        if mx <= a.tol:
            st = "ok"
        elif t in seam_t:
            st = "upstream_seam"
        elif t in fdiff_t:
            st = "factor_diff"
        elif int(bad.sum()) <= 2:
            st = "single_day"
        elif float((g["up_raw"] / g["raw_close"] - 1).abs().max()) <= a.tol:
            st = "upstream_unadjusted"       # 上游這檔在窗內＝未還原價（完全沒做還原；常見於窗內有減資／面額變更／分割）
        elif t in set(ca["ticker"]) and cap_adj_dev(g, t) <= a.tol:
            st = "upstream_no_capital_adj"
        elif (t in future_t or t not in evn) and _tail_only(g, recent_cut, a.tol):
            st = "pending_event"             # 偏離只出現在最近幾天、且我們事件表沒有該檔事件：上游（Yahoo）在除權息日前一晚就把事件套進歷史（例 2614，10-06 除權息）
        elif _stepwise(g["rn"].to_numpy(), int((evn.get(t, 0))) + 1):
            st = "upstream_stepwise"
        else:
            st = "unexplained"
        recs.append({"ticker": t, "n": len(g), "max_dev": round(mx, 5), "bad_days": int(bad.sum()),
                     "first_bad": str(g.loc[bad, "date"].iloc[0].date()) if bad.any() else "", "status": st})
    d = pd.DataFrame(recs)
    d.to_csv(OUT_CSV, index=False)
    cnt = d["status"].value_counts().to_dict()
    un = d[d["status"] == "unexplained"].sort_values("max_dev", ascending=False)
    res = {"schema": 1, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "window": [str(win.date()), str(last.date())], "days": a.days, "tol": a.tol,
           "tickers_compared": int(len(d)), "counts": cnt,
           "unexplained_top": un.head(200).to_dict("records")}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("分類：", cnt)
    print(f"→ {OUT_JSON}、{OUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
