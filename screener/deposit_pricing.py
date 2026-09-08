"""定存清單的兩道新硬門檻（PRD §7.1）+ 殖利率法買價 / verdict（§7.3 / §7.4）。

§7.1 新增（v3.0 重定位——這條線接手美元收益部位，回撤容忍極低）：
  - 近 5 年平均**填息率 ≥ 60%**（賺息賠價差 = 假存股）
  - 近 3 年**含息年化報酬 ≥ 0**（NAV 在流血的高息 = 陷阱）

§7.3 買價：
  買入殖利率門檻 = max(該股近 5 年平均殖利率, 5.0%)   ← 硬底線 5%，不能自己放水到 4%
  估值買價       = 近 3 年平均現金股利 ÷ 買入殖利率門檻
  買入區間       = [max(季線, 20 週前低), min(估值買價, 現價)]，倒置同 §6.3

§7.4 verdict：現價殖利率 ≥ 門檻 且過所有硬門檻 → 推薦；否則 觀望 / 不推薦（原因）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from screener.pricing import _buy_range, price_levels

FILL_WINDOW = 60            # 除息後幾個交易日內算「填息」
FILL_RATE_MIN = 0.60       # §7.1
YIELD_FLOOR = 0.05         # §7.0.1 硬底線（不放水到 4%）
RET3Y_MIN = 0.0            # §7.1


def fill_rates(raw_hist: pd.DataFrame | None, div: pd.DataFrame,
               asof: pd.Timestamp, years: int = 5) -> pd.Series:
    """每檔近 `years` 年除息事件的完全填息比率：除息後 `FILL_WINDOW` 交易日內，
    未還原收盤曾回到除息前一日水準的事件佔比。raw 缺 → 空 Series。"""
    if raw_hist is None or raw_hist.empty:
        return pd.Series(dtype=float, name="fill_rate")
    raw = raw_hist.copy()
    raw["date"] = pd.to_datetime(raw["date"])
    raw["ticker"] = raw["ticker"].astype(str).str.split(".").str[0]
    wide = raw.pivot_table(index="date", columns="ticker", values="close").sort_index()

    lo = pd.Timestamp(asof) - pd.DateOffset(years=years)
    dv = div.copy()
    dv["ticker"] = dv["ticker"].astype(str)
    ev = dv[(dv["ex_date"] >= lo) & (dv["ex_date"] < asof) & (dv["cash_dividend"] > 0)]

    res: dict[str, float] = {}
    for tk, g in ev.groupby("ticker"):
        if tk not in wide.columns:
            continue
        s = wide[tk].dropna()
        hits = tot = 0
        for ex in g["ex_date"]:
            pre = s[s.index < ex]
            post = s[s.index >= ex].head(FILL_WINDOW)
            if pre.empty or post.empty:
                continue
            tot += 1
            if post.max() >= pre.iloc[-1]:
                hits += 1
        if tot:
            res[tk] = hits / tot
    return pd.Series(res, name="fill_rate")


def incl_div_return_3y(adj_hist: pd.DataFrame | None,
                       asof: pd.Timestamp) -> pd.Series:
    """近 3 年含息年化報酬（還原序列，還原序列已把配息再投入算進去）。"""
    if adj_hist is None or adj_hist.empty:
        return pd.Series(dtype=float, name="ret3y_incl")
    a = adj_hist.copy()
    a["date"] = pd.to_datetime(a["date"])
    a["ticker"] = a["ticker"].astype(str).str.split(".").str[0]
    wide = a.pivot_table(index="date", columns="ticker", values="close").sort_index()
    asof = pd.Timestamp(asof)
    past = wide.index[wide.index <= asof - pd.DateOffset(years=3)]
    now = wide.index[wide.index <= asof]
    if past.empty or now.empty:
        return pd.Series(dtype=float, name="ret3y_incl")
    return ((wide.loc[now[-1]] / wide.loc[past[-1]]) ** (1 / 3) - 1).rename("ret3y_incl")


def yield_history(per_hist: pd.DataFrame | None, asof: pd.Timestamp
                  ) -> pd.DataFrame:
    """每檔的殖利率統計（用 bundle `per.parquet` 的 `dividend_yield`，單位 %）：
    近 5 年均、近 3 年均、當前、當前在近 5 年區間的分位。"""
    cols = ["avg_yield_5y", "avg_yield_3y", "cur_yield_twse", "yield_pctile_5y"]
    if per_hist is None or per_hist.empty or "dividend_yield" not in per_hist.columns:
        return pd.DataFrame(columns=["ticker", *cols])
    d = per_hist.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["ticker"] = d["ticker"].astype(str).str.split(".").str[0]
    asof = pd.Timestamp(asof)
    d = d[(d["date"] <= asof) & (d["dividend_yield"] > 0)]
    lo5 = asof - pd.DateOffset(years=5)
    lo3 = asof - pd.DateOffset(years=3)
    out = {}
    for tk, g in d.groupby("ticker"):
        g5 = g[g["date"] >= lo5]["dividend_yield"]
        if g5.empty:
            continue
        cur = g.sort_values("date")["dividend_yield"].iloc[-1]
        out[tk] = {
            "avg_yield_5y": g5.mean() / 100.0,
            "avg_yield_3y": g[g["date"] >= lo3]["dividend_yield"].mean() / 100.0,
            "cur_yield_twse": cur / 100.0,
            "yield_pctile_5y": float((g5 <= cur).mean()),
        }
    return pd.DataFrame(out).T.rename_axis("ticker").reset_index()


def add_deposit_verdict(dep: pd.DataFrame, raw_hist: pd.DataFrame | None,
                        adj_hist: pd.DataFrame | None, per_hist: pd.DataFrame | None,
                        div: pd.DataFrame, asof: pd.Timestamp | None = None
                        ) -> pd.DataFrame:
    """在 `screen_deposit()` 結果上加 §7.1 兩道硬門檻 + §7.3 買價 + §7.4 verdict / 揭露欄。

    §7.1 門檻**只在資料齊時才擋**（raw 缺 → fill_rate NaN → 不擋，標記在 verdict）。
    """
    asof = pd.Timestamp(asof or pd.Timestamp.now()).normalize()
    d = dep.copy()
    d["reject_reason"] = d["reject_reason"].astype("object")
    tk = d["ticker"].astype(str)

    fr = fill_rates(raw_hist, div, asof)
    r3 = incl_div_return_3y(adj_hist, asof)
    yh = yield_history(per_hist, asof).set_index("ticker")
    lv = price_levels(adj_hist, asof).set_index("ticker") if adj_hist is not None \
        else pd.DataFrame(columns=["ma_quarter", "low_20w"])

    d["fill_rate"] = tk.map(fr) if len(fr) else np.nan
    d["ret3y_incl"] = tk.map(r3) if len(r3) else np.nan
    for c in ["avg_yield_5y", "avg_yield_3y", "cur_yield_twse", "yield_pctile_5y"]:
        d[c] = tk.map(yh[c]) if c in yh.columns else np.nan
    d["ma_quarter"] = tk.map(lv["ma_quarter"]) if "ma_quarter" in lv else np.nan
    d["low_20w"] = tk.map(lv["low_20w"]) if "low_20w" in lv else np.nan

    # §7.3：買入殖利率門檻、估值買價、現價殖利率（與買價同基礎：近 3 年均現金股利）
    d["yield_floor"] = np.maximum(d["avg_yield_5y"].fillna(0.0), YIELD_FLOOR)
    avg_div_3y = d.get("avg_cash_dividend_3y", np.nan)
    d["est_buy_price"] = avg_div_3y / d["yield_floor"]
    d["cur_yield"] = avg_div_3y / d["close"] if "close" in d.columns else np.nan

    # §7.1 兩道新硬門檻（剔除）——只在資料齊時擋，補進既有 reject_reason（NaN 的才寫）
    extra = {
        "填息率 < 60%（近5年）": d["fill_rate"].notna() & (d["fill_rate"] < FILL_RATE_MIN),
        "近3年含息報酬 < 0": d["ret3y_incl"].notna() & (d["ret3y_incl"] < RET3Y_MIN),
    }
    for label, mask in extra.items():
        hit = mask.fillna(False).to_numpy() & d["reject_reason"].isna().to_numpy()
        d.loc[hit, "reject_reason"] = label
    d["passes"] = d["reject_reason"].isna()

    # §7.4 verdict——現價殖利率 < 門檻 是「觀望」不是剔除（PRD §7.4）
    low_yield = d["cur_yield"].notna() & (d["cur_yield"] < d["yield_floor"])
    verdict = np.where(
        ~d["passes"], "不推薦（" + d["reject_reason"].astype("string") + "）",
        np.where(low_yield, "觀望（現價殖利率 " + (d["cur_yield"] * 100).round(1).astype("string")
                 + "% < 門檻 " + (d["yield_floor"] * 100).round(1).astype("string") + "%）",
                 "推薦"))
    # raw 缺 → 填息率沒驗到，「推薦」降級成「觀望」提醒
    if fr.empty or d["fill_rate"].isna().all():
        verdict = np.where((verdict == "推薦"), "觀望（填息率未驗，缺未還原股價）", verdict)
    d["verdict"] = pd.Series(verdict, index=d.index, dtype=object)

    # §7.3 買入區間——只有「推薦」才算
    rec = pd.Series(d["verdict"], index=d.index).str.startswith("推薦")
    lower = d[["ma_quarter", "low_20w"]].max(axis=1).where(rec)
    upper = d[["est_buy_price", "close"]].min(axis=1).where(rec) if "close" in d.columns \
        else pd.Series(np.nan, index=d.index)
    d = d.join(_buy_range(lower, upper))
    return d
