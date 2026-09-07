"""實驗 D · 主動選股候選池每週剩幾檔（tw-hold/docs/BACKTEST_HANDOFF.md §2.6）。

**這不是回測，是可行性普查。** 規格 tw-hold/PRD.md §5.2。
問題：CANSLIM（歐尼爾）+ Minervini 趨勢模板 全部寫成「狀態」，逐週回掃
2016–2026，每週前 500 大裡剩幾檔。判準：中位數 1–5 檔、空白週 < 30% = 可行。

⚠️ 研究腳本不是產品碼——直接 import tw-swing 的 twswing.value / twswing.data。
⚠️ 生存者偏差：universe = 今天的前 ~514 大（data/fundamentals），拿它回掃
   2016 等於已知誰活到今天。報告要寫明、結論當上界。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

TWSWING = Path(r"d:\g\claude\tw-swing")
sys.path.insert(0, str(TWSWING / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from twswing.data import fundamentals as fd
from twswing.data import market as mkt
from twswing.data import regime as rg
from twswing.data import store
from twswing.value import factors, loader

OUT = Path(__file__).resolve().parent.parent / "docs" / "reports"
OUT.mkdir(parents=True, exist_ok=True)

# CANSLIM 門檻（PRD §5.2.1）
EPS_YOY_MIN = 0.25          # 最近一季 EPS YoY > 25%
ROE_MIN = 0.15             # ROE > 15%（TTM）
FSCORE_MIN = 6
RS_PCTILE_MIN = 70        # Minervini ⑧ RS 排名 > 70（vs 0050，橫斷面百分位）
INST_WINDOW = 20          # 法人近 20 交易日淨買超


def _weekly_dates(daily: pd.DataFrame) -> pd.DatetimeIndex:
    """每週最後一個交易日（週五或其代理），2016-01 起。"""
    d = pd.DatetimeIndex(pd.to_datetime(daily["date"]).drop_duplicates().sort_values())
    d = d[d >= "2016-01-01"]
    s = pd.Series(d, index=d)
    return pd.DatetimeIndex(s.groupby(d.to_period("W")).last().values)


def build_trend_template(daily: pd.DataFrame, idx: pd.Series) -> pd.DataFrame:
    """Minervini 八條，全部只要日線 + 0050。回傳 [date,ticker, t1..t8, trend_pass]。"""
    px = daily.pivot_table(index="date", columns="ticker", values="close").sort_index()
    ma50 = px.rolling(50).mean()
    ma150 = px.rolling(150).mean()
    ma200 = px.rolling(200).mean()
    lo52 = px.rolling(252).min()
    hi52 = px.rolling(252).max()
    ret126 = px / px.shift(126) - 1.0
    idx126 = idx / idx.shift(126) - 1.0
    rel = ret126.sub(idx126.reindex(px.index), axis=0)           # 相對 0050 的 126 日超額
    rs_pctile = rel.rank(axis=1, pct=True) * 100                  # 橫斷面百分位

    t1 = (px > ma150) & (px > ma200)
    t2 = ma150 > ma200
    t3 = ma200 > ma200.shift(21)
    t4 = (ma50 > ma150) & (ma150 > ma200)
    t5 = px > ma50
    t6 = px >= lo52 * 1.30
    t7 = px >= hi52 * 0.75
    t8 = rs_pctile > RS_PCTILE_MIN
    cnt = (t1.astype(float) + t2 + t3 + t4 + t5 + t6 + t7 + t8)

    out = pd.DataFrame({
        "trend_cnt": cnt.stack(),
        "trend_pass": (cnt >= 8).stack(),
    }).reset_index().rename(columns={"level_0": "date", "level_1": "ticker"})
    return out


def main() -> int:
    daily = store.read_daily(recent=False, columns=["date", "ticker", "close"])
    idx = mkt.market_close(recent=False)
    idx.index = pd.to_datetime(idx.index)

    daily["ticker"] = daily["ticker"].astype(str)

    # universe = data/fundamentals 有的股票（今天的前 ~514 大；生存者偏差已知）
    # 財報表的 ticker 是裸代號（1101），日線/月營收/籌碼是 1101.TW → 統一
    code2t = fd._code_to_ticker_map()
    q = loader.load_quarterly()
    q["ticker"] = q["ticker"].astype(str).map(lambda c: code2t.get(c, c + ".TW"))
    universe = sorted(q["ticker"].unique())
    daily = daily[daily["ticker"].isin(universe)].copy()

    qf = factors.quarterly_factors(q).sort_values(["ticker", "period_end"])
    g = qf.groupby("ticker", sort=False)
    qf["eps_yoy_q"] = qf["eps"] / g["eps"].shift(4) - 1.0
    qf["ttm_eps_3y"] = g["ttm_eps"].shift(12)
    qf["gm_p1"] = g["gross_margin"].shift(1)
    qf["gm_p2"] = g["gross_margin"].shift(2)

    rev = fd.load_revenue_features()
    inst = pd.read_parquet(store.STORE_DIR / "inst.parquet",
                           columns=["date", "ticker", "trust_net", "foreign_net"])
    inst = inst.dropna(subset=["ticker"])
    inst["net"] = inst["trust_net"].fillna(0) + inst["foreign_net"].fillna(0)
    inst = inst.sort_values(["ticker", "date"])
    inst["net20"] = (inst.groupby("ticker")["net"]
                     .rolling(INST_WINDOW, min_periods=INST_WINDOW).sum()
                     .reset_index(level=0, drop=True))

    trend = build_trend_template(daily, idx)
    trend = trend.set_index(["date", "ticker"])

    weeks = _weekly_dates(daily)
    rev_s = rev.sort_values("available_date")

    recs = []
    for wk in weeks:
        # 基本面：已公告最新一期
        qq = qf[qf["disclosure_date"] <= wk].groupby("ticker").tail(1)
        f_ok = (
            (qq["eps_yoy_q"] > EPS_YOY_MIN)
            & (qq["ttm_eps"] > qq["ttm_eps_3y"]) & (qq["ttm_eps"] > 0)
            & (qq["roe"] > ROE_MIN)
            & ~((qq["gross_margin"] < qq["gm_p1"]) & (qq["gm_p1"] < qq["gm_p2"]))
            & (qq["f_score"] >= FSCORE_MIN)
        )
        fset = set(qq.loc[f_ok.fillna(False), "ticker"])

        # 月營收：available_date <= wk 的最新一筆
        rr = rev_s[rev_s["available_date"] <= wk].groupby("ticker").tail(1)
        r_ok = (rr["revenue_yoy"] > 0) & (rr["revenue_accel"])
        rset = set(rr.loc[r_ok.fillna(False), "ticker"])

        # 法人 20 日淨買超 > 0（wk 當日或之前最近一筆）
        ii = inst[inst["date"] <= wk].groupby("ticker").tail(1)
        iset = set(ii.loc[ii["net20"] > 0, "ticker"])

        # 趨勢模板 8/8（wk 當日）
        try:
            td = trend.xs(wk, level="date")
            tset = set(td.index[td["trend_pass"].fillna(False)])
            tset5 = set(td.index[td["trend_cnt"].fillna(0) >= 5])
        except KeyError:
            tset, tset5 = set(), set()

        allpass = fset & rset & iset & tset
        recs.append({
            "week": wk, "fund": len(fset), "rev": len(rset), "inst": len(iset),
            "trend8": len(tset), "trend5": len(tset5),
            "fund_rev": len(fset & rset),
            "fund_rev_inst": len(fset & rset & iset),
            "all": len(allpass),
            "names": ",".join(sorted(allpass)[:20]),
        })

    df = pd.DataFrame(recs)
    reg = rg.classify(idx).reindex(pd.DatetimeIndex(df["week"]), method="ffill")
    df["regime"] = reg.values

    csv = OUT / "candidate_pool_survey.csv"
    df.to_csv(csv, index=False)

    def stats(s):
        return (f"中位數 {s.median():.0f}｜平均 {s.mean():.1f}｜P90 {s.quantile(.9):.0f}｜"
                f"max {s.max():.0f}｜空白週 {(s == 0).mean():.0%}｜週數 {len(s)}")

    lines = ["# 實驗 D · 主動選股候選池每週剩幾檔", "",
             f"- 產出：{pd.Timestamp.now():%Y-%m-%d %H:%M}",
             f"- 期間：{df['week'].min():%Y-%m-%d} → {df['week'].max():%Y-%m-%d}（{len(df)} 週）",
             f"- universe：{len(universe)} 檔（data/fundamentals，今天的前 ~514 大——"
             "🔴 生存者偏差，結論當上界）",
             f"- 門檻：EPS YoY > {EPS_YOY_MIN:.0%}、ROE > {ROE_MIN:.0%}、F-Score ≥ {FSCORE_MIN}、"
             f"月營收 YoY>0 且加速、法人 {INST_WINDOW} 日淨買超>0、Minervini 8/8", "",
             "## 全部條件都過（CANSLIM + 趨勢模板 8/8 + 月營收 + 法人）", "",
             f"**{stats(df['all'])}**", "",
             "## 各層單獨過幾檔（看哪一關在卡）", "",
             f"| 層 | 統計 |", "| :--- | :--- |",
             f"| 基本面（EPS/ROE/F-Score/毛利） | {stats(df['fund'])} |",
             f"| 月營收 YoY>0 且加速 | {stats(df['rev'])} |",
             f"| 法人 20 日淨買超>0 | {stats(df['inst'])} |",
             f"| 趨勢模板 8/8 | {stats(df['trend8'])} |",
             f"| 趨勢模板 ≥5/8 | {stats(df['trend5'])} |",
             f"| 基本面 ∩ 月營收 | {stats(df['fund_rev'])} |",
             f"| 基本面 ∩ 月營收 ∩ 法人 | {stats(df['fund_rev_inst'])} |", "",
             "## 分市況（全部條件都過）", ""]
    for k in rg.ORDER:
        sub = df[df["regime"] == k]["all"]
        if len(sub):
            lines.append(f"- **{rg.LABELS[k]}**（{len(sub)} 週）：{stats(sub)}")
    lines += ["", "## 分年（全部條件都過）", "",
              "| 年 | 中位數 | 空白週 | 最多 |", "| ---: | ---: | ---: | ---: |"]
    df["yr"] = df["week"].dt.year
    for y, sub in df.groupby("yr"):
        lines.append(f"| {y} | {sub['all'].median():.0f} | "
                     f"{(sub['all'] == 0).mean():.0%} | {sub['all'].max():.0f} |")
    lines += ["", "## 抽樣：候選名單（人工看合不合理）", ""]
    for tgt in ["2017-06", "2020-07", "2021-11", "2022-10", "2024-06"]:
        row = df[df["week"].dt.strftime("%Y-%m") == tgt]
        if len(row):
            r = row.iloc[0]
            lines.append(f"- **{r['week']:%Y-%m-%d}**（{r['all']} 檔）：{r['names'] or '（空）'}")

    md = OUT / "candidate_pool_survey.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n-> {md}\n-> {csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
