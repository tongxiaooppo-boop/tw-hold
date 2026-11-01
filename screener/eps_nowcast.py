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
# - ok 表示基礎參數有效且至少有一個可用的 eps_nc／eps_future；
#   試算失敗但能退回 TTM 時仍可為 True。基礎參數無法推算則為 False。
# - NC 退回時明細改列 TTM；失敗且無可用明細的路徑回傳空 list。

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


QUARTERS_PER_YEAR = 4
MONTHS_PER_QUARTER = 3
TTM_QUARTERS = 4
FUTURE_QUARTERS = 4
# 候選值，未經事先登記重播驗證
FUTURE_G_FACTOR = 0.5
FUTURE_MULT_CAP = 1.30
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
# 試算季口徑（使用者 2026-11-01 拍板）：
#   "latest"＝毛利率、費用率取最新一季，不加季節偏差；沒有月營收的遠季營收維持最近一季水準。
#   "ttm"＝舊口徑（近四季合計毛利率＋季節偏差；遠季＝去年同季×(1+g_far)），保留作新舊對比與回滾。
TRIAL_BASIS = "latest"
# 驗證前僅為候選門檻；只標示高變動，不調整任何試算數字。
VAR_REV_QOQ = 0.30
VAR_GM_PP = 0.05
VAR_EPS_X = 2.0
TRIAL_BASIS_TEXT = {
    "latest": "前瞻 4 季：實際、月營收推算及營收沿用。\n"
              "試算採最新季毛利率與費用率，排除業外。",
    "ttm": "前瞻 4 季：沿用舊口徑推算。",
}
FUTURE_TEXT = ("未來 4 季：沿用前瞻末兩季，再以近 12 月營收年增的一半逐季成長，預測兩季。"
               "營收、最新季淨利與營業利益都年增才給；成長上限 1.3 倍；規則未經驗證。")

FALLBACK_FLAG = "前瞻 4 季退回過去 4 季 EPS"
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
    "gm_last",
    "opex_last",
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
        "basis": TRIAL_BASIS,
        "variability": {"flag": False, "reasons": [], "metrics": {}},
        "reason": None,
        "last_q": None,
        "last_month": None,
        "k": None,
        "eps_ttm": None,
        "eps_nc": None,
        "nc_quarters": [],
        "eps_future": None,
        "future_quarters": [],
        "future_status": "no_data",
        "ttm_quarters": [],
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


def _variability(q: pd.DataFrame) -> dict[str, Any]:
    """對照連續曆季；近零 EPS 不作倍數判斷。"""
    recent = _ttm_frame(q, q.index[-1])
    last, previous = recent.iloc[-1], recent.iloc[-2]
    metrics = {"rev_qoq": None, "gm_pp": None, "eps_x": None}
    reasons = []
    rev, prev_rev = _number(last["revenue"]), _number(previous["revenue"])
    if rev is not None and prev_rev is not None and prev_rev != 0:
        metrics["rev_qoq"] = rev / prev_rev - 1
        if abs(metrics["rev_qoq"]) >= VAR_REV_QOQ:
            reasons.append("營收季增減達 30%")
    gm = _gross_margin(recent.iloc[[-1]])
    prev_gm = _gross_margin(recent.iloc[[-2]])
    if gm is not None and prev_gm is not None:
        metrics["gm_pp"] = gm - prev_gm
        if abs(metrics["gm_pp"]) >= VAR_GM_PP or math.isclose(abs(metrics["gm_pp"]), VAR_GM_PP):
            reasons.append("毛利率季差達 5 個百分點")
    positive = [v for value in recent.iloc[:-1]["eps"]
                if (v := _number(value)) is not None and v > 0]
    eps = _number(last["eps"])
    if len(positive) >= 2:
        median = float(np.median(positive))
        if median >= MIN_ABS_EPS and eps is not None and eps >= MIN_ABS_EPS:
            metrics["eps_x"] = eps / median
            if metrics["eps_x"] > VAR_EPS_X:
                reasons.append("最新季 EPS 超過前三季正 EPS 中位數 2 倍")
    return {"flag": bool(reasons), "reasons": reasons, "metrics": metrics}


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
    last_row = q.loc[[last]]
    last_revenue = _number(last_row["revenue"].iloc[0])
    gm_last = _gross_margin(last_row)
    if last_revenue is not None and last_revenue > 0 and gm_last is not None:
        params["gm_last"] = gm_last
        params["opex_last"] = _number(
            (last_row["gross_profit"].iloc[0] - last_row["op_income"].iloc[0])
            / last_revenue
        )

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
    flat_revenue: float | None = None,
    basis: str = "ttm",
) -> dict[str, Any] | None:
    params = result["params"]
    latest = basis == "latest"
    if latest and (params["gm_last"] is None or params["opex_last"] is None):
        _flag(result, "最新一季毛利率／費用率缺值")
        return None
    has_monthly = _has_monthly(monthly, period)
    if params["g3"] is None and (not latest or has_monthly):
        _flag(result, "近三月或去年同期月營收不足，無法計算 g3")
        return None

    if has_monthly:
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
    elif latest and flat_revenue is not None:
        revenue = flat_revenue
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

    if latest:
        gm = params["gm_last"]
        opex_ratio = params["opex_last"]
    else:
        gm = params["gm_ttm"] + _seasonal_bias(q, period)
        opex_ratio = params["opex_ratio"]
    gp = revenue * gm
    opex = opex_ratio * revenue
    op = gp - opex
    # "latest" 口徑與估值展開表一致：試算季排除業外（使用者 2026-10-29 主版本）；舊 "ttm" 口徑加近 8 季中位數。
    nonop = 0.0 if latest else params["nonop_med"]
    conv = (1 - params["t"]) * (1 - params["m"])
    net = (op + nonop) * conv
    # 舊口徑保留原有運算順序。
    eps = ((op + nonop) * (1 - params["t"]) * (1 - params["m"])
           / params["shares"])
    if any(_number(value) is None for value in (revenue, gm, op, eps)):
        _flag(result, f"{period} 試算 EPS 或中間值非有限值")
        return None

    return {
        "q": str(period),
        "kind": "copy" if latest and not has_monthly else "est",
        "rev_src": "monthly" if has_monthly else "flat",
        "gp": float(gp),
        "opex_ratio": float(opex_ratio),
        "opex": float(opex),
        "conv": float(conv),
        "net": float(net),
        "shares": params["shares"],
        "eps": float(eps),
        "rev": float(revenue),
        "gm": float(gm),
        "op": float(op),
        "nonop": nonop,
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
    result["variability"] = _variability(q)
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
    if params["g12"] is None and TRIAL_BASIS == "ttm":      # latest 口徑不用遠季成長率；g12 缺值只影響未來 4 季（_future 會標資料不足）
        _flag(result, "近十二月或去年同期月營收不足，遠季成長率用 0")

    ttm_periods = pd.period_range(end=last, periods=TTM_QUARTERS, freq="Q-DEC")
    ttm_details = _actual_details(q, ttm_periods)
    result["eps_ttm"] = _sum_eps(ttm_details)
    if result["eps_ttm"] is None:
        ttm_details = None
        _flag(result, "過去 4 季 EPS 缺季或缺值")

    result["ttm_quarters"] = ttm_details or []
    future = pd.period_range(start=last + 1, periods=FUTURE_QUARTERS, freq="Q-DEC")

    k = result["k"]
    if k == 0 and TRIAL_BASIS == "ttm":
        result["eps_nc"] = result["eps_ttm"]
        result["nc_quarters"] = ttm_details or []

    if TRIAL_BASIS == "latest" and (
        _gross_margin(q.loc[[last]]) is None
        or _number(q.loc[last, "op_income"]) is None
    ):
        _flag(result, "最新一季毛利率／費用率缺值")
        _fallback(result, ttm_details)
    calibration_error = _calibrate(q, result)
    if calibration_error is not None:
        if k != 0 or TRIAL_BASIS == "latest":
            _fallback(result, ttm_details)
        return _fail(result, calibration_error)

    estimates = {}
    if k is not None and k <= MAX_NC_K:
        flat_revenue = _number(q.loc[last, "revenue"])
        for period in future[:k + (TRIAL_BASIS == "latest")]:
            detail = _estimate(q, monthly, period, result, flat_revenue, basis=TRIAL_BASIS)
            estimates[period] = detail
            if detail is not None and _has_monthly(monthly, period):
                flat_revenue = detail["rev"]

    if k is None:
        _flag(result, "沒有月營收最新月，無法判定滾動季數")
        _fallback(result, ttm_details)
    elif k > MAX_NC_K:
        _flag(result, "月營收超前財報超過三季")
        _fallback(result, ttm_details)
    elif k > 0 or TRIAL_BASIS == "latest":
        actual_periods = pd.period_range(
            end=last, periods=TTM_QUARTERS - k - (TRIAL_BASIS == "latest"), freq="Q-DEC"
        )
        actual = _actual_details(q, actual_periods)
        estimated = [estimates[period] for period in future[:k + (TRIAL_BASIS == "latest")]]
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
        result["eps_nc"] is not None
    )
    if not result["ok"]:
        return _fail(result, "無法取得可用的前瞻 4 季或過去 4 季 EPS")
    _future(q, result)
    return result


def _future(q: pd.DataFrame, result: dict[str, Any]) -> None:
    """末兩季原樣共用；成長季採最新季參數。"""
    if FALLBACK_FLAG in result["flags"] or result["eps_nc"] is None:
        return
    p = result["params"]
    last = q.index[-1]
    previous = last - QUARTERS_PER_YEAR
    g = p["g12"]
    if g is None or previous not in q.index:
        return
    current_ni = _number(q.loc[last, "ni_parent"])
    previous_ni = _number(q.loc[previous, "ni_parent"])
    current_op = _number(q.loc[last, "op_income"])
    previous_op = _number(q.loc[previous, "op_income"])
    if current_ni is None or previous_ni is None or current_op is None or previous_op is None:
        return
    # 淨利含業外、預測季排除業外：同時要求營業利益年增，避免靠業外撐起的「成長」
    if g <= 0 or previous_ni <= 0 or current_ni <= previous_ni or previous_op <= 0 or current_op <= previous_op:
        result["future_status"] = "not_growth"
        return
    qs = result["nc_quarters"]
    if len(qs) != 4 or any(p[key] is None for key in ("gm_last", "opex_last", "t", "m", "shares")):
        return
    flat_revenue = qs[-1]["rev"]
    if flat_revenue is None:
        return
    details = qs[2:4]
    growth = min(FUTURE_G_FACTOR * g, FUTURE_MULT_CAP ** 2 - 1)
    for j in (1, 2):
        rev = flat_revenue * (1 + growth) ** (j / 4)
        gm, opex_ratio = p["gm_last"], p["opex_last"]
        gp, opex = rev * gm, rev * opex_ratio
        op = gp - opex
        conv = (1 - p["t"]) * (1 - p["m"])
        net = op * conv
        details.append(dict(q=str(pd.Period(qs[-1]["q"], freq="Q-DEC") + j),
                            kind="grow", rev=rev, rev_src="grow", gm=gm, gp=gp,
                            opex_ratio=opex_ratio, opex=opex, op=op, nonop=0.0,
                            conv=conv, net=net, shares=p["shares"], eps=net / p["shares"]))
    eps_future = _sum_eps(details)
    if eps_future is None or eps_future <= 0:                  # 合計非正（例：試算費用率高於毛利率）→ 不給數字
        return
    result.update(eps_future=eps_future, future_quarters=details, future_status="ok")


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
