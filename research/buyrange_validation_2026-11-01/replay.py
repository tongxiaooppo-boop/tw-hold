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
    values = pd.to_numeric(q["eps"], errors="coerce").to_numpy(dtype=float).copy()
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
