"""實驗 B · 價值/定存清單的組合層歷史回溯（tw-hold/docs/BACKTEST_HANDOFF.md §3）。

**這個實驗值 300 萬，而且它可能會說「不要做」。**

問題：如果從 2015 年就照 PRD §6（價值）§7（定存）的規則季換股，10 年結果是什麼？

紀律：
- 🔴 公告日遞延一定要套（財報 period_end + 45 天、股利 announce_date）——沒套＝未來函數。
- 🔴 生存者偏差：universe = 今天的前 ~500 大 → 報告當上界看待。
- 只跑基準版，不調參數湊過門檻。基準版不好看照實回報。

⚠️ 研究腳本不是產品碼——直接 import tw-swing 的 twswing.value / twswing.data。

用法：
    python research/backtest_rebalance.py            # 兩條線都跑，N=10 與 20
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

TWSWING = Path(r"d:\g\claude\tw-swing")
sys.path.insert(0, str(TWSWING / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from twswing.data import store
from twswing.value import factors, loader, screen

OUT = Path(__file__).resolve().parent.parent / "docs" / "reports"
OUT.mkdir(parents=True, exist_ok=True)
RAW_PRICES = TWSWING / "data" / "fundamentals" / "prices_raw.parquet"
COST = 0.00585           # tw-swing 口徑（來回）
FILL_WINDOW = 60         # 填息率：除息後幾個交易日內填息
DEPOSIT_YIELD_FLOOR = 0.05   # §7.0.1 硬底線


# ───────────────────────── 資料 ─────────────────────────

def load_all():
    q = loader.load_quarterly()
    q["ticker"] = q["ticker"].astype(str)
    qf = factors.quarterly_factors(q)
    ann = factors.annual_eps(q)

    div = loader.load_dividends()
    div["ticker"] = div["ticker"].astype(str)

    # 財報/股利表的 ticker 是裸代號（1101）；日線是 1101.TW → 全部統一成裸代號
    px = store.read_daily(recent=False, columns=["date", "ticker", "close"])
    px["ticker"] = px["ticker"].astype(str).str.split(".").str[0]
    adj = px.pivot_table(index="date", columns="ticker", values="close").sort_index()

    raw = None
    if RAW_PRICES.exists():
        r = pd.read_parquet(RAW_PRICES)
        r["ticker"] = r["ticker"].astype(str).str.split(".").str[0]
        raw = r.pivot_table(index="date", columns="ticker", values="close").sort_index()
    return qf, ann, div, adj, raw


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


# ─────────────────── 定存線的新增門檻（填息率 / 含息報酬）───────────────────

def fill_rates(raw: pd.DataFrame, div: pd.DataFrame, asof: pd.Timestamp,
               years: int = 5) -> pd.Series:
    """每檔近 `years` 年除息事件的**完全填息比率**（除息後 FILL_WINDOW 交易日內
    未還原收盤回到除息前一日水準的事件佔比）。raw 缺 → 全 NaN。"""
    if raw is None:
        return pd.Series(dtype=float)
    lo = asof - pd.DateOffset(years=years)
    ev = div[(div["ex_date"] >= lo) & (div["ex_date"] < asof) & (div["cash_dividend"] > 0)]
    res = {}
    for tk, g in ev.groupby("ticker"):
        if tk not in raw.columns:
            continue
        s = raw[tk].dropna()
        hits = tot = 0
        for ex in g["ex_date"]:
            pre = s[s.index < ex]
            post = s[(s.index >= ex)].head(FILL_WINDOW)
            if pre.empty or post.empty:
                continue
            tot += 1
            if post.max() >= pre.iloc[-1]:
                hits += 1
        if tot:
            res[tk] = hits / tot
    return pd.Series(res, name="fill_rate")


def incl_div_return_3y(adj: pd.DataFrame, asof: pd.Timestamp) -> pd.Series:
    """近 3 年含息年化報酬（用還原序列）。"""
    lo = adj.index[adj.index <= asof - pd.DateOffset(years=3)]
    if lo.empty:
        return pd.Series(dtype=float)
    a = adj.loc[lo[-1]]
    b = adj.loc[adj.index[adj.index <= asof][-1]]
    return ((b / a) ** (1 / 3) - 1).rename("ret3y_incl")


# ───────────────────────── 選股 ─────────────────────────

def prices_asof(adj: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """asof 當日（或之前最近一交易日）的收盤，`[ticker, close]`。
    capital_stock 由 screen 自己從 qf 讀（已 merge 進 load_quarterly）。"""
    row = adj.loc[adj.index[adj.index <= asof][-1]]
    p = pd.DataFrame({"close": row})
    p.index.name = "ticker"
    return p.reset_index()


def pick_value(qf, adj, asof, n):
    scr = screen.screen_value(qf, prices=prices_asof(adj, asof), asof=asof)
    ok = scr[scr["passes"]].sort_values("value_score", ascending=False)
    return ok["ticker"].tolist(), len(ok)


def pick_deposit(qf, ann, div, adj, raw, asof, n):
    d0 = div[div["announce_date"] <= asof]
    divf = factors.dividend_factors(d0, ann_eps=ann)
    # §7.3 殖利率：近 3 年平均現金股利 ÷ 現價
    row = adj.loc[adj.index[adj.index <= asof][-1]]
    divf = divf.set_index("ticker")
    divf["close"] = row.reindex(divf.index)
    divf["cur_yield"] = divf["avg_cash_dividend_3y"] / divf["close"]

    prices = prices_asof(adj, asof)
    ann_vol = (adj.pct_change().loc[:asof].tail(252).std() * np.sqrt(252)).rename("ann_vol")
    scr = screen.screen_deposit(
        qf, divf.reset_index()[["ticker", "div_years", "div_cut_5y",
                                "last_cash_dividend", "avg_cash_dividend_3y",
                                "earnings_div_ratio", "payout_ratio_ttm"]],
        prices=prices, vol=ann_vol.reset_index().rename(columns={"index": "ticker", 0: "ann_vol"}),
        asof=asof)
    scr = scr.merge(divf["cur_yield"].reset_index(), on="ticker", how="left")

    # 額外硬門檻（§7.1）：殖利率 ≥ 5%、填息率 ≥ 60%、近 3 年含息報酬 ≥ 0
    fr = fill_rates(raw, div, asof)
    r3 = incl_div_return_3y(adj, asof)
    scr["fill_rate"] = scr["ticker"].map(fr) if len(fr) else np.nan
    scr["ret3y_incl"] = scr["ticker"].map(r3) if len(r3) else np.nan
    extra_ok = (
        scr["passes"]
        & (scr["cur_yield"] >= DEPOSIT_YIELD_FLOOR)
        & (scr["fill_rate"].isna() | (scr["fill_rate"] >= 0.60))   # raw 缺就不擋
        & (scr["ret3y_incl"].isna() | (scr["ret3y_incl"] >= 0))
    )
    ok = scr[extra_ok].sort_values("safety_score", ascending=False)
    return ok["ticker"].tolist(), len(ok), (scr, fr.notna().any())


# ───────────────────────── 回溯 ─────────────────────────

def fwd_ret(adj, tickers, d0, d1):
    """等權持有 tickers 從 d0 到 d1 的含息報酬。停牌/下市（該區間無價）的
    自動剔除——**這會系統性高估**（真實情況是那些部位歸零或流動性折價），
    生存者偏差的一部分，報告已註明結論當上界。"""
    if not tickers:
        return np.nan
    cols = [t for t in tickers if t in adj.columns]
    if not cols:
        return np.nan
    a = adj.loc[d0].reindex(cols)
    b = adj.loc[d1].reindex(cols)
    r = (b / a - 1.0).dropna()
    return r.mean() if len(r) else np.nan


def run_track(name, picker, qf, ann, div, adj, raw, dates, n):
    rows, prev = [], set()
    eq = 1.0
    curve = [(dates[0], 1.0)]
    for d0, d1 in zip(dates[:-1], dates[1:]):
        picked = picker(qf, ann, div, adj, raw, d0, n)
        cands = picked[0]
        n_ok = picked[1]
        held = cands[:n]
        gross = fwd_ret(adj, held, d0, d1)
        h = set(held)
        adds, drops = len(h - prev), len(prev - h)
        # 成本：每筆單邊 COST/2。本期買 adds 檔、賣 drops 檔 → (adds+drops) 筆單邊。
        cost = (COST / 2) * (adds + drops) / max(1, len(held)) if held else 0.0
        turn = (adds + drops) / 2 / max(1, len(held)) if held else np.nan  # 揭露用（單向）
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
    # 分年含息報酬（該年最後一點 / 前一年最後一點 − 1）
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
    qf, ann, div, adj, raw = load_all()
    dates = rebal_dates(adj)
    print(f"換股日 {len(dates)} 個：{dates[0].date()} → {dates[-1].date()}")
    print(f"raw prices（填息率用）：{'有' if raw is not None else '🔴 缺（F3 未跑，定存線的填息率/近3年報酬門檻先略過）'}")

    md = ["# 實驗 B · 價值/定存組合層歷史回溯", "",
          f"- 產出：{pd.Timestamp.now():%Y-%m-%d %H:%M}",
          f"- 換股：季中（3/6/9/12 月 15 日），{dates[0].date()} → {dates[-1].date()}（{len(dates)-1} 期）",
          f"- 成本：{COST:.3%} × 換手 × 2（來回）",
          f"- universe：data/fundamentals（今天的前 ~500 大，🔴 生存者偏差、結論當上界）",
          f"- 填息率資料：{'已接' if raw is not None else '🔴 缺（F3 未跑）——定存線少兩道硬門檻'}", ""]

    def pv(qf, ann, div, adj, raw, d0, n): return pick_value(qf, adj, d0, n)
    def pd_(qf, ann, div, adj, raw, d0, n):
        r = pick_deposit(qf, ann, div, adj, raw, d0, n); return r[0], r[1]

    for n in (10, 20):
        md += [f"## N = {n}", ""]
        for label, picker, bmk in [("價值", pv, "0050"), ("定存", pd_, "0056")]:
            df, stat, cv = run_track(label, picker, qf, ann, div, adj, raw, dates, n)
            b = bench(adj, dates, bmk)
            md += [f"### {label}線（N={n}）· 對照 {bmk}", "",
                   f"| | 含息年化 | 最大回撤 | 每期候選(中位) | 空白期 | 平均換手 |",
                   f"| :-- | --: | --: | --: | --: | --: |",
                   f"| **{label}線** | {stat['cagr']:+.2%} | {stat['maxdd']:.1%} | "
                   f"{stat['med_cand']:.0f} | {stat['blank']:.0%} | {stat['avg_turn']:.0%} |",
                   f"| {bmk}（含息） | {b['cagr']:+.2%} | {b['maxdd']:.1%} | — | — | — |"
                   if b else f"| {bmk} | 資料缺 | | | | |", "",
                   "每期候選檔數："
                   + ", ".join(f"{r.date:%y-%m} {r.n_candidates}" for r in df.itertuples()), "",
                   "分年含息報酬（策略）："
                   + ", ".join(f"{y} {v:+.0%}" for y, v in stat["yr_ret"].items()), ""]
            df.to_csv(OUT / f"rebalance_{label}_{n}.csv", index=False)

    # 對照組：等權買下**所有**過硬門檻的（看排序有沒有貢獻）
    md += ["## 對照組：過硬門檻、不排序、等權全買（N=∞）", ""]
    for label, picker, bmk in [("價值", pv, "0050"), ("定存", pd_, "0056")]:
        df, stat, cv = run_track(label, picker, qf, ann, div, adj, raw, dates, 999)
        md += [f"- **{label}線 全買**：含息年化 {stat['cagr']:+.2%}、回撤 {stat['maxdd']:.1%}、"
               f"每期 {stat['med_cand']:.0f} 檔", ]
    md += ["", "## 生存者偏差", "",
           "universe 是今天的前 ~500 大，用它回溯 2016 等於已知誰活到今天。",
           "免費層拿不到歷史成分股，這個偏差消不掉——**上面所有報酬數字都是上界**，",
           "真實結果會更差（下市、重大衰退的公司當年會在清單裡，這裡看不到）。", ""]

    (OUT / "rebalance_backtest_20260907.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"\n-> {OUT / 'rebalance_backtest_20260907.md'}")


if __name__ == "__main__":
    main()
