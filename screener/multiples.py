"""以個股自身歷史倍數分布估算價格帶；不代表內在價值。"""

from __future__ import annotations

import numpy as np
import pandas as pd


_QUANTILES = ("p20", "p50", "p80")


def _timestamp(value):
    """解析日期；有時區時保留當地日期時間並移除時區。"""
    if value is None:
        return None
    try:
        result = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(result):
        return None
    if result.tzinfo is not None:
        result = result.tz_localize(None)
    return result


def _number(value):
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return None if np.isnan(result) else result


def _daily_values(per, col):
    """先依輸入順序保留重複日期的最後一筆，再按日期排序。"""
    empty = pd.Series(
        index=pd.DatetimeIndex([], name="date"), dtype=float, name=col
    )
    if (
        per is None
        or col not in ("per", "pbr")
        or "date" not in per.columns
        or col not in per.columns
    ):
        return empty

    frame = per.loc[:, ["date", col]].copy()
    frame["date"] = frame["date"].map(_timestamp)
    frame = frame.dropna(subset=["date"]).drop_duplicates("date", keep="last")
    if frame.empty:
        return empty

    numeric = pd.to_numeric(frame[col], errors="coerce").astype(float)
    values = pd.Series(
        numeric.to_numpy(),
        index=pd.DatetimeIndex(frame["date"], name="date"),
        name=col,
        dtype=float,
    )
    return values.sort_index(kind="mergesort")


def _positive_values(values):
    return values.loc[values.notna() & (values > 0)]


def _monthly_last(values):
    if values.empty:
        return values.copy()
    return values.groupby(values.index.to_period("M"), sort=True).tail(1)


def month_end_values(per, col) -> pd.Series:
    """每月最後一個有效值；索引保留該值實際交易日，而非日曆月底。"""
    return _monthly_last(_positive_values(_daily_values(per, col)))


def band(per, col, years, min_months, cap=None, asof=None) -> dict:
    """計算含起訖日的歷史窗口分布。

    asof 存在時先排除其後日資料，再取各月最後有效值，避免前視。
    window_start/window_end 表示實際採用樣本的首末月份。
    """
    daily = _positive_values(_daily_values(per, col))
    if asof is not None:
        end = _timestamp(asof)
    else:
        end = None if daily.empty else daily.index[-1]

    if end is None:
        monthly = daily.iloc[:0]
    else:
        selected = daily.loc[daily.index <= end]
        if years is not None:
            start = end - pd.DateOffset(years=years)
            selected = selected.loc[selected.index >= start]
        monthly = _monthly_last(selected)

    n_months = len(monthly)
    raw = dict.fromkeys(_QUANTILES)
    if n_months:
        percentiles = np.percentile(
            monthly.to_numpy(dtype=float), [20, 50, 80]
        )
        raw = {
            key: _number(value)
            for key, value in zip(_QUANTILES, percentiles)
        }

    capped = {
        key: (
            None
            if value is None
            else value if cap is None else min(value, cap)
        )
        for key, value in raw.items()
    }
    truncated = bool(
        cap is not None
        and any(value is not None and value > cap for value in raw.values())
    )

    p20, p80 = raw["p20"], raw["p80"]
    if p20 is None or p80 is None:
        ratio = None
    elif p20 == p80:
        ratio = 1.0
    else:
        ratio = _number(p80 / p20)

    ok = n_months >= min_months
    return {
        "ok": bool(ok),
        "reason": (
            None
            if ok
            else f"有效月數不足（{n_months}/{min_months}）"
        ),
        "n_months": n_months,
        "window_start": (
            monthly.index[0].strftime("%Y-%m") if n_months else None
        ),
        "window_end": (
            monthly.index[-1].strftime("%Y-%m") if n_months else None
        ),
        "raw": raw,
        "capped": capped,
        "truncated": truncated,
        "ratio": ratio,
        "cap": cap,
    }


def prices(base, b) -> dict | None:
    base = _number(base)
    if base is None or base <= 0 or b is None or not b.get("ok", False):
        return None

    result = {}
    for name, quantile in zip(("cheap", "fair", "dear"), _QUANTILES):
        capped = _number(b["capped"][quantile])
        raw = _number(b["raw"][quantile])
        if capped is None or raw is None:
            return None
        result[name] = base * capped
        result[f"{name}_raw"] = base * raw
    return result


def high_pe_exception(per, yearly_eps, years=5, gate=30.0) -> bool:
    """檢查資料最後一年「之前」最近 years 個完整日曆年（**不含當年**）。

    當年財報未齊（例如 10 月只有 Q1、Q2），拿它的全年 EPS 當條件會讓放寬永遠不成立
    （2026-11-01 Opus 掃描抓到）。當年＝資料最後日期所屬年，不依賴系統時間。
    僅納入至少 20 個有效日的年份，且須有 years 個合格年份。
    """
    if years <= 0 or yearly_eps is None:
        return False

    daily = _daily_values(per, "per")
    if daily.empty:
        return False

    current_year = daily.index[-1].year
    valid = _positive_values(daily)
    valid = valid.loc[
        (valid.index.year >= current_year - years)
        & (valid.index.year < current_year)
    ]
    if valid.empty:
        return False

    yearly = valid.groupby(valid.index.year).agg(["count", "mean"])
    eligible = yearly.loc[yearly["count"] >= 20]
    if len(eligible) < years or not (eligible["mean"] > gate).all():
        return False

    for year in eligible.index:
        eps = _number(yearly_eps.get(int(year)))
        if eps is None or eps <= 0:
            return False
    return True


def classify_position(price, p) -> str:
    if p is None:
        return "na"

    price = _number(price)
    cheap = _number(p.get("cheap"))
    fair = _number(p.get("fair"))
    dear = _number(p.get("dear"))
    if any(value is None for value in (price, cheap, fair, dear)):
        return "na"
    if price < cheap:
        return "cheap"
    if price <= dear:
        return "fair"
    return "dear"
