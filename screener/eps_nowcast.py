# screener/eps_nowcast.py
# 假設：
# - 季別採曆季；輸入按日期排序後使用，同季／同月重複資料視為輸入無效。
# - 最近四季與歷史 TTM 必須連續；近八季指最後財報季起算的八個曆季，
#   其中至少須有四筆資料。季節偏差使用截至最後財報季的最近三年。
# - ni_parent 欄位缺少時，等同整欄 NaN，以 net_income 代替。
# - 非有限數值視為缺值；月營收最新月依輸入索引判定，不因該月缺值而前移。
# - g3 缺失使試算路徑失敗；k=0 的 eps_nc 仍可直接使用已公布 TTM。
# - 淨利合計為零時無法計算 m；營收或同比基期合計為零時無法計算比率。
# - 季節偏差的符號以 numpy.sign 判定，零與正／負數視為不同符號。
# - ok 表示基礎參數有效且至少有一個可用的 eps_nc／eps_f4；
#   試算失敗但能退回 TTM 時仍可為 True。基礎參數無法推算則為 False。
# - NC 退回時明細改列 TTM；失敗且無可用明細的路徑回傳空 list。
#   f4_far_quarters 計算整個 F4 視窗中的遠季數，即使 F4 試算失敗也保留。

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


QUARTERS_PER_YEAR = 4
MONTHS_PER_QUARTER = 3
TTM_QUARTERS = 4
F4_QUARTERS = 4
HISTORY_QUARTERS = 8
MIN_HISTORY_QUARTERS = 4
SEASONAL_YEARS = 3
MIN_SEASONAL_OBSERVATIONS = 2
G3_MONTHS = 3
G12_MONTHS = 12
FAR_GROWTH_FACTOR = 0.5
MIN_TAX_RATE = 0.0
MAX_TAX_RATE = 0.35
DEFAULT_TAX_RATE = 0.20
MIN_ABS_EPS = 0.05
LARGE_MINORITY_RATIO = 0.30
MAX_NC_K = 3

FALLBACK_FLAG = "EPS_NC 退回已公布 TTM"
PARAM_NAMES = (
    "t",
    "m",
    "shares",
    "gm_ttm",
    "opex_ratio",
    "nonop_med",
    "g3",
    "g12",
    "g_far",
)
NUMERIC_COLUMNS = (
    "revenue",
    "gross_profit",
    "op_income",
    "pretax_income",
    "net_income",
    "ni_parent",
    "eps",
)
REQUIRED_COLUMNS = ("period_end",) + tuple(
    name for name in NUMERIC_COLUMNS if name != "ni_parent"
)


def _empty_result() -> dict[str, Any]:
    return {
        "ok": False,
        "reason": None,
        "last_q": None,
        "last_month": None,
        "k": None,
        "eps_ttm": None,
        "eps_nc": None,
        "nc_quarters": [],
        "eps_f4": None,
        "f4_quarters": [],
        "f4_far_quarters": 0,
        "params": dict.fromkeys(PARAM_NAMES),
        "flags": [],
        "fallback": False,
    }


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _flag(result: dict[str, Any], text: str) -> None:
    if text not in result["flags"]:
        result["flags"].append(text)


def _fail(result: dict[str, Any], reason: str) -> dict[str, Any]:
    result["ok"] = False
    result["reason"] = reason
    _flag(result, reason)
    return result


def _finite(frame: pd.DataFrame, columns: tuple[str, ...]) -> bool:
    return bool(np.isfinite(frame.loc[:, list(columns)].to_numpy(dtype=float)).all())


def _normalize_q(q: pd.DataFrame) -> pd.DataFrame:
    data = q.copy(deep=True)
    dates = pd.DatetimeIndex(pd.to_datetime(data.pop("period_end"), errors="coerce"))
    if dates.hasnans:
        raise ValueError("財報日期無效")
    if dates.tz is not None:
        dates = dates.tz_localize(None)
    periods = dates.to_period("Q-DEC")
    if periods.has_duplicates:
        raise ValueError("財報季度重複")
    data.index = periods
    if "ni_parent" not in data:
        data["ni_parent"] = np.nan
    for column in NUMERIC_COLUMNS:
        data[column] = pd.to_numeric(data[column], errors="coerce").astype(float)
    data["ni_parent"] = data["ni_parent"].fillna(data["net_income"])
    return data.sort_index()


def _normalize_monthly(monthly: pd.Series) -> pd.Series:
    dates = pd.DatetimeIndex(pd.to_datetime(monthly.index, errors="coerce"))
    if dates.hasnans:
        raise ValueError("月營收日期無效")
    if dates.tz is not None:
        dates = dates.tz_localize(None)
    periods = dates.to_period("M")
    if periods.has_duplicates:
        raise ValueError("月營收月份重複")
    values = pd.to_numeric(monthly, errors="coerce").to_numpy(dtype=float)
    return pd.Series(values, index=periods, dtype=float).sort_index()


def _growth(monthly: pd.Series, window: int) -> float | None:
    if monthly.empty:
        return None
    current_index = pd.period_range(
        end=monthly.index[-1], periods=window, freq="M"
    )
    current = monthly.reindex(current_index).to_numpy(dtype=float)
    previous = monthly.reindex(current_index - G12_MONTHS).to_numpy(dtype=float)
    if not np.isfinite(current).all() or not np.isfinite(previous).all():
        return None
    current_sum = _number(current.sum())
    previous_sum = _number(previous.sum())
    if current_sum is None or previous_sum is None or previous_sum == 0:
        return None
    return _number(current_sum / previous_sum - 1)


def _ttm_frame(q: pd.DataFrame, end: pd.Period) -> pd.DataFrame:
    return q.reindex(
        pd.period_range(end=end, periods=TTM_QUARTERS, freq="Q-DEC")
    )


def _gross_margin(frame: pd.DataFrame) -> float | None:
    if not _finite(frame, ("revenue", "gross_profit")):
        return None
    revenue = _number(frame["revenue"].sum())
    profit = _number(frame["gross_profit"].sum())
    if revenue is None or revenue == 0 or profit is None:
        return None
    return _number(profit / revenue)


def _seasonal_bias(q: pd.DataFrame, target: pd.Period) -> float:
    first = q.index[-1] - (SEASONAL_YEARS * QUARTERS_PER_YEAR - 1)
    observations = []
    for period in q.index[q.index >= first]:
        if period.quarter != target.quarter:
            continue
        quarter_margin = _gross_margin(q.loc[[period]])
        historical_ttm_margin = _gross_margin(_ttm_frame(q, period))
        if quarter_margin is None or historical_ttm_margin is None:
            continue
        deviation = _number(quarter_margin - historical_ttm_margin)
        if deviation is not None:
            observations.append(deviation)
    if len(observations) < MIN_SEASONAL_OBSERVATIONS:
        return 0.0
    signs = np.sign(observations)
    if not np.all(signs == signs[0]):
        return 0.0
    return float(np.mean(observations))


def _actual_details(
    q: pd.DataFrame, periods: pd.PeriodIndex
) -> list[dict[str, Any]] | None:
    details = []
    for period in periods:
        if period not in q.index:
            return None
        row = q.loc[period]
        eps = _number(row["eps"])
        if eps is None:
            return None
        pretax = _number(row["pretax_income"])
        op = _number(row["op_income"])
        details.append(
            {
                "q": str(period),
                "kind": "actual",
                "eps": eps,
                "rev": _number(row["revenue"]),
                "gm": _gross_margin(q.loc[[period]]),
                "op": op,
                "nonop": (
                    _number(pretax - op)
                    if pretax is not None and op is not None
                    else None
                ),
            }
        )
    return details


def _sum_eps(details: list[dict[str, Any]] | None) -> float | None:
    if details is None:
        return None
    return _number(sum(item["eps"] for item in details))


def _calibrate(q: pd.DataFrame, result: dict[str, Any]) -> str | None:
    params = result["params"]
    last = q.index[-1]
    recent = _ttm_frame(q, last)
    gm = _gross_margin(recent)
    if gm is None or not _finite(recent, ("gross_profit", "op_income")):
        return "最近四季財報缺季或缺值，無法計算 TTM 參數"

    revenue_sum = float(recent["revenue"].sum())
    opex = _number(
        (recent["gross_profit"] - recent["op_income"]).sum() / revenue_sum
    )
    if opex is None:
        return "營業費損率無法計算"
    params["gm_ttm"] = gm
    params["opex_ratio"] = opex

    shares_candidates = []
    for _, row in recent.iterrows():
        eps = _number(row["eps"])
        ni_parent = _number(row["ni_parent"])
        if eps is None or ni_parent is None or abs(eps) < MIN_ABS_EPS:
            continue
        candidate = _number(ni_parent / eps)
        if candidate is not None and candidate > 0:
            shares_candidates.append(candidate)
    if not shares_candidates:
        return "股數推不出"
    shares = _number(np.median(shares_candidates))
    if shares is None or shares <= 0:
        return "股數推不出"
    params["shares"] = shares

    history = q.loc[q.index >= last - (HISTORY_QUARTERS - 1)]
    required = ("op_income", "pretax_income", "net_income", "ni_parent")
    if len(history) < MIN_HISTORY_QUARTERS or not _finite(history, required):
        return "近八季有效財報不足，無法計算業外、稅率或少數股權比"

    nonop = _number(
        np.median(
            (history["pretax_income"] - history["op_income"]).to_numpy(dtype=float)
        )
    )
    pretax_sum = _number(history["pretax_income"].sum())
    net_sum = _number(history["net_income"].sum())
    parent_sum = _number(history["ni_parent"].sum())
    if any(value is None for value in (nonop, pretax_sum, net_sum, parent_sum)):
        return "業外、稅率或少數股權比無法計算"

    tax = 0.0 if pretax_sum <= 0 else _number(1 - net_sum / pretax_sum)
    if tax is None:
        return "有效稅率無法計算"
    if not MIN_TAX_RATE <= tax <= MAX_TAX_RATE:
        tax = DEFAULT_TAX_RATE
        _flag(result, "稅率超界，改用 20%")

    if net_sum == 0:
        return "淨利合計為零，少數股權比無法計算"
    minority = _number(1 - parent_sum / net_sum)
    if minority is None:
        return "少數股權比無法計算"
    if abs(minority) > LARGE_MINORITY_RATIO:
        _flag(result, "少數股權比重大")

    params.update(t=tax, m=minority, nonop_med=nonop)
    return None


def _quarter_months(period: pd.Period) -> pd.PeriodIndex:
    return pd.period_range(
        start=period.asfreq("M", how="start"),
        periods=MONTHS_PER_QUARTER,
        freq="M",
    )


def _has_monthly(monthly: pd.Series, period: pd.Period) -> bool:
    return bool(
        np.isfinite(monthly.reindex(_quarter_months(period)).to_numpy(dtype=float))
        .any()
    )


def _estimate(
    q: pd.DataFrame,
    monthly: pd.Series,
    period: pd.Period,
    result: dict[str, Any],
) -> dict[str, Any] | None:
    params = result["params"]
    if params["g3"] is None:
        _flag(result, "近三月或去年同期月營收不足，無法計算 g3")
        return None

    if _has_monthly(monthly, period):
        revenue = 0.0
        for month in _quarter_months(period):
            value = _number(monthly.get(month, np.nan))
            if value is None:
                previous = _number(monthly.get(month - G12_MONTHS, np.nan))
                if previous is None:
                    _flag(result, f"{period} 去年同月營收缺漏：{month - G12_MONTHS}")
                    return None
                value = previous * (1 + params["g3"])
            revenue += value
    else:
        previous_period = period - QUARTERS_PER_YEAR
        if previous_period not in q.index:
            _flag(result, f"{period} 去年同季財報營收缺漏")
            return None
        previous_revenue = _number(q.loc[previous_period, "revenue"])
        if previous_revenue is None:
            _flag(result, f"{period} 去年同季財報營收缺漏")
            return None
        revenue = previous_revenue * (1 + params["g_far"])

    gm = params["gm_ttm"] + _seasonal_bias(q, period)
    op = revenue * gm - params["opex_ratio"] * revenue
    eps = (
        (op + params["nonop_med"])
        * (1 - params["t"])
        * (1 - params["m"])
        / params["shares"]
    )
    if any(_number(value) is None for value in (revenue, gm, op, eps)):
        _flag(result, f"{period} 試算 EPS 或中間值非有限值")
        return None

    return {
        "q": str(period),
        "kind": "est",
        "eps": float(eps),
        "rev": float(revenue),
        "gm": float(gm),
        "op": float(op),
        "nonop": params["nonop_med"],
    }


def _fallback(
    result: dict[str, Any], ttm_details: list[dict[str, Any]] | None
) -> None:
    result["eps_nc"] = result["eps_ttm"]
    result["nc_quarters"] = ttm_details or []
    result["fallback"] = True
    _flag(result, FALLBACK_FLAG)


def _calculate(
    q: pd.DataFrame,
    monthly: pd.Series,
    g_far_zero: bool,
    result: dict[str, Any],
) -> dict[str, Any]:
    if not q.columns.is_unique or not set(REQUIRED_COLUMNS).issubset(q.columns):
        return _fail(result, "財報缺少必要欄位或欄位重複")
    if q.empty:
        return _fail(result, "財報資料為空")
    if not isinstance(monthly, pd.Series):
        return _fail(result, "monthly 必須是 Series")

    q = _normalize_q(q)
    monthly = _normalize_monthly(monthly)
    last = q.index[-1]
    result["last_q"] = last.end_time.normalize()
    if not monthly.empty:
        latest_month = monthly.index[-1]
        result["last_month"] = latest_month.start_time
        result["k"] = max(0, latest_month.asfreq("Q-DEC").ordinal - last.ordinal)
    if not np.isfinite(monthly.to_numpy(dtype=float)).all():
        _flag(result, "月營收有非有限值，視為缺值")

    params = result["params"]
    params["g3"] = _growth(monthly, G3_MONTHS)
    params["g12"] = _growth(monthly, G12_MONTHS)
    params["g_far"] = (
        0.0
        if g_far_zero or params["g12"] is None
        else _number(params["g12"] * FAR_GROWTH_FACTOR)
    )
    if params["g12"] is None:
        _flag(result, "近十二月或去年同期月營收不足，遠季成長率用 0")

    ttm_periods = pd.period_range(end=last, periods=TTM_QUARTERS, freq="Q-DEC")
    ttm_details = _actual_details(q, ttm_periods)
    result["eps_ttm"] = _sum_eps(ttm_details)
    if result["eps_ttm"] is None:
        ttm_details = None
        _flag(result, "已公布 TTM EPS 缺季或缺值")

    future = pd.period_range(
        start=last + 1, periods=F4_QUARTERS, freq="Q-DEC"
    )
    result["f4_far_quarters"] = sum(
        not _has_monthly(monthly, period) for period in future
    )

    k = result["k"]
    if k == 0:
        result["eps_nc"] = result["eps_ttm"]
        result["nc_quarters"] = ttm_details or []

    calibration_error = _calibrate(q, result)
    if calibration_error is not None:
        if k != 0:
            _fallback(result, ttm_details)
        return _fail(result, calibration_error)

    estimates = {
        period: _estimate(q, monthly, period, result) for period in future
    }
    f4_details = [estimates[period] for period in future]
    if all(detail is not None for detail in f4_details):
        eps_f4 = _sum_eps(f4_details)
        if eps_f4 is None:
            _flag(result, "F4 EPS 合計非有限值")
        else:
            result["eps_f4"] = eps_f4
            result["f4_quarters"] = f4_details

    if k is None:
        _flag(result, "沒有月營收最新月，無法判定滾動季數")
        _fallback(result, ttm_details)
    elif k > MAX_NC_K:
        _flag(result, "月營收超前財報超過三季")
        _fallback(result, ttm_details)
    elif k > 0:
        actual_periods = pd.period_range(
            end=last, periods=TTM_QUARTERS - k, freq="Q-DEC"
        )
        actual = _actual_details(q, actual_periods)
        estimated = [estimates[period] for period in future[:k]]
        if actual is None:
            _flag(result, "滾動四季的實際 EPS 缺季或缺值")
        if actual is None or any(detail is None for detail in estimated):
            _fallback(result, ttm_details)
        else:
            details = actual + estimated
            eps_nc = _sum_eps(details)
            if eps_nc is None:
                _flag(result, "滾動四季 EPS 合計非有限值")
                _fallback(result, ttm_details)
            else:
                result["eps_nc"] = eps_nc
                result["nc_quarters"] = details

    result["ok"] = (
        result["eps_nc"] is not None or result["eps_f4"] is not None
    )
    if not result["ok"]:
        return _fail(result, "無法取得可用的前瞻 EPS 或已公布 TTM")
    return result


def nowcast(
    q: pd.DataFrame,
    monthly: pd.Series,
    g_far_zero: bool = False,
) -> dict:
    """用已公布單季財報及月營收，試算滾動四季與未來四季 EPS。"""
    if not isinstance(q, pd.DataFrame):
        raise TypeError("q 必須是 DataFrame")

    result = _empty_result()
    try:
        return _calculate(q, monthly, g_far_zero, result)
    except Exception:
        # 僅 q 的型別錯誤向外拋出；其餘不合法或無法運算的輸入安全降級。
        return _fail(result, "輸入資料格式或數值無法處理")
