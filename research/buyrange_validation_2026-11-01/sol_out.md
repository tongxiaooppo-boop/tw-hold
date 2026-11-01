```python
# replay.py
# 預註冊優先：
# 1. BT1 的主分析依預註冊 §1，條件為 TTM>0、目標>0、預測有限；
#    不採任務文字另外加入的 F4>0 篩選，避免事後刪除負值預測。
# 2. 不讀 disclosure_date、stock_class.json 或任何分類。
# 3. 未來實際 EPS、進出場價及 0050 報酬集中於檔尾「僅供評分」區。
from __future__ import annotations

import csv
import math
import sys
import traceback
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "app"))
sys.path.insert(0, str(HERE))

import numpy as np
import pandas as pd

import data
from screener import eps_nowcast

OUT = HERE / "out"
EXIT_CUTOFF = pd.Timestamp("2026-10-30")
HOLDING_DAYS = 252
COST = 0.006
ERROR_COLUMNS = ["script", "ticker", "rd", "stage", "error", "traceback"]

LIMITATIONS = (
    "母體為現行上市櫃，沒有下市股；財報使用現存重編值，沒有原始公告版本。"
    "財報及月營收以法定期限代理可得日，不使用 disclosure_date。"
    "EPS 股數調整沿用 loader 的 quarterly_factors/adjust_eps，可能含後見調整。"
    "預測目標為含業外的季報 EPS；NC 使用業外中位數，口徑可能不同。"
    "PER 未另行修正股數事件；BT2 將排除窗口內已發生的重大股數事件。"
)
PRICE_CHECK = (
    "價格先決檢查：依指定 data.py 的資料契約，prices_adj 為含息還原價，"
    "且提供者已實測除息日 ratio 跳變；本腳本沒有另用原始股利資料獨立重驗。"
    "0050 使用指定 index_0050 的 close；其是否為含息總報酬未獲資料契約保證，"
    "故 0050 僅列輔助對照，不用於通過判定。"
)

_SOURCE = None
_HISTORY: dict = {}
_PRICES: dict = {}
_DIAGNOSTICS: dict = {}
_CALENDAR = None


def init_output() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "errors.csv"
    if not path.exists() or path.stat().st_size == 0:
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(ERROR_COLUMNS)
    return OUT


def log_error(t, rd, stage: str, exc: Exception) -> None:
    init_output()
    row = [
        Path(sys.argv[0]).name,
        str(t),
        "" if rd is None else str(pd.Timestamp(rd).date()),
        stage,
        f"{type(exc).__name__}: {exc}",
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    ]
    with (OUT / "errors.csv").open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)


def number(value) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return float("nan")
    return value if math.isfinite(value) else float("nan")


def isfinite(value) -> bool:
    return math.isfinite(number(value))


def ratio(numerator, denominator) -> float:
    a, b = number(numerator), number(denominator)
    return a / b if math.isfinite(a) and math.isfinite(b) and b != 0 else np.nan


def _sync(d) -> None:
    global _SOURCE, _CALENDAR
    if _SOURCE is not d:
        _SOURCE = d
        _HISTORY.clear()
        _PRICES.clear()
        _DIAGNOSTICS.clear()
        _CALENDAR = None


def replay_dates(start, end) -> list[pd.Timestamp]:
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    return [
        rd
        for year in range(start.year, end.year + 1)
        for month, day in ((4, 1), (5, 16), (8, 15), (11, 15))
        if start <= (rd := pd.Timestamp(year, month, day)) <= end
    ]


def _diagnostic(d, t, rd) -> dict:
    _sync(d)
    key = (str(t), pd.Timestamp(rd))
    if key not in _DIAGNOSTICS:
        _DIAGNOSTICS[key] = {
            "t": str(t),
            "rd": pd.Timestamp(rd),
            "n_q": 0,
            "has_8q": False,
            "has_gross": False,
            "base_eligible": False,
            "eligible": False,
            "nc_calculable": False,
            "f4_calculable": False,
            "reason": "",
        }
    return _DIAGNOSTICS[key]


def _history(d, t) -> dict:
    """僅建立排序及可得日索引；PIT 使用嚴格小於 rd 的切片。"""
    _sync(d)
    if t in _HISTORY:
        return _HISTORY[t]

    q = d["qf"][t].copy()
    q["period_end"] = pd.to_datetime(q["period_end"])
    q = q.sort_values("period_end", kind="stable").reset_index(drop=True)
    if q["period_end"].isna().any():
        raise ValueError("季報 period_end 有 NaT")
    if "ni_parent" not in q:
        q["ni_parent"] = np.nan
    q_deadlines = pd.DatetimeIndex(
        [data.report_deadline(pd.Timestamp(x)) for x in q["period_end"]]
    )

    monthly = d.get("monthly", {}).get(t, pd.Series(dtype=float)).copy()
    monthly.index = pd.DatetimeIndex(pd.to_datetime(monthly.index))
    if monthly.index.hasnans:
        raise ValueError("月營收索引有 NaT")
    monthly = monthly.sort_index()
    m_deadlines = pd.DatetimeIndex(
        [data.revenue_deadline(pd.Timestamp(x)) for x in monthly.index]
    )

    per = d.get("per", {}).get(
        t, pd.DataFrame(columns=["date", "per", "pbr"])
    ).copy()
    per["date"] = pd.to_datetime(per["date"])
    per = per.loc[per["date"].notna()].sort_values("date", kind="stable")
    per = per.reset_index(drop=True)
    p_dates = pd.DatetimeIndex(per["date"])

    if not q_deadlines.is_monotonic_increasing:
        raise ValueError("季報法定期限未依季度遞增")
    if not m_deadlines.is_monotonic_increasing:
        raise ValueError("月營收法定期限未依月份遞增")

    result = {
        "q": q,
        "q_deadlines": q_deadlines,
        "monthly": monthly,
        "m_deadlines": m_deadlines,
        "per": per,
        "p_dates": p_dates,
    }
    _HISTORY[t] = result
    return result


def point_in_time(d, t, rd) -> dict | None:
    rd = pd.Timestamp(rd)
    audit = _diagnostic(d, t, rd)
    try:
        h = _history(d, t)
        q = h["q"].iloc[: h["q_deadlines"].searchsorted(rd, side="left")]
        monthly = h["monthly"].iloc[
            : h["m_deadlines"].searchsorted(rd, side="left")
        ]
        per = h["per"].iloc[: h["p_dates"].searchsorted(rd, side="left")]

        audit["n_q"] = len(q)
        audit["has_8q"] = q["period_end"].dt.to_period("Q-DEC").nunique() >= 8
        audit["has_gross"] = (
            "gross_profit" in q
            and pd.to_numeric(q["gross_profit"], errors="coerce").notna().any()
        )
        if not audit["has_8q"]:
            audit["reason"] = "不足8季財報"
            return None
        if not audit["has_gross"]:
            audit["reason"] = "缺毛利欄或全NaN"
            return None
        return {"q": q, "monthly": monthly, "per": per}
    except Exception as exc:
        audit["reason"] = "PIT例外"
        log_error(t, rd, "point_in_time", exc)
        return None


def quarter_eps(q: pd.DataFrame) -> pd.Series:
    """只對傳入的季報運算；補齊季度格點由呼叫端明確指定。"""
    periods = pd.DatetimeIndex(q["period_end"]).to_period("Q-DEC")
    if periods.has_duplicates:
        raise ValueError("季報同季重複")
    values = pd.to_numeric(q["eps"], errors="coerce").to_numpy(dtype=float)
    values[~np.isfinite(values)] = np.nan
    return pd.Series(values, index=periods, dtype=float).sort_index()


def current_ttm(q: pd.DataFrame) -> float:
    e = quarter_eps(q)
    if e.empty:
        return np.nan
    a = e.reindex(pd.period_range(end=e.index[-1], periods=4, freq="Q-DEC"))
    return float(a.sum()) if a.notna().all() else np.nan


def compute_point(d, t, rd) -> dict | None:
    rd = pd.Timestamp(rd)
    audit = _diagnostic(d, t, rd)
    pit = point_in_time(d, t, rd)
    if pit is None:
        return None
    try:
        q, monthly = pit["q"], pit["monthly"]
        ttm = current_ttm(q)
        if not isfinite(ttm):
            audit["reason"] = "最近連續4季EPS缺值"
            return None
        if ttm <= 0:
            audit["reason"] = "TTM非正"
            return None
        audit["base_eligible"] = True

        nc = eps_nowcast.nowcast(q, monthly)
        if not nc.get("ok", False):
            audit["reason"] = "nowcast失敗：" + str(nc.get("reason") or "未說明")
            return None
        ttm = number(nc.get("eps_ttm"))
        if not isfinite(ttm) or ttm <= 0:
            audit["reason"] = "nowcast的TTM缺值或非正"
            return None

        eps_nc = number(nc.get("eps_nc"))
        eps_f4 = number(nc.get("eps_f4"))
        audit["eligible"] = True
        audit["nc_calculable"] = isfinite(eps_nc)
        audit["f4_calculable"] = isfinite(eps_f4)
        missing = []
        if not audit["nc_calculable"]:
            missing.append("NC缺值")
        if not audit["f4_calculable"]:
            missing.append("F4缺值")
        audit["reason"] = ";".join(missing)

        last = pd.Timestamp(nc["last_q"])
        k_raw = nc.get("k")
        k = int(k_raw) if k_raw is not None and isfinite(k_raw) else None

        # 僅供評分：回傳欄位中 target* 不得供預測、分層或篩選使用。
        targets = scoring_targets(d, t, last, k)
        return {
            "t": str(t),
            "rd": rd,
            "q_last": last,
            "k": k,
            "eps_nc": eps_nc,
            "eps_f4": eps_f4,
            "eps_ttm": ttm,
            "target4": targets["target4"],
            "target_nc": targets["target_nc"],
            "flags": list(nc.get("flags") or []),
            "params": dict(nc.get("params") or {}),
        }
    except Exception as exc:
        audit["reason"] = "compute_point例外"
        log_error(t, rd, "compute_point", exc)
        return None


def eligible_universe(d, rd) -> dict:
    result = {}
    for t in sorted(d["qf"]):
        point = compute_point(d, t, rd)
        if point is not None:
            result[str(t)] = point
    return result


def population_tables(d, dates) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, failures = [], []
    for rd in dates:
        audits = [_diagnostic(d, t, rd) for t in sorted(d["qf"])]
        n_base = sum(a["base_eligible"] for a in audits)
        nc = sum(a["nc_calculable"] for a in audits)
        f4 = sum(a["f4_calculable"] for a in audits)
        rows.append(
            {
                "rd": pd.Timestamp(rd).date().isoformat(),
                "current_tickers": len(d["qf"]),
                "has_8q_and_gross": sum(
                    a["has_8q"] and a["has_gross"] for a in audits
                ),
                "base_universe": n_base,
                "eligible": sum(a["eligible"] for a in audits),
                "NC_n": nc,
                "F4_n": f4,
                "NC_ratio": ratio(nc, n_base),
                "F4_ratio": ratio(f4, n_base),
            }
        )
        counts = Counter(
            reason
            for a in audits
            for reason in a["reason"].split(";")
            if reason
        )
        for reason, n in sorted(counts.items()):
            failures.append(
                {
                    "rd": pd.Timestamp(rd).date().isoformat(),
                    "reason": reason,
                    "n": n,
                }
            )
    return (
        pd.DataFrame(rows),
        pd.DataFrame(failures, columns=["rd", "reason", "n"]),
    )


def _price_frame(d, t) -> pd.DataFrame:
    _sync(d)
    if t not in _PRICES:
        raw = d.get("px", {}).get(t)
        if raw is None or raw.empty:
            x = pd.DataFrame(
                columns=["open", "close"], index=pd.DatetimeIndex([], name="date")
            )
        else:
            x = raw.loc[:, ["date", "open", "close"]].copy()
            x["date"] = pd.to_datetime(x["date"])
            x = x.dropna(subset=["date"]).drop_duplicates("date", keep="last")
            x = x.set_index("date").sort_index()
        _PRICES[t] = x
    return _PRICES[t]


def known_price(d, t, rd) -> tuple[pd.Timestamp | None, float]:
    """進場前一市場交易日的 close：僅讀 date<=rd，不向前補缺價。"""
    x = _price_frame(d, t)
    calendar = market_calendar(d)
    i = calendar.searchsorted(pd.Timestamp(rd), side="right") - 1
    if i < 0:
        return None, np.nan
    date = pd.Timestamp(calendar[i])
    if date not in x.index:
        return date, np.nan
    value = number(x.at[date, "close"])
    return date, value if isfinite(value) and value > 0 else np.nan


def market_calendar(d) -> pd.DatetimeIndex:
    """只把日期當交易日曆；不把任何未來價格數值交給預測端。"""
    global _CALENDAR
    _sync(d)
    if _CALENDAR is None:
        arrays = []
        for x in d.get("px", {}).values():
            if x is not None and not x.empty:
                dates = pd.DatetimeIndex(pd.to_datetime(x["date"])).dropna()
                arrays.append(dates.to_numpy(dtype="datetime64[ns]"))
        idx = d.get("idx0050")
        if idx is not None and not idx.empty:
            dates = pd.DatetimeIndex(pd.to_datetime(idx["date"])).dropna()
            arrays.append(dates.to_numpy(dtype="datetime64[ns]"))
        _CALENDAR = (
            pd.DatetimeIndex(np.unique(np.concatenate(arrays))).sort_values()
            if arrays
            else pd.DatetimeIndex([])
        )
    return _CALENDAR


def md_table(frame: pd.DataFrame, columns=None) -> str:
    if columns is not None:
        frame = frame.reindex(columns=columns)
    if frame.empty:
        return "（無樣本）\n"

    def fmt(x):
        if x is None or x is pd.NA:
            return "NA"
        if isinstance(x, (float, np.floating)):
            return f"{x:.6g}" if math.isfinite(float(x)) else "NA"
        if isinstance(x, (bool, np.bool_)):
            return "是" if x else "否"
        if isinstance(x, pd.Timestamp):
            return x.date().isoformat()
        return str(x).replace("|", r"\|").replace("\n", " ")

    headers = [str(c) for c in frame.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(fmt(x) for x in row) + " |"
        for row in frame.itertuples(index=False, name=None)
    )
    return "\n".join(lines) + "\n"


# ============================================================================
# 僅供評分：以下是唯一讀取 rd 之後實際 EPS、進出場價及 benchmark 數值的區域。
# 這些輸出不得作為可買條件、可信度、倍數窗口或預測分層的輸入。
# ============================================================================

def scoring_targets(d, t, q_last, k) -> dict:
    result = {"target4": None, "target_nc": None}
    try:
        actual = quarter_eps(d["qf"][t])
        last = pd.Timestamp(q_last).to_period("Q-DEC")

        def total(end):
            a = actual.reindex(
                pd.period_range(end=end, periods=4, freq="Q-DEC")
            )
            return float(a.sum()) if a.notna().all() else None

        result["target4"] = total(last + 4)
        if k is not None and k >= 0:
            result["target_nc"] = total(last + int(k))
    except Exception as exc:
        log_error(t, None, "scoring_targets", exc)
    return result


def scoring_schedule(d, rd) -> dict:
    """次一市場交易日進場；其後第252個交易日收盤出場，不以缺價日遞延。"""
    calendar = market_calendar(d)
    i = calendar.searchsorted(pd.Timestamp(rd), side="right")
    if i >= len(calendar):
        return {
            "entry_date": pd.NaT,
            "exit_date": pd.NaT,
            "reason": "無進場交易日",
        }
    entry = pd.Timestamp(calendar[i])
    j = i + HOLDING_DAYS
    if j >= len(calendar):
        return {
            "entry_date": entry,
            "exit_date": pd.NaT,
            "reason": "不足252個後續交易日",
        }
    exit_date = pd.Timestamp(calendar[j])
    return {
        "entry_date": entry,
        "exit_date": exit_date,
        "reason": "出場超過2026-10-30" if exit_date > EXIT_CUTOFF else "",
    }


def scoring_trade(d, t, rd) -> dict:
    schedule = scoring_schedule(d, rd)
    result = {
        **schedule,
        "ok": False,
        "ret": np.nan,
        "ret_net": np.nan,
        "benchmark_0050": np.nan,
    }
    if schedule["reason"]:
        return result
    try:
        entry, exit_date = schedule["entry_date"], schedule["exit_date"]
        x = _price_frame(d, t)
        if entry not in x.index or exit_date not in x.index:
            result["reason"] = "進場或出場交易日缺價"
            return result
        open_entry = number(x.at[entry, "open"])
        close_exit = number(x.at[exit_date, "close"])
        if not (isfinite(open_entry) and isfinite(close_exit)):
            result["reason"] = "進出場價非有限值"
            return result
        if open_entry <= 0 or close_exit <= 0:
            result["reason"] = "進出場價非正"
            return result

        result["ok"] = True
        result["ret"] = close_exit / open_entry - 1
        result["ret_net"] = result["ret"] - COST
        result["reason"] = ""

        idx = d.get("idx0050")
        if idx is not None and not idx.empty:
            dates = pd.to_datetime(idx["date"])
            a = idx.loc[dates.eq(entry), "close"]
            b = idx.loc[dates.eq(exit_date), "close"]
            if not a.empty and not b.empty:
                v0, v1 = number(a.iloc[-1]), number(b.iloc[-1])
                if isfinite(v0) and isfinite(v1) and v0 > 0 and v1 > 0:
                    result["benchmark_0050"] = v1 / v0 - 1
    except Exception as exc:
        result["reason"] = "價格評分例外"
        result["ok"] = False
        log_error(t, rd, "scoring_trade", exc)
    return result
```

```python
# bt1.py
# 預註冊優先：§1 僅要求 TTM>0、目標>0，沒有 F4>0 的額外限制。
# 因而主分析保留有限但非正的 F4/NC 預測；與任務文字衝突處依預註冊。
# 「TTM相對近5年中位數≥P80」的事前操作定義：
# 每股最近20個季度終點之連續4季TTM，至少12個有效值、其中位數>0；
# 以當期TTM/自身歷史中位數，在每個重播點的可分層母體取橫斷面P80。
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "app"))
sys.path.insert(0, str(HERE))

import numpy as np
import pandas as pd

import data
from screener import detect
from replay import (
    LIMITATIONS,
    eligible_universe,
    init_output,
    isfinite,
    log_error,
    md_table,
    number,
    point_in_time,
    population_tables,
    quarter_eps,
    ratio,
    replay_dates,
)

START = "2018-04-01"
END = "2025-08-15"
TARGET_2026 = pd.Timestamp("2026-01-01")
NW_LAG = 3
BOOTSTRAP_DRAWS = 5000
BOOTSTRAP_SEED = 20261101
HISTORY_TTM_ENDPOINTS = 20
MIN_HISTORY_TTMS = 12

STRATA = (
    "all",
    "ttm_high",
    "ttm_not_high",
    "ttm_unclassified",
    "revenue_positive",
    "revenue_negative",
    "revenue_zero",
    "revenue_unknown",
    "nonop_ok",
    "nonop_degrade",
    "nonop_block",
)
CUTS = ("all", "exclude_2026")
ERROR_FIELDS = [
    "n", "p10", "p25", "p50", "p75", "p90",
    "median_absolute_error", "naive_median_absolute_error", "skill",
]
Q_FIELDS = [f"q{i}_actual_growth_median" for i in range(1, 6)]
BASE_COLUMNS = [
    "t", "rd", "q_last", "k", "eps_nc", "eps_f4", "eps_ttm",
    "target4", "target_nc", "target4_end", "ttm_relative",
    "ttm_history_n", "ttm_class", "revenue_growth_3m", "nonop_level",
]


def past_features(q, monthly, eps_ttm) -> dict:
    result = {
        "ttm_relative": np.nan,
        "ttm_history_n": 0,
        "revenue_growth_3m": np.nan,
        "nonop_level": "unknown",
    }
    e = quarter_eps(q)
    if not e.empty:
        grid = pd.period_range(
            end=e.index[-1], periods=HISTORY_TTM_ENDPOINTS + 3, freq="Q-DEC"
        )
        history = e.reindex(grid).rolling(4, min_periods=4).sum().iloc[-20:]
        valid = history.loc[np.isfinite(history.to_numpy(dtype=float))]
        result["ttm_history_n"] = len(valid)
        if len(valid) >= MIN_HISTORY_TTMS:
            med = number(valid.median())
            if isfinite(med) and med > 0:
                result["ttm_relative"] = number(eps_ttm) / med

    if not monthly.empty:
        m = pd.Series(
            pd.to_numeric(monthly, errors="coerce").to_numpy(dtype=float),
            index=pd.DatetimeIndex(monthly.index).to_period("M"),
        )
        if m.index.has_duplicates:
            raise ValueError("月營收同月重複")
        current = pd.period_range(end=m.index.max(), periods=3, freq="M")
        a = m.reindex(current).to_numpy(dtype=float)
        b = m.reindex(current - 12).to_numpy(dtype=float)
        if np.isfinite(a).all() and np.isfinite(b).all() and b.sum() != 0:
            result["revenue_growth_3m"] = a.sum() / b.sum() - 1

    result["nonop_level"] = detect.nonop_gate(q).level
    return result


def select_stratum(frame: pd.DataFrame, stratum: str) -> pd.DataFrame:
    if stratum == "all":
        return frame
    if stratum.startswith("ttm_"):
        label = {
            "ttm_high": "high",
            "ttm_not_high": "not_high",
            "ttm_unclassified": "unknown",
        }[stratum]
        return frame.loc[frame["ttm_class"].eq(label)]
    if stratum.startswith("nonop_"):
        return frame.loc[frame["nonop_level"].eq(stratum.removeprefix("nonop_"))]
    g = pd.to_numeric(frame["revenue_growth_3m"], errors="coerce")
    mask = {
        "revenue_positive": g.gt(0),
        "revenue_negative": g.lt(0),
        "revenue_zero": g.eq(0),
        "revenue_unknown": g.isna(),
    }[stratum]
    return frame.loc[mask]


def select_cut(frame: pd.DataFrame, cut: str) -> pd.DataFrame:
    if cut == "all":
        return frame
    return frame.loc[frame["target4_end"].lt(TARGET_2026)]


def error_stats(frame: pd.DataFrame, model: str) -> dict:
    prediction = "eps_f4" if model == "F4" else "eps_nc"
    target = "target4" if model == "F4" else "target_nc"
    p = pd.to_numeric(frame[prediction], errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(frame[target], errors="coerce").to_numpy(dtype=float)
    naive = pd.to_numeric(frame["eps_ttm"], errors="coerce").to_numpy(dtype=float)
    mask = (
        np.isfinite(p) & np.isfinite(y) & np.isfinite(naive)
        & (y > 0) & (naive > 0)
    )
    result = dict.fromkeys(ERROR_FIELDS, np.nan)
    result["n"] = int(mask.sum())
    if not mask.any():
        return result
    e = (p[mask] - y[mask]) / y[mask]
    e_naive = (naive[mask] - y[mask]) / y[mask]
    for key, value in zip(
        ("p10", "p25", "p50", "p75", "p90"),
        np.percentile(e, [10, 25, 50, 75, 90]),
    ):
        result[key] = float(value)
    mae = float(np.median(np.abs(e)))
    mae_naive = float(np.median(np.abs(e_naive)))
    result["median_absolute_error"] = mae
    result["naive_median_absolute_error"] = mae_naive
    result["skill"] = 1 - mae / mae_naive if mae_naive > 0 else np.nan
    return result


def spearman_rank_ic(x, y) -> float:
    a = pd.Series(x, dtype=float).rank(method="average").to_numpy(dtype=float)
    b = pd.Series(y, dtype=float).rank(method="average").to_numpy(dtype=float)
    if len(a) < 2:
        return np.nan
    a, b = a - a.mean(), b - b.mean()
    denominator = np.sqrt(np.dot(a, a) * np.dot(b, b))
    return float(np.dot(a, b) / denominator) if denominator > 0 else np.nan


def newey_west_t(values, lag=NW_LAG) -> float:
    """截距平均數的 Bartlett HAC；gamma_l 使用除以 n 的定義。"""
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2:
        return np.nan
    u = x - x.mean()
    long_run_variance = float(np.dot(u, u) / n)
    for ell in range(1, min(lag, n - 1) + 1):
        weight = 1 - ell / (lag + 1)
        long_run_variance += 2 * weight * float(np.dot(u[ell:], u[:-ell]) / n)
    if long_run_variance <= 0:
        return np.nan
    return float(x.mean() / np.sqrt(long_run_variance / n))


def yearly_block_ci(point_rows) -> tuple[float, float, int]:
    """整個重播年一起重抽，保留每年有效點數，以逐點IC平均為估計量。"""
    valid = [
        (pd.Timestamp(row["rd"]).year, number(row["ic"]))
        for row in point_rows
        if isfinite(row["ic"])
    ]
    years = sorted({year for year, _ in valid})
    if len(years) < 2:
        return np.nan, np.nan, len(years)
    sums = np.array(
        [sum(value for year, value in valid if year == y) for y in years],
        dtype=float,
    )
    counts = np.array(
        [sum(year == y for year, _ in valid) for y in years], dtype=float
    )
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    selected = rng.integers(0, len(years), size=(BOOTSTRAP_DRAWS, len(years)))
    means = sums[selected].sum(axis=1) / counts[selected].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi), len(years)


def growth_sample(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["eps_f4", "eps_ttm", "target4"]
    values = frame[columns].apply(pd.to_numeric, errors="coerce")
    mask = np.isfinite(values.to_numpy(dtype=float)).all(axis=1)
    mask &= values["eps_ttm"].gt(0).to_numpy()
    mask &= values["target4"].gt(0).to_numpy()
    result = frame.loc[mask, ["t", "rd"]].copy()
    values = values.loc[mask]
    result["predicted_growth"] = values["eps_f4"] / values["eps_ttm"] - 1
    result["actual_growth"] = values["target4"] / values["eps_ttm"] - 1
    return result


def quintile_medians(frame: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    result = dict.fromkeys(Q_FIELDS, np.nan)
    assigned = frame.copy()
    assigned["quintile"] = np.nan
    if len(frame) >= 5:
        # 平均名次，不用 ticker/輸入順序拆散相同訊號；同值多時允許空分位。
        assigned["quintile"] = np.ceil(
            assigned["predicted_growth"].rank(method="average", pct=True) * 5
        ).clip(1, 5)
        for i in range(1, 6):
            a = assigned.loc[assigned["quintile"].eq(i), "actual_growth"]
            if not a.empty:
                result[f"q{i}_actual_growth_median"] = float(a.median())
    return result, assigned


def ic_analysis(frame: pd.DataFrame, dates) -> tuple[list[dict], dict]:
    sample = growth_sample(frame)
    rows, assigned_points = [], []
    for rd in dates:
        a = sample.loc[sample["rd"].eq(rd)]
        qstats, assigned = quintile_medians(a)
        rows.append(
            {
                "scope": "point",
                "rd": rd,
                "n": len(a),
                "ic": spearman_rank_ic(a["predicted_growth"], a["actual_growth"]),
                **qstats,
            }
        )
        assigned_points.append(assigned)

    pooled = pd.concat(assigned_points, ignore_index=True)
    pooled_q = dict.fromkeys(Q_FIELDS, np.nan)
    for i in range(1, 6):
        a = pooled.loc[pooled["quintile"].eq(i), "actual_growth"]
        if not a.empty:
            pooled_q[f"q{i}_actual_growth_median"] = float(a.median())

    ics = np.array([number(row["ic"]) for row in rows], dtype=float)
    finite = ics[np.isfinite(ics)]
    lo, hi, years = yearly_block_ci(rows)
    qvalues = [pooled_q[key] for key in Q_FIELDS]
    q5_gt_q1 = (
        isfinite(qvalues[0]) and isfinite(qvalues[-1])
        and qvalues[-1] > qvalues[0]
    )
    monotonic = bool(
        all(isfinite(x) for x in qvalues) and np.all(np.diff(qvalues) >= 0)
    )
    summary = {
        "scope": "all",
        "rd": "ALL",
        "n": len(sample),
        "ic_points": len(finite),
        "ic_mean": float(finite.mean()) if len(finite) else np.nan,
        "nw_lag": NW_LAG,
        "nw_t": newey_west_t(ics),
        "bootstrap_years": years,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "ci_low": lo,
        "ci_high": hi,
        **pooled_q,
        "q5_gt_q1": bool(q5_gt_q1),
        "quintiles_monotonic": monotonic,
    }
    return rows, summary


def positive_direction(row) -> bool:
    return bool(
        isfinite(row["ic_mean"]) and row["ic_mean"] > 0
        and row["q5_gt_q1"]
    )


def estimator_verdict(skill) -> str:
    if not isfinite(skill):
        return "skill無法判定；不得據此宣稱可用於價格門檻"
    if skill <= 0:
        return "輸給樸素預測（skill≤0）；依預註冊不得用於任何價格門檻"
    return "skill>0；不代表已通過BT2或已取得價格門檻依據"


def main() -> None:
    out = init_output()
    dates = replay_dates(START, END)
    d = data.load_all()
    records = []

    for rd in dates:
        universe = eligible_universe(d, rd)
        point_records = []
        for t, point in universe.items():
            features = {
                "ttm_relative": np.nan,
                "ttm_history_n": 0,
                "revenue_growth_3m": np.nan,
                "nonop_level": "unknown",
            }
            try:
                pit = point_in_time(d, t, rd)
                if pit is not None:
                    features = past_features(
                        pit["q"], pit["monthly"], point["eps_ttm"]
                    )
            except Exception as exc:
                log_error(t, rd, "bt1_past_features", exc)
            # 僅供評分的目標日期；不參與 PIT 分層。
            target_end = (
                pd.Timestamp(point["q_last"]).to_period("Q-DEC") + 4
            ).end_time.normalize()
            point_records.append(
                {
                    **point,
                    **features,
                    "target4_end": target_end,
                    "ttm_class": "unknown",
                }
            )

        valid_ratios = [
            r["ttm_relative"] for r in point_records
            if isfinite(r["ttm_relative"])
        ]
        p80 = float(np.percentile(valid_ratios, 80)) if valid_ratios else np.nan
        for row in point_records:
            if isfinite(row["ttm_relative"]) and isfinite(p80):
                row["ttm_class"] = (
                    "high" if row["ttm_relative"] >= p80 else "not_high"
                )
            records.append(row)
        pop, _ = population_tables(d, [rd])
        p = pop.iloc[0]
        print(
            f"BT1 {rd.date()} 現行={p['current_tickers']} "
            f"母體={p['base_universe']} eligible={len(universe)} "
            f"NC={p['NC_n']} F4={p['F4_n']}",
            flush=True,
        )

    frame = pd.DataFrame(records)
    if frame.empty:
        frame = pd.DataFrame(columns=BASE_COLUMNS)
    for c in ("rd", "q_last", "target4_end"):
        frame[c] = pd.to_datetime(frame[c])
    for c in (
        "eps_nc", "eps_f4", "eps_ttm", "target4", "target_nc",
        "ttm_relative", "revenue_growth_3m",
    ):
        frame[c] = pd.to_numeric(frame[c], errors="coerce")

    error_rows, ic_rows = [], []
    error_summaries, ic_summaries = {}, {}
    for cut in CUTS:
        cut_frame = select_cut(frame, cut)
        for stratum in STRATA:
            a = select_stratum(cut_frame, stratum)
            for model in ("F4", "NC"):
                summary = {
                    "scope": "all",
                    "cut": cut,
                    "stratum": stratum,
                    "rd": "ALL",
                    "model": model,
                    **error_stats(a, model),
                }
                error_rows.append(summary)
                error_summaries[(cut, stratum, model)] = summary
                for rd in dates:
                    error_rows.append(
                        {
                            "scope": "point",
                            "cut": cut,
                            "stratum": stratum,
                            "rd": rd.date().isoformat(),
                            "model": model,
                            **error_stats(a.loc[a["rd"].eq(rd)], model),
                        }
                    )

            points, summary = ic_analysis(a, dates)
            for row in points:
                ic_rows.append(
                    {
                        **row,
                        "rd": pd.Timestamp(row["rd"]).date().isoformat(),
                        "cut": cut,
                        "stratum": stratum,
                    }
                )
            summary.update(cut=cut, stratum=stratum)
            ic_summaries[(cut, stratum)] = summary

    for stratum in STRATA:
        full = ic_summaries[("all", stratum)]
        excluded = ic_summaries[("exclude_2026", stratum)]
        direction_unchanged = positive_direction(excluded)
        passed = bool(
            isfinite(full["ci_low"]) and full["ci_low"] > 0
            and full["q5_gt_q1"] and direction_unchanged
        )
        full["exclude_2026_direction_unchanged"] = direction_unchanged
        full["growth_signal_pass"] = passed
        excluded["positive_direction"] = direction_unchanged

    for cut in CUTS:
        for stratum in STRATA:
            ic_rows.append(ic_summaries[(cut, stratum)])

    errors = pd.DataFrame(error_rows)
    ics = pd.DataFrame(ic_rows)
    errors.to_csv(out / "bt1_error_by_point.csv", index=False, encoding="utf-8-sig")
    ics.to_csv(out / "bt1_ic.csv", index=False, encoding="utf-8-sig")

    population, failures = population_tables(d, dates)
    full = ic_summaries[("all", "all")]
    excluded = ic_summaries[("exclude_2026", "all")]
    f4 = error_summaries[("all", "all", "F4")]
    nc = error_summaries[("all", "all", "NC")]
    conclusion = "通過" if full["growth_signal_pass"] else "不通過"
    checks = pd.DataFrame(
        [
            {
                "檢查": "平均IC年度區塊bootstrap CI下界>0",
                "數值": full["ci_low"],
                "成立": isfinite(full["ci_low"]) and full["ci_low"] > 0,
            },
            {
                "檢查": "逐點五分位合併後Q5>Q1",
                "數值": number(full[Q_FIELDS[-1]]) - number(full[Q_FIELDS[0]]),
                "成立": full["q5_gt_q1"],
            },
            {
                "檢查": "排除2026目標後平均IC>0且Q5>Q1",
                "數值": excluded["ic_mean"],
                "成立": full["exclude_2026_direction_unchanged"],
            },
        ]
    )

    all_errors = errors.loc[errors["scope"].eq("all")]
    all_ics = ics.loc[ics["scope"].eq("all")]
    point_errors = errors.loc[
        errors["scope"].eq("point") & errors["stratum"].eq("all")
    ]
    point_ics = ics.loc[
        ics["scope"].eq("point") & ics["stratum"].eq("all")
    ]
    failure_totals = (
        failures.groupby("reason", as_index=False)["n"].sum()
        if not failures.empty
        else pd.DataFrame(columns=["reason", "n"])
    )

    text = [
        "# BT1：EPS估計器與成長訊號",
        "",
        f"重播區間 {START}～{END}，共 {len(dates)} 點；"
        f"現行財報代號數 {len(d['qf'])}。",
        "",
        f"## 明確結論：成長訊號{conclusion}",
        "",
        f"- F4：{estimator_verdict(f4['skill'])}。",
        f"- NC：{estimator_verdict(nc['skill'])}。",
        "- 成長訊號通過與否，和估計值能否用於價格門檻是兩件事；"
        "即使成長訊號通過，skill≤0 仍受預註冊禁止條款約束。",
        "",
        md_table(checks),
        "## 口徑",
        "",
        "- 主樣本依預註冊：TTM>0、各模型自己的目標>0、預測有限；"
        "保留非正預測，不套任務文字額外的F4>0篩選。",
        "- e=(預測−實際)/實際；MAE在本報告專指中位絕對相對誤差，"
        "不是平均絕對誤差。skill=1−模型MAE/同樣本樸素MAE；"
        "樸素MAE=0時skill記NA。",
        "- TTM不變與去年同季不變在本口徑完全等價："
        "未來四季各取去年同季，合計仍為Q_last−3..Q_last的TTM，故只保留一個基準。",
        "- TTM分層：最近20個季度終點計算連續四季TTM，至少12個有效值且"
        "歷史中位數>0，取當期TTM/該中位數；逐點橫斷面P80以上為high，"
        "其餘可分層者為not_high，不可分層者另列。",
        "- 營收符號為最近連續三月合計對去年同期；零與未知不硬塞進正／負。",
        "- 業外分層沿用當時detect.nonop_gate的ok/degrade/block，"
        "不因業外檢查失敗而從BT1母體刪除。",
        "- IC以pandas平均名次計算Pearson of ranks；每點等權。"
        "NW使用Bartlett權重、lag=3，缺失IC先略去。"
        f"年度區塊bootstrap固定seed={BOOTSTRAP_SEED}、{BOOTSTRAP_DRAWS}次，"
        "抽重播年並保留該年全部有效IC，對抽到的逐點IC求平均；少於兩年CI記NA。",
        "- 五分位在各點、各分層、各排除口徑內重分組，再合併個股觀察值取實際成長中位數；"
        "相同訊號不以代號任意拆開，可能出現空分位。單調定義Q1≤Q2≤...≤Q5；"
        "通過標準只要求Q5>Q1，不擅加單調條件。",
        "- 排除2026：Q_last+4季末≥2026-01-01的觀察值整筆剔除，"
        "同時重算F4、NC誤差及IC；方向不變定義為平均IC>0且Q5>Q1。",
        "- 以下所有誤差、成長與報酬均為小數比率，非百分比。",
        "",
        "## 母體與NC/F4可算比例",
        "",
        "base_universe為≥8季、有毛利、最近連續四季TTM>0；eligible另要求nowcast.ok。"
        "NC/F4比例分母為base_universe，不是已成功的eligible。",
        "",
        md_table(population),
        "## 失敗／缺值原因",
        "",
        "正常不合格原因與部分預測缺值如下；真正單檔例外另追加至errors.csv。"
        "同一觀察值可能同時計入NC缺值與F4缺值。",
        "",
        md_table(failure_totals),
        "### 逐點原因",
        "",
        md_table(failures),
        "## 全樣本及各分層誤差（含排除2026）",
        "",
        md_table(
            all_errors,
            ["cut", "stratum", "model", *ERROR_FIELDS],
        ),
        "## 全體逐重播點誤差",
        "",
        md_table(
            point_errors,
            ["cut", "rd", "model", *ERROR_FIELDS],
        ),
        "## IC、NW、bootstrap與五分位（含各分層、排除2026）",
        "",
        md_table(
            all_ics,
            [
                "cut", "stratum", "n", "ic_points", "ic_mean", "nw_t",
                "bootstrap_years", "ci_low", "ci_high", *Q_FIELDS,
                "q5_gt_q1", "quintiles_monotonic",
                "exclude_2026_direction_unchanged", "growth_signal_pass",
            ],
        ),
        "## 全體逐點IC與五分位",
        "",
        md_table(point_ics, ["cut", "rd", "n", "ic", *Q_FIELDS]),
        "完整逐點×分層資料見bt1_error_by_point.csv及bt1_ic.csv；"
        "scope=all為合併摘要，scope=point為逐點。",
        "",
        "## 已知限制",
        "",
        LIMITATIONS,
        "",
    ]
    (out / "bt1_summary.md").write_text("\n".join(text), encoding="utf-8")


if __name__ == "__main__":
    main()
```

```python
# bt2.py
# 預註冊優先，不更動G0/G1/G2/G3與四條通過標準。
# §2括註提及高成長3年/50，但沒有預註冊可重播的高成長識別規則；
# §3及本任務又禁止任何分類。本腳本不自行新增高成長分類門檻，
# 所有非金融PE樣本固定採任務明定的5年、48個月、cap=30。
# 12個月的交易日操作口徑依任務明定：次一交易日open進場，其後第252日close出場。
# 「相鄰方向一致」的固定實作：G0→G1→G2→G3的全樣本內外超額差同為正，
# 不另新增未預註冊的差值大小單調要求；P20只作子群報告，不作第五個候選。
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "app"))
sys.path.insert(0, str(HERE))

import numpy as np
import pandas as pd

import data
from screener import detect, multiples
from replay import (
    COST,
    LIMITATIONS,
    PRICE_CHECK,
    eligible_universe,
    init_output,
    isfinite,
    known_price,
    log_error,
    md_table,
    number,
    point_in_time,
    population_tables,
    ratio,
    replay_dates,
    scoring_schedule,
    scoring_trade,
)

START = "2023-08-15"
END = "2025-08-15"
EXCLUDE_EXIT_FROM = pd.Timestamp("2026-01-01")
BAND_YEARS = 5
MIN_MONTHS = 48
PE_CAP = 30.0
EVENT_THRESHOLD = 0.03
MAIN_GROUPS = ("G0", "G1", "G2", "G3")
P20_GROUPS = tuple(f"{g}_P20" for g in MAIN_GROUPS)
GROUPS = MAIN_GROUPS + P20_GROUPS
GROWTH_FACTORS = {"G1": 1.00, "G2": 1.05, "G3": 1.10}
TOP_N = 10
DISCLAIMER = (
    "獨立年度約 3、樣本為現行上市櫃（存活者偏差）、"
    "區間內外同時暴露於 2026 超級循環；即使通過只算方向性證據"
)
SCORED_COLUMNS = [
    "t", "rd", "entry_date", "exit_date", "ret", "ret_net",
    "benchmark_0050", "ew_return", "excess", "excess_net",
    "buyable", *GROUPS,
]


def prediction_record(d, t, rd, point) -> dict:
    """純PIT選股路徑：不讀target*、進場open、出場close或未來報酬。"""
    result = {
        "t": t,
        "rd": rd,
        "buyable": False,
        "known_price_date": pd.NaT,
        "known_price": np.nan,
        "n_months": np.nan,
        "confidence": "未計算",
        "event_blocked": False,
        "reasons": [],
        **dict.fromkeys(GROUPS, False),
    }
    pit = point_in_time(d, t, rd)
    if pit is None:
        result["reasons"].append("PIT不可用")
        return result

    q, monthly, per = pit["q"], pit["monthly"], pit["per"]
    b = multiples.band(
        per,
        "per",
        years=BAND_YEARS,
        min_months=MIN_MONTHS,
        cap=PE_CAP,
        asof=rd,
    )
    result["n_months"] = b.get("n_months", np.nan)
    p = multiples.prices(point["eps_nc"], b)

    checks = [
        detect.nonop_gate(q),
        detect.revenue_caliber(q, monthly),
        detect.bridge_residual(q, point["params"]),
        detect.shares_check(q),
    ]
    checks.extend(
        detect.Check("NC旗標", "degrade", None, str(flag))
        for flag in point["flags"]
    )
    checks.extend(
        [
            detect.dist_check(b),
            detect.near_zero_eps(
                point["eps_nc"] if isfinite(point["eps_nc"]) else None, q
            ),
        ]
    )
    confidence = detect.confidence(checks)
    result["confidence"] = confidence["level"]

    events_map = d.get("events", {})
    events = events_map.get(t)
    if events is None:
        result["reasons"].append("股數事件資料未知")
        result["event_blocked"] = True
    else:
        window_start = rd - pd.DateOffset(years=BAND_YEARS)
        for event_date, multiplier in events:
            event_date = pd.Timestamp(event_date)
            if not (window_start <= event_date < rd):
                continue
            multiplier = number(multiplier)
            if not isfinite(multiplier):
                result["event_blocked"] = True
                result["reasons"].append("窗內股數事件倍率缺值")
                break
            if round(abs(multiplier - 1), 9) >= EVENT_THRESHOLD:
                result["event_blocked"] = True
                result["reasons"].append("窗內股數事件>=3%")
                break

    price_date, price = known_price(d, t, rd)
    result["known_price_date"] = price_date
    result["known_price"] = price
    if not b.get("ok", False):
        result["reasons"].append("PER有效月數不足")
    if p is None:
        result["reasons"].append("無法給三價")
    elif not all(
        isfinite(p.get(name)) and p[name] > 0
        for name in ("cheap", "fair", "dear")
    ):
        result["reasons"].append("三價非有限或非正")
    if confidence["level"] not in ("高", "中"):
        result["reasons"].append("可信度" + confidence["level"])
    if not isfinite(price) or price <= 0:
        result["reasons"].append("前一市場交易日收盤缺價")

    if result["reasons"]:
        return result

    result["buyable"] = True
    result["G0"] = bool(price <= p["fair"])
    f4, ttm = number(point["eps_f4"]), number(point["eps_ttm"])
    for group, factor in GROWTH_FACTORS.items():
        result[group] = bool(
            result["G0"] and isfinite(f4) and isfinite(ttm)
            and f4 >= factor * ttm
        )
    cheap = price <= p["cheap"]
    for group in MAIN_GROUPS:
        result[f"{group}_P20"] = bool(result[group] and cheap)
    return result


def mean_value(frame: pd.DataFrame, column: str) -> float:
    if frame.empty:
        return np.nan
    values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    return float(values.mean()) if len(values) else np.nan


def positive_rate(values) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    return float(np.mean(values > 0)) if len(values) else np.nan


def side_metrics(frame: pd.DataFrame, prefix: str) -> dict:
    result = {
        f"n_{prefix}": len(frame),
        f"stocks_{prefix}": frame["t"].nunique() if not frame.empty else 0,
        f"{prefix}_return": mean_value(frame, "ret"),
        f"{prefix}_return_net": mean_value(frame, "ret_net"),
        f"{prefix}_excess": mean_value(frame, "excess"),
        f"{prefix}_excess_net": mean_value(frame, "excess_net"),
        f"{prefix}_ew_return": mean_value(frame, "ew_return"),
        f"{prefix}_0050_return": mean_value(frame, "benchmark_0050"),
    }
    if frame.empty:
        for key in (
            "win_rate", "win_rate_net", "excess_win_rate",
            "excess_win_rate_net", "0050_excess", "0050_excess_net",
            "0050_win_rate", "0050_n",
        ):
            result[f"{prefix}_{key}"] = 0 if key == "0050_n" else np.nan
        return result

    result[f"{prefix}_win_rate"] = positive_rate(frame["ret"])
    result[f"{prefix}_win_rate_net"] = positive_rate(frame["ret_net"])
    result[f"{prefix}_excess_win_rate"] = positive_rate(frame["excess"])
    result[f"{prefix}_excess_win_rate_net"] = positive_rate(frame["excess_net"])
    r = pd.to_numeric(frame["ret"], errors="coerce").to_numpy(dtype=float)
    b = pd.to_numeric(
        frame["benchmark_0050"], errors="coerce"
    ).to_numpy(dtype=float)
    valid = np.isfinite(r) & np.isfinite(b)
    result[f"{prefix}_0050_n"] = int(valid.sum())
    result[f"{prefix}_0050_excess"] = (
        float(np.mean(r[valid] - b[valid])) if valid.any() else np.nan
    )
    result[f"{prefix}_0050_excess_net"] = (
        float(np.mean(r[valid] - COST - b[valid])) if valid.any() else np.nan
    )
    result[f"{prefix}_0050_win_rate"] = (
        positive_rate(r[valid] - b[valid]) if valid.any() else np.nan
    )
    return result


def group_metrics(frame: pd.DataFrame, group: str) -> dict:
    mask = frame[group].fillna(False).astype(bool)
    inside, outside = frame.loc[mask], frame.loc[~mask]
    result = {
        "group": group,
        "n_buyable": len(frame),
        **side_metrics(inside, "in"),
        **side_metrics(outside, "out"),
    }
    result["spread"] = result["in_excess"] - result["out_excess"]
    result["spread_net"] = result["in_excess_net"] - result["out_excess_net"]
    return result


def remove_top_contributors(frame: pd.DataFrame, group: str) -> tuple:
    """以對組內合併平均超額的加總貢獻排序；同檔所有重播觀察整檔移除。"""
    inside = frame.loc[frame[group].fillna(False).astype(bool)]
    if inside.empty:
        return frame.copy(), [], pd.DataFrame(columns=["t", "contribution"])
    contribution = inside.groupby("t", as_index=False)["excess"].sum()
    contribution["contribution"] = contribution["excess"] / len(inside)
    contribution = contribution.sort_values(
        ["contribution", "t"], ascending=[False, True], kind="stable"
    )
    top = contribution.head(TOP_N)
    tickers = top["t"].tolist()
    remaining = frame.loc[~frame["t"].isin(tickers)].copy()
    return remaining, tickers, top[["t", "contribution"]]


def adjacent_direction_consistent(metrics: dict, names) -> bool:
    """四點鏈各相鄰端的內外差均為正；不要求差值大小單調。"""
    for left, right in zip(names[:-1], names[1:]):
        a = number(metrics[left]["spread"])
        b = number(metrics[right]["spread"])
        if not (isfinite(a) and isfinite(b) and a > 0 and b > 0):
            return False
    return True


def band_month_stats(predictions) -> dict:
    values = np.asarray(
        [number(row["n_months"]) for row in predictions], dtype=float
    )
    values = values[np.isfinite(values)]
    if not len(values):
        return {
            "per_months_n": 0,
            "per_months_min": np.nan,
            "per_months_p25": np.nan,
            "per_months_p50": np.nan,
            "per_months_p75": np.nan,
            "per_months_max": np.nan,
            "per_months_ge48": 0,
        }
    q = np.percentile(values, [0, 25, 50, 75, 100])
    return {
        "per_months_n": len(values),
        **dict(
            zip(
                [
                    "per_months_min", "per_months_p25", "per_months_p50",
                    "per_months_p75", "per_months_max",
                ],
                map(float, q),
            )
        ),
        "per_months_ge48": int(np.sum(values >= MIN_MONTHS)),
    }


def bt1_price_restriction(out: Path) -> str:
    """只讀同資料夾既有BT1結果；不把BT1結果拿來改BT2格點或四條判定。"""
    path = out / "bt1_error_by_point.csv"
    if not path.exists():
        return (
            "尚未找到BT1結果：以下僅判定BT2方向性證據，不授權實際價格門檻。"
            "依預註冊，須另確認F4/NC沒有skill≤0的禁止條款。"
        )
    try:
        errors = pd.read_csv(path)
        base = errors.loc[
            errors["scope"].eq("all")
            & errors["cut"].eq("all")
            & errors["stratum"].eq("all")
        ]
        messages = []
        for model in ("F4", "NC"):
            a = base.loc[base["model"].eq(model), "skill"]
            skill = number(a.iloc[0]) if not a.empty else np.nan
            if not isfinite(skill):
                messages.append(f"{model} skill未知，不得據此授權價格門檻")
            elif skill <= 0:
                messages.append(
                    f"{model} skill={skill:.6g}≤0，依預註冊不得用於任何價格門檻"
                )
            else:
                messages.append(f"{model} skill={skill:.6g}>0")
        return "；".join(messages) + "。BT2四條檢查不取代上述先決限制。"
    except Exception as exc:
        log_error("", None, "read_bt1_restriction", exc)
        return "BT1結果讀取失敗；不得將BT2方向性通過視為價格門檻授權。"


def main() -> None:
    out = init_output()
    dates = replay_dates(START, END)
    d = data.load_all()
    scored_records, audits, reason_rows = [], [], []
    schedules = {}

    for rd in dates:
        universe = eligible_universe(d, rd)
        predictions = []
        for t, point in universe.items():
            try:
                predictions.append(prediction_record(d, t, rd, point))
            except Exception as exc:
                log_error(t, rd, "bt2_prediction_record", exc)
                predictions.append(
                    {
                        "t": t,
                        "rd": rd,
                        "buyable": False,
                        "n_months": np.nan,
                        "confidence": "例外",
                        "event_blocked": False,
                        "reasons": ["估值或可信度例外"],
                        **dict.fromkeys(GROUPS, False),
                    }
                )

        prediction_map = {r["t"]: r for r in predictions}

        # 僅供評分：選股條件已完全凍結，才讀進出場及0050價格。
        schedule = scoring_schedule(d, rd)
        schedules[rd] = schedule
        priced = []
        price_failures = Counter()
        for t in universe:
            score = scoring_trade(d, t, rd)
            if not score["ok"]:
                price_failures[score["reason"]] += 1
                continue
            prediction = prediction_map[t]
            priced.append(
                {
                    "t": t,
                    "rd": rd,
                    "entry_date": score["entry_date"],
                    "exit_date": score["exit_date"],
                    "ret": score["ret"],
                    "ret_net": score["ret_net"],
                    "benchmark_0050": score["benchmark_0050"],
                    "buyable": prediction["buyable"],
                    **{g: prediction[g] for g in GROUPS},
                }
            )

        ew = float(np.mean([r["ret"] for r in priced])) if priced else np.nan
        for row in priced:
            row["ew_return"] = ew
            row["excess"] = row["ret"] - ew
            # 淨超額對照固定使用未扣成本母體；內外兩側均扣同一成本。
            row["excess_net"] = row["ret_net"] - ew
            scored_records.append(row)

        population, _ = population_tables(d, [rd])
        audit = population.iloc[0].to_dict()
        audit.update(
            {
                **band_month_stats(predictions),
                "entry_date": schedule["entry_date"],
                "exit_date": schedule["exit_date"],
                "priced_universe": len(priced),
                "ew_return": ew,
                "ew_return_net": ew - COST if isfinite(ew) else np.nan,
                "buyable_before_price_scoring": sum(r["buyable"] for r in predictions),
                "buyable_with_returns": sum(r["buyable"] for r in priced),
                "benchmark_0050_n": sum(
                    isfinite(r["benchmark_0050"]) for r in priced
                ),
                "event_blocked": sum(r["event_blocked"] for r in predictions),
            }
        )
        conf = Counter(r["confidence"] for r in predictions)
        for level in ("高", "中", "低", "不給價", "未計算", "例外"):
            audit["confidence_" + level] = conf[level]
        audits.append(audit)

        prediction_failures = Counter(
            reason for r in predictions for reason in r["reasons"]
        )
        for stage, counts in (
            ("可買條件", prediction_failures),
            ("價格評分", price_failures),
        ):
            for reason, n in sorted(counts.items()):
                reason_rows.append(
                    {
                        "rd": rd.date().isoformat(),
                        "stage": stage,
                        "reason": reason,
                        "n": n,
                    }
                )
        print(
            f"BT2 {rd.date()} 母體={audit['base_universe']} "
            f"eligible={len(universe)} 有報酬={len(priced)} "
            f"可買有報酬={audit['buyable_with_returns']} "
            f"NC={audit['NC_n']} F4={audit['F4_n']}",
            flush=True,
        )

    scored = pd.DataFrame(scored_records)
    if scored.empty:
        scored = pd.DataFrame(columns=SCORED_COLUMNS)
    for c in ("rd", "entry_date", "exit_date"):
        scored[c] = pd.to_datetime(scored[c])
    for g in ("buyable", *GROUPS):
        scored[g] = scored[g].fillna(False).astype(bool)
    buyable = scored.loc[scored["buyable"]].copy()
    audit_frame = pd.DataFrame(audits)
    audit_map = {
        pd.Timestamp(a["rd"]): a for a in audits
    }

    point_rows = []
    for rd in dates:
        a = buyable.loc[buyable["rd"].eq(rd)]
        for group in GROUPS:
            point_rows.append(
                {
                    "scope": "point",
                    "rd": rd.date().isoformat(),
                    **group_metrics(a, group),
                    **{
                        key: value
                        for key, value in audit_map[rd].items()
                        if key != "rd"
                    },
                }
            )
    point_frame = pd.DataFrame(point_rows)
    point_frame.to_csv(
        out / "bt2_groups.csv", index=False, encoding="utf-8-sig"
    )

    # 僅供評分的敏感度分析：整個重播點剔除，而非只刪其中個股。
    retained_dates = [
        rd for rd in dates
        if pd.notna(schedules[rd]["exit_date"])
        and schedules[rd]["exit_date"] < EXCLUDE_EXIT_FROM
        and not schedules[rd]["reason"]
    ]
    excluded = buyable.loc[buyable["rd"].isin(retained_dates)]
    full_metrics = {g: group_metrics(buyable, g) for g in GROUPS}
    excluded_metrics = {g: group_metrics(excluded, g) for g in GROUPS}

    chain_ok = adjacent_direction_consistent(full_metrics, MAIN_GROUPS)
    p20_chain_ok = adjacent_direction_consistent(full_metrics, P20_GROUPS)
    checks, summary_rows, top_rows = [], [], []
    passed_groups = []

    for group in GROUPS:
        full = full_metrics[group]
        ex = excluded_metrics[group]
        reduced, removed, contributions = remove_top_contributors(buyable, group)
        trimmed = group_metrics(reduced, group)
        point_spreads = point_frame.loc[
            point_frame["group"].eq(group), "spread"
        ].to_numpy(dtype=float)
        valid_points = int(np.isfinite(point_spreads).sum())
        positive_points = int(np.sum(np.isfinite(point_spreads) & (point_spreads > 0)))
        # 空內/外組的點不以缺值隱藏；分母固定為全部預註冊重播點。
        positive_fraction = ratio(positive_points, len(dates))
        c1_full = isfinite(full["spread"]) and full["spread"] > 0
        c1_excluded = isfinite(ex["spread"]) and ex["spread"] > 0
        c1 = bool(c1_full and c1_excluded)
        c2 = bool(isfinite(positive_fraction) and positive_fraction >= 2 / 3)
        c3 = bool(isfinite(trimmed["spread"]) and trimmed["spread"] > 0)
        c4 = chain_ok if group in MAIN_GROUPS else p20_chain_ok
        passed = bool(c1 and c2 and c3 and c4)

        if group in MAIN_GROUPS and passed:
            passed_groups.append(group)
        checks.append(
            {
                "group": group,
                "candidate": group in MAIN_GROUPS,
                "full_spread": full["spread"],
                "exclude_2026_spread": ex["spread"],
                "C1_full_and_excluded_positive": c1,
                "positive_points": positive_points,
                "valid_comparison_points": valid_points,
                "all_registered_points": len(dates),
                "positive_point_fraction": positive_fraction,
                "C2_at_least_two_thirds": c2,
                "trimmed_spread": trimmed["spread"],
                "trimmed_n_in": trimmed["n_in"],
                "trimmed_n_out": trimmed["n_out"],
                "C3_remove_top10_positive": c3,
                "C4_adjacent_direction": c4,
                "all_four_pass": passed,
                "removed_tickers": ",".join(removed),
            }
        )
        for scope, metrics in (
            ("all", full),
            ("exclude_2026_exit_points", ex),
            ("remove_top10", trimmed),
        ):
            summary_rows.append({"scope": scope, **metrics})
        for row in contributions.to_dict("records"):
            top_rows.append({"group": group, **row})

    check_frame = pd.DataFrame(checks)
    summary_frame = pd.DataFrame(summary_rows)
    top_frame = pd.DataFrame(
        top_rows, columns=["group", "t", "contribution"]
    )
    population, universe_failures = population_tables(d, dates)
    reasons = pd.DataFrame(
        reason_rows, columns=["rd", "stage", "reason", "n"]
    )
    reason_totals = (
        reasons.groupby(["stage", "reason"], as_index=False)["n"].sum()
        if not reasons.empty
        else pd.DataFrame(columns=["stage", "reason", "n"])
    )
    universe_failure_totals = (
        universe_failures.groupby("reason", as_index=False)["n"].sum()
        if not universe_failures.empty
        else pd.DataFrame(columns=["reason", "n"])
    )

    if passed_groups:
        selected = next(g for g in MAIN_GROUPS if g in passed_groups)
        conclusion = (
            f"BT2四條全過的格點：{', '.join(passed_groups)}；"
            f"其中最寬者為 **{selected}**。只成立方向性證據，"
            "實際使用仍受BT1估計器skill禁止條款約束。"
        )
    else:
        conclusion = "**不立買進區間**：四個事前候選沒有任何一個四條全過。"

    restriction = bt1_price_restriction(out)
    point_counts = []
    point_spread_rows = []
    for rd in dates:
        rows = point_frame.loc[point_frame["rd"].eq(rd.date().isoformat())]
        counts = {"rd": rd.date().isoformat()}
        spreads = {"rd": rd.date().isoformat()}
        for group in GROUPS:
            row = rows.loc[rows["group"].eq(group)].iloc[0]
            counts[group + "_in"] = row["n_in"]
            counts[group + "_out"] = row["n_out"]
            spreads[group] = row["spread"]
        point_counts.append(counts)
        point_spread_rows.append(spreads)

    chain_rows = []
    for names, label in ((MAIN_GROUPS, "主格點"), (P20_GROUPS, "P20子群")):
        for left, right in zip(names[:-1], names[1:]):
            a, b = full_metrics[left]["spread"], full_metrics[right]["spread"]
            chain_rows.append(
                {
                    "type": label,
                    "adjacent": f"{left}→{right}",
                    "left_spread": a,
                    "right_spread": b,
                    "same_positive_direction": (
                        isfinite(a) and isfinite(b) and a > 0 and b > 0
                    ),
                }
            )

    text = [
        DISCLAIMER,
        "",
        "# BT2：PE估值帶方向性報酬驗證",
        "",
        f"重播 {START}～{END}，共 {len(dates)} 點；"
        f"現行財報代號數 {len(d['qf'])}。",
        "",
        "## 明確結論",
        "",
        conclusion,
        "",
        "**BT1先決限制：** " + restriction,
        "",
        "## 先決檢查及固定口徑",
        "",
        PRICE_CHECK,
        "",
        "- 全母體為eligible_universe；等權對照使用同點全母體中有完整進出場價者，"
        "包含可信度低、不能給三價、PER月份不足及股數事件被擋的股票。",
        "- PE固定5年、至少48個有效月份、cap=30，per嚴格date<rd。"
        "預註冊沒有可重播高成長識別規則，且禁止分類，因此不自行新增3年/50路線。",
        "- 可信度只用PIT業外、月營收口徑、橋接、股數、NC旗標、倍數分布及近零EPS；"
        "每個NC旗標轉成degrade Check，只留高／中，不用任何股票分類。",
        "- 股數事件窗口為[rd−5年,rd)，|m−1|≥3%排除可買資格；"
        "未知事件資料不冒充沒有事件。被擋者仍保留在有價母體對照。",
        "- 預測選股先凍結，再讀取未來價格評分。進場為rd之後首個市場交易日open；"
        "出場為進場日之後第252個市場交易日close，出場不得晚於2026-10-30。"
        "缺進出場當日價格不遞延、不以前後價格替代。",
        "- 現價為進場前一市場交易日close，日期≤rd；若該股該日缺價，"
        "不向前找舊價，不給可買資格。",
        "- G0為現價≤fair；G1/G2/G3依序另要求F4≥1.00/1.05/1.10×TTM。"
        "G0不因F4缺值自動被刪除。每組P20子群另要求現價≤cheap。",
        "- 各組區間外為同點可買且有報酬母體中不屬該組者；"
        "P20子群的外組是同一可買母體對該P20子群的補集。"
        "P20僅作附帶報告，不加入最寬格點選擇。",
        "- 全樣本以個股×重播點觀察等權合併，先逐點扣除全母體等權R，"
        "再計算內組平均超額減外組平均超額；不是直接比較兩組原始R。",
        "- 淨報酬=R−0.006，淨超額對照固定為未扣成本等權母體；"
        "兩側都扣相同成本，所以內外差與未扣成本版相同。"
        "另列全母體扣成本R供對照。0050為同一進場日及出場日close比。",
        "- 勝率分別列R>0、淨R>0、超額>0、淨超額>0；"
        "0050缺值不剔除有效個股報酬，僅從0050輔助統計分母排除。",
        "- 排除2026出場以整個重播點為單位：只保留預定出場日<2026-01-01的點。"
        "不是只刪部分個股，也不是排除2026之後才開始的年份。",
        "- 四條通過檢查：C1全樣本與排除2026後內外差均>0；"
        "C2逐點差>0比例≥2/3；C3剔除最大10檔貢獻者仍>0；C4相鄰格點方向一致。",
        "- C2分母固定為全部事前重播點；空內組／外組的點保留為NA且不算正點，"
        "不能靠略去空群提高正點比例。",
        "- 最大貢獻者按各股票對組內合併平均超額的貢獻"
        "sum(該股組內超額)/全部組內觀察數排序；選前10個不同代號，"
        "從內外兩側所有重播觀察整檔移除，固定原始等權對照後重算。"
        "不足10檔則全部移除，若無可比較內外組，C3不通過。",
        "- C4操作化為G0→G1→G2→G3每個相鄰端的內外差同為正，"
        "即整條鏈同向；不新增差值大小單調要求。P20的同項僅為子群診斷。",
        "- 表中報酬與比例均為小數比率，非百分比；NA不是0。",
        "",
        "## 母體與NC/F4可算比例",
        "",
        "base_universe為≥8季、有毛利、連續四季TTM>0；"
        "eligible另要求nowcast.ok，NC/F4比例以base_universe為分母。",
        "",
        md_table(population),
        "## 季報／估計器失敗原因",
        "",
        md_table(universe_failure_totals),
        "### 逐點季報／估計器原因",
        "",
        md_table(universe_failures),
        "## PER有效月數、可信度及有價母體先決檢查",
        "",
        md_table(
            audit_frame,
            [
                "rd", "entry_date", "exit_date", "priced_universe",
                "buyable_before_price_scoring", "buyable_with_returns",
                "ew_return", "ew_return_net", "benchmark_0050_n",
                "per_months_n", "per_months_min", "per_months_p25",
                "per_months_p50", "per_months_p75", "per_months_max",
                "per_months_ge48", "event_blocked",
                "confidence_高", "confidence_中", "confidence_低",
                "confidence_不給價", "confidence_未計算", "confidence_例外",
            ],
        ),
        "PER有效月數統計對每點eligible母體計算，不只看通過估值篩選者；"
        "可買資格失敗原因可重複計數。",
        "",
        md_table(reason_totals),
        "### 逐點可買條件／價格失敗原因",
        "",
        md_table(reasons),
        "## 四條通過檢查（主格點及P20子群診斷）",
        "",
        md_table(
            check_frame,
            [
                "group", "candidate", "full_spread", "exclude_2026_spread",
                "C1_full_and_excluded_positive",
                "positive_points", "valid_comparison_points",
                "all_registered_points", "positive_point_fraction",
                "C2_at_least_two_thirds", "trimmed_spread",
                "trimmed_n_in", "trimmed_n_out", "C3_remove_top10_positive",
                "C4_adjacent_direction", "all_four_pass",
            ],
        ),
        "排除2026出場保留重播點："
        + (", ".join(str(rd.date()) for rd in retained_dates) or "無"),
        "",
        "### 相鄰格點方向逐對檢查",
        "",
        md_table(pd.DataFrame(chain_rows)),
        "## 合併報酬、檔數及內外差",
        "",
        "n為個股×重播點觀察數；stocks為不同代號數。",
        "",
        md_table(
            summary_frame,
            [
                "scope", "group", "n_in", "n_out", "stocks_in", "stocks_out",
                "in_return", "out_return", "in_return_net", "out_return_net",
                "in_excess", "out_excess", "in_excess_net", "out_excess_net",
                "spread", "spread_net",
            ],
        ),
        "## 勝率與0050輔助對照",
        "",
        md_table(
            summary_frame.loc[summary_frame["scope"].eq("all")],
            [
                "group", "in_win_rate", "out_win_rate",
                "in_win_rate_net", "out_win_rate_net",
                "in_excess_win_rate", "out_excess_win_rate",
                "in_excess_win_rate_net", "out_excess_win_rate_net",
                "in_0050_n", "out_0050_n",
                "in_0050_return", "out_0050_return",
                "in_0050_excess", "out_0050_excess",
                "in_0050_excess_net", "out_0050_excess_net",
                "in_0050_win_rate", "out_0050_win_rate",
            ],
        ),
        "## 逐點內外檔數",
        "",
        md_table(pd.DataFrame(point_counts)),
        "## 逐點內外超額差",
        "",
        md_table(pd.DataFrame(point_spread_rows)),
        "完整逐點逐組的未扣／扣成本報酬、勝率、0050及先決檢查"
        "寫於bt2_groups.csv。",
        "",
        "## 被剔除的最大10檔貢獻者",
        "",
        md_table(check_frame, ["group", "removed_tickers"]),
        md_table(top_frame),
        "## 已知限制",
        "",
        LIMITATIONS,
        "",
        DISCLAIMER,
        "",
    ]
    (out / "bt2_summary.md").write_text("\n".join(text), encoding="utf-8")


if __name__ == "__main__":
    main()
```
