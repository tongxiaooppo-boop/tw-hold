"""農曆新年窗：除夕前 3 天～除夕後 6 天（含頭尾，共 10 天）。各指標共用（2026-11-20 使用者定）。

用途：月資料（月營收 MoM）碰到這段期間的月份，季節失真，不做月增判斷。
除夕表寫死；2021～2026 已用 prices_raw_close 休市日自查通過（research/rev_growth_rank_2026-11/out/lny_audit_r2.csv）。
表外年份 → KeyError，請補表，不要猜。
"""
from __future__ import annotations

import pandas as pd

BEFORE_DAYS = 3
AFTER_DAYS = 6

LNY_EVE: dict[int, str] = {
    2015: "2015-02-18", 2016: "2016-02-07", 2017: "2017-01-27", 2018: "2018-02-15",
    2019: "2019-02-04", 2020: "2020-01-24", 2021: "2021-02-11", 2022: "2022-01-31",
    2023: "2023-01-21", 2024: "2024-02-09", 2025: "2025-01-28", 2026: "2026-02-16",
    2027: "2027-02-05", 2028: "2028-01-25", 2029: "2029-02-12", 2030: "2030-02-02",
}


def lunar_new_year_window(year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """該年（國曆年）除夕所在的新年窗 (start, end)，含頭尾。"""
    eve = pd.Timestamp(LNY_EVE[int(year)])
    return eve - pd.Timedelta(days=BEFORE_DAYS), eve + pd.Timedelta(days=AFTER_DAYS)


def months_touching_lny(year: int) -> list[str]:
    """該年新年窗碰到的月份 'YYYY-MM'（由小到大）。"""
    s, e = lunar_new_year_window(year)
    return [str(p) for p in pd.period_range(s.to_period("M"), e.to_period("M"), freq="M")]


def month_touches_lny(month: str) -> bool:
    """'YYYY-MM' 是否碰到新年窗；表外年份 → False（新年窗只會落在 1、2 月，其他月份不用查表）。"""
    p = pd.Period(str(month)[:7], "M")
    if p.month > 2:
        return False
    if p.year not in LNY_EVE:
        return False
    return str(p) in months_touching_lny(p.year)
