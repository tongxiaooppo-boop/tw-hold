"""實驗 B' · 價值清單組合層歷史回溯——port 版，只做價值線（HANDOFF §1.6）。

原始「實驗 B」（`research/backtest_rebalance.py`，2026-09-07）依賴的 `twswing.value`
套件已經搬進 tw-hold 自己的 `factors/`／`reference/`／`screener/`，原始腳本
`import twswing.value` 直接會炸（tw-swing 那邊已刪除這個子套件）。這支用 tw-hold
自己的模組重新接線：

    財報四表（tw-hold bundle） → reference.loader.load_quarterly
                               → factors.factors.quarterly_factors
    日線（tw-swing 本機 store，tw-hold 自己 bundle 的 prices_adj 只從 2023-05 起，
          長度不夠回溯 2016） → screener.screen.screen_value

**只做價值線**（使用者 2026-09-12 裁決：定存先不用——定存線還有填息率/含息報酬
兩道硬門檻要接 `raw` 未還原價格 + 股利表，範疇比較大，先不做）。

紀律照舊：
- 🔴 公告日遞延一定要套（`load_quarterly` 已內建 `disclosure_date = period_end + 45天`）。
- 🔴 生存者偏差：universe = 今天 bundle `universe.parquet` 的 `in_universe`
  （市值前500∪成交值前500，~610 檔），拿去回溯 2016 等於已知誰活到今天，報告當上界。
- 只跑基準版，不調參數湊過門檻。

用法：
    python research/backtest_value.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
TWSWING = Path(r"d:\g\claude\tw-swing")
sys.path.insert(0, str(TWSWING / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from twswing.data import store  # noqa: E402  只借日線母表，不碰 twswing.value

from factors.factors import quarterly_factors  # noqa: E402
from reference.loader import BUNDLE_DIR, load_quarterly  # noqa: E402
from screener.screen import screen_value  # noqa: E402

OUT = REPO / "docs" / "reports"
OUT.mkdir(parents=True, exist_ok=True)
COST = 0.00585           # tw-swing 口徑（來回）


def _bare(s: pd.Series) -> pd.Series:
    return s.astype(str).str.split(".").str[0]


def load_all():
    q = load_quarterly()
    qf = quarterly_factors(q)

    px = store.read_daily(recent=False, columns=["date", "ticker", "close"])
    px["ticker"] = _bare(px["ticker"])
    adj = px.pivot_table(index="date", columns="ticker", values="close").sort_index()

    uni_p = BUNDLE_DIR / "fundamentals" / "universe.parquet"
    uni_df = pd.read_parquet(uni_p, columns=["ticker", "in_universe"])
    universe = set(uni_df.loc[uni_df["in_universe"], "ticker"].astype(str))

    return qf, adj, universe


def rebal_dates(adj: pd.DataFrame) -> list[pd.Timestamp]:
    """季中換股：3/6/9/12 月的 15 日（或之後第一個交易日），2016 起。"""
    idx = adj.index
    out = []
    for y in range(2016, idx.max().year + 1):
        for m in (3, 6, 9, 12):
            d = pd.Timestamp(y, m, 15)
            nxt = idx[idx >= d]
            if len(nxt):
                out.append(nxt[0])
    return [d for d in out if d <= idx.max()]


def prices_asof(adj: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    row = adj.loc[adj.index[adj.index <= asof][-1]]
    p = pd.DataFrame({"close": row})
    p.index.name = "ticker"
    return p.reset_index()


def pick_value(qf: pd.DataFrame, adj: pd.DataFrame, asof: pd.Timestamp,
              universe: set[str]) -> tuple[list[str], int]:
    scr = screen_value(qf, prices=prices_asof(adj, asof), asof=asof)
    scr = scr[scr["ticker"].isin(universe)]
    ok = scr[scr["passes"]].sort_values("value_score", ascending=False)
    return ok["ticker"].tolist(), len(ok)


def fwd_ret(adj: pd.DataFrame, tickers: list[str], d0: pd.Timestamp, d1: pd.Timestamp) -> float:
    """等權持有 tickers 從 d0 到 d1 的還原（含息）報酬。停牌/下市（該區間無價）的
    自動剔除——**這會系統性高估**，生存者偏差的一部分，報告已註明結論當上界。"""
    if not tickers:
        return np.nan
    cols = [t for t in tickers if t in adj.columns]
    if not cols:
        return np.nan
    a = adj.loc[d0].reindex(cols)
    b = adj.loc[d1].reindex(cols)
    r = (b / a - 1.0).dropna()
    return r.mean() if len(r) else np.nan


def run_track(qf, adj, universe, dates, n):
    rows, prev = [], set()
    eq = 1.0
    curve = [(dates[0], 1.0)]
    for d0, d1 in zip(dates[:-1], dates[1:]):
        cands, n_ok = pick_value(qf, adj, d0, universe)
        held = cands[:n]
        gross = fwd_ret(adj, held, d0, d1)
        h = set(held)
        adds, drops = len(h - prev), len(prev - h)
        cost = (COST / 2) * (adds + drops) / max(1, len(held)) if held else 0.0
        turn = (adds + drops) / 2 / max(1, len(held)) if held else np.nan
        net = (gross - cost) if pd.notna(gross) else np.nan
        if pd.notna(net):
            eq *= (1 + net)
        curve.append((d1, eq))
        rows.append({"date": d0, "n_candidates": n_ok, "n_held": len(held),
                     "gross": gross, "turnover": turn, "net": net, "held": ",".join(held[:12])})
        prev = set(held)
    df = pd.DataFrame(rows)
    cv = pd.Series(dict(curve))
    yrs = (cv.index[-1] - cv.index[0]).days / 365.25
    cagr = cv.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else np.nan
    dd = (cv / cv.cummax() - 1).min()
    yr_last = cv.groupby(cv.index.year).last()
    yr_ret = yr_last / yr_last.shift(1) - 1
    return df, {"cagr": cagr, "maxdd": dd, "final": cv.iloc[-1],
               "med_cand": df["n_candidates"].median(),
               "blank": (df["n_candidates"] == 0).mean(),
               "avg_turn": df["turnover"].mean(),
               "yr_ret": yr_ret.dropna()}, cv


def bench(adj, dates, tk):
    if tk not in adj.columns:
        return None
    s = adj[tk].reindex(dates, method="ffill")
    r = s / s.iloc[0]
    yrs = (dates[-1] - dates[0]).days / 365.25
    return {"cagr": r.iloc[-1] ** (1 / yrs) - 1, "maxdd": (r / r.cummax() - 1).min()}


def main():
    qf, adj, universe = load_all()
    dates = rebal_dates(adj)
    print(f"換股日 {len(dates)} 個：{dates[0].date()} → {dates[-1].date()}")
    print(f"universe：{len(universe)} 檔（bundle universe.parquet in_universe）")

    md = ["# 實驗 B' · 價值清單組合層歷史回溯（port 版，只做價值線）", "",
         f"- 產出：{pd.Timestamp.now():%Y-%m-%d %H:%M}",
         "- 沿用實驗 B（2026-09-07）方法論，改用 tw-hold 自己的 factors/reference/"
         "screener 模組重新接線（原始 `research/backtest_rebalance.py` 依賴的 "
         "`twswing.value` 已被刪除，import 會炸——見 HANDOFF §1.6）",
         f"- 換股：季中（3/6/9/12 月 15 日），{dates[0].date()} → {dates[-1].date()}"
         f"（{len(dates)-1} 期）",
         f"- 成本：{COST:.3%} × 換手 × 2（來回）",
         f"- universe：{len(universe)} 檔（bundle `universe.parquet` `in_universe`，"
         "市值前500∪成交值前500——🔴 生存者偏差，結論當上界）",
         "- 定存線這輪沒做（使用者 2026-09-12 裁決）", ""]

    for n in (10, 20):
        df, stat, cv = run_track(qf, adj, universe, dates, n)
        b = bench(adj, dates, "0050")
        md += [f"## N = {n}", "",
              "| | 含息年化 | 最大回撤 | 每期候選(中位) | 空白期 | 平均換手 |",
              "| :-- | --: | --: | --: | --: | --: |",
              f"| **價值線** | {stat['cagr']:+.2%} | {stat['maxdd']:.1%} | "
              f"{stat['med_cand']:.0f} | {stat['blank']:.0%} | {stat['avg_turn']:.0%} |",
              (f"| 0050（含息） | {b['cagr']:+.2%} | {b['maxdd']:.1%} | — | — | — |"
               if b else "| 0050 | 資料缺 | | | | |"), "",
              "每期候選檔數：" + ", ".join(f"{r.date:%y-%m} {r.n_candidates}"
                                       for r in df.itertuples()), "",
              "分年含息報酬（策略）：" + ", ".join(f"{y} {v:+.0%}"
                                          for y, v in stat["yr_ret"].items()), ""]
        df.to_csv(OUT / f"backtest_value_{n}.csv", index=False)

    md += ["## 對照組：過硬門檻、不排序、等權全買（N=∞）", ""]
    df, stat, cv = run_track(qf, adj, universe, dates, 999)
    md += [f"- **價值線全買**：含息年化 {stat['cagr']:+.2%}、回撤 {stat['maxdd']:.1%}、"
          f"每期 {stat['med_cand']:.0f} 檔", ""]

    md += ["## 生存者偏差", "",
          "universe 是今天 bundle 的 `in_universe`（市值/成交值前段班），拿它回溯 2016 等於",
          "已知誰活到今天。免費層拿不到歷史成分股，這個偏差消不掉——**上面所有報酬數字都是",
          "上界**，真實結果會更差（下市、重大衰退的公司當年會在清單裡，這裡看不到）。", ""]

    out_md = OUT / "backtest_value_20260912.md"
    out_md.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"\n-> {out_md}")


if __name__ == "__main__":
    main()
