"""買價 + verdict（PRD §6.2 / §6.3；定存 §7.3 / §7.4 之後補）。

**這一層才把「候選 + 為什麼」變成「買價 + verdict」**——寫死、不調參（凍結條件 5）。

## 為什麼 verdict 只由「便宜門檻」一個數驅動

估值上緣（`TTM_EPS × P70`）是**參考、非預測**，PRD §6.3 明講「是天花板不是目標」。
一個進了 verdict 的數字就不再是參考——那正是 `me` 在小規模重演的死因。
所以估值上緣只算「空間 %」給展開明細看，**不進 verdict**。

## 盈餘基礎不對稱（站得住）

- 估值上緣用 `TTM_EPS`（當期，不外推）——不懲罰真成長股
- 便宜門檻用 `normalized_EPS`（近 5 年年度 EPS 均值）——攤平景氣循環、偏保守

景氣循環股獲利高峰時 `TTM_EPS / normalized_EPS > 1.5` → 明細標「估值上緣偏樂觀」。
旗標只顯示，不進公式、不進 verdict。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PE_YEARS = 5
CYCLICAL_PEAK_RATIO = 1.5
MA_QUARTER_DAYS = 60        # 季線 = 60 交易日均線
LOW_LOOKBACK_WEEKS = 20     # 近 20 週前低
#: normalized_EPS 隱含 PE 低於市場 PE 這個倍數 → 判 EPS 基準存疑（多半是股利/股本未還原）。
#: 只擋「算得太便宜」這一側——算得太貴頂多被排除，不會誤導成買點。
PE_DIVERGENCE_FLOOR = 0.5


def pe_percentiles(per_hist: pd.DataFrame, asof: pd.Timestamp,
                   years: int = PE_YEARS) -> pd.DataFrame:
    """每檔取近 `years` 年 `per` 序列的 P30 / P70。

    per_hist: `[ticker, date, per]`（bundle `fundamentals/per.parquet`）。
    只取 per > 0（虧損期 TWSE 報 0 或負，不是估值資訊）。樣本 < 60 個交易日 → NaN。
    """
    if per_hist is None or per_hist.empty:
        return pd.DataFrame(columns=["ticker", "pe_p30", "pe_p70"])
    d = per_hist.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["ticker"] = d["ticker"].astype(str).str.split(".").str[0]
    cutoff = pd.Timestamp(asof).normalize() - pd.DateOffset(years=years)
    d = d[(d["date"] >= cutoff) & (d["date"] <= pd.Timestamp(asof)) & (d["per"] > 0)]
    g = d.groupby("ticker")["per"]
    latest = d.sort_values("date").groupby("ticker")["per"].last()
    out = pd.DataFrame({
        "pe_p30": g.quantile(0.30),
        "pe_p70": g.quantile(0.70),
        "pe_market": latest,          # 最新市場 PE——拿來對照 normalized_EPS 有沒有算歪
        "_n": g.size(),
    })
    out.loc[out["_n"] < MA_QUARTER_DAYS, ["pe_p30", "pe_p70"]] = np.nan
    return out.drop(columns="_n").reset_index()


def price_levels(price_hist: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """每檔的季線（60 日均線）與近 20 週前低。

    price_hist: `[date, ticker, close]`（還原日線；build_factors._read_bundle_price_history）。
    """
    if price_hist is None or price_hist.empty:
        return pd.DataFrame(columns=["ticker", "ma_quarter", "low_20w"])
    d = price_hist.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["ticker"] = d["ticker"].astype(str).str.split(".").str[0]
    d = d[d["date"] <= pd.Timestamp(asof)].sort_values(["ticker", "date"])

    ma = (d.groupby("ticker")["close"]
            .apply(lambda s: s.tail(MA_QUARTER_DAYS).mean()
                   if len(s) >= MA_QUARTER_DAYS else np.nan)
            .rename("ma_quarter"))
    low_cut = pd.Timestamp(asof).normalize() - pd.Timedelta(weeks=LOW_LOOKBACK_WEEKS)
    low = (d[d["date"] >= low_cut].groupby("ticker")["close"].min().rename("low_20w"))
    return pd.concat([ma, low], axis=1).reset_index()


def _buy_range(lower: pd.Series, upper: pd.Series) -> pd.DataFrame:
    """買入區間 [下界, 上界]；下界 > 上界 → 不吐負寬度區間，改標支撐位（PRD §6.3 倒置處理）。

    §6.3 / §7.3 同一個處理。
    """
    inverted = lower.notna() & upper.notna() & (lower > upper)
    buy_low = np.where(inverted, np.nan, lower)
    buy_high = np.where(inverted, np.nan, upper)
    note = pd.Series(np.where(
        inverted,
        "支撐位（" + lower.round(1).astype("string") + "）已在買點之上 → 等回檔或等支撐下移",
        None), index=lower.index, dtype="object")
    return pd.DataFrame({"buy_low": buy_low, "buy_high": buy_high, "buy_note": note},
                        index=lower.index)


def add_value_verdict(val: pd.DataFrame, per_hist: pd.DataFrame | None,
                      price_hist: pd.DataFrame | None,
                      asof: pd.Timestamp | None = None) -> pd.DataFrame:
    """在 `screen_value()` 的結果上加：便宜門檻 / 估值上緣 / 空間 % / 循環高峰旗標 /
    verdict / 買入區間（PRD §6.2、§6.3）。

    缺 per_hist（P30/P70 算不出）→ verdict 退化為「資料不足」、不吐買價。
    """
    asof = pd.Timestamp(asof or pd.Timestamp.now()).normalize()
    d = val.copy()
    tk = d["ticker"].astype(str)

    new_cols = ["pe_p30", "pe_p70", "pe_market", "ma_quarter", "low_20w",
                "cheap_threshold", "valuation_ceiling", "upside_pct",
                "buy_low", "buy_high"]
    if {"close", "normalized_eps", "ttm_eps"} - set(d.columns):
        # 無股價（M0a 退化路徑）→ 買價 / verdict 全算不出，留空欄位、標「資料不足」
        for c in new_cols:
            d[c] = np.nan
        d["cyclical_peak_flag"] = False
        d["eps_basis_suspect"] = False
        d["buy_note"] = None
        d["verdict"] = np.where(d["passes"], "資料不足（無股價）", "不推薦（品質）")
        return d

    pe = pe_percentiles(per_hist, asof).set_index("ticker") if per_hist is not None \
        else pd.DataFrame(columns=["pe_p30", "pe_p70"])
    lv = price_levels(price_hist, asof).set_index("ticker") if price_hist is not None \
        else pd.DataFrame(columns=["ma_quarter", "low_20w"])

    d["pe_p30"] = tk.map(pe["pe_p30"]) if "pe_p30" in pe else np.nan
    d["pe_p70"] = tk.map(pe["pe_p70"]) if "pe_p70" in pe else np.nan
    d["pe_market"] = tk.map(pe["pe_market"]) if "pe_market" in pe else np.nan
    d["ma_quarter"] = tk.map(lv["ma_quarter"]) if "ma_quarter" in lv else np.nan
    d["low_20w"] = tk.map(lv["low_20w"]) if "low_20w" in lv else np.nan

    # normalized_EPS 有沒有算歪：隱含 PE 遠低於市場 PE = EPS 基準存疑（股利/股本未還原）
    implied_pe = d["close"] / d["normalized_eps"]
    d["eps_basis_suspect"] = (
        d["pe_market"].notna() & (implied_pe > 0)
        & (implied_pe < PE_DIVERGENCE_FLOOR * d["pe_market"]))

    # §6.2：盈餘基礎不對稱——便宜門檻用 normalized_EPS，估值上緣用 TTM_EPS
    d["cheap_threshold"] = d["normalized_eps"] * d["pe_p30"]
    d["valuation_ceiling"] = d["ttm_eps"] * d["pe_p70"]
    d["upside_pct"] = d["valuation_ceiling"] / d["close"] - 1.0
    d["cyclical_peak_flag"] = (d["ttm_eps"] / d["normalized_eps"]) > CYCLICAL_PEAK_RATIO

    # §6.3 verdict（由上往下，先命中先算）——估值上緣不進 verdict
    has_gate = d["cheap_threshold"].notna()
    verdict = pd.Series(np.nan, index=d.index, dtype="object")
    verdict = verdict.where(d["passes"], "不推薦（品質）")           # reject_reason 已載明細因
    verdict = verdict.mask(verdict.isna() & ~has_gate, "資料不足（PE 分位算不出）")
    verdict = verdict.mask(verdict.isna() & d["eps_basis_suspect"],
                           "資料不足（EPS 基準存疑）")
    verdict = verdict.mask(verdict.isna() & (d["close"] >= d["cheap_threshold"]),
                           "觀望（無安全邊際）")
    verdict = verdict.mask(verdict.isna(), "推薦")
    d["verdict"] = verdict

    # §6.3 買入區間——只有「推薦」才算；下界 max(季線, 20 週前低)、上界 min(便宜門檻, 現價)
    rec = d["verdict"] == "推薦"
    lower = d[["ma_quarter", "low_20w"]].max(axis=1).where(rec)
    upper = d[["cheap_threshold", "close"]].min(axis=1).where(rec)
    d = d.join(_buy_range(lower, upper))
    return d
