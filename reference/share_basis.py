"""股數基準（估值 2.0，upgrade_guide §4-2）：事件倍數、面額推回、現金減資剔除區間。

【框架由 Opus 定，實作者不得改介面】函式本體由 P1 實作。

事件來源一律 `reference.corporate_actions.SPLITS`（{裸代號: [ {date, type, m, pf, src} ]}），
type ∈ {ex_both, ex_rights, cap_reduction, par_change, split}。m＝股數倍數（1 股變 m 股），
m=None 表示無法換算股數（cap_reduction 多為現金減資）。
SPLITS 載入失敗時 corporate_actions 會設 EVENTS_OK=False；這裡遇到 EVENTS_OK=False 一律 raise
EventsUnavailable（T-17：不得靜默當成「沒有事件」）。
"""
from __future__ import annotations

import math

import pandas as pd

from reference import corporate_actions as ca


class EventsUnavailable(RuntimeError):
    """事件表讀不到；依賴股數事件的估值要停用，不可當成無事件。"""


def events(ticker: str) -> list[dict]:
    """該檔全部事件（date 轉 Timestamp），依日期排序；裸代號比對（"2330.TW" → "2330"）。"""
    if not ca.EVENTS_OK:
        raise EventsUnavailable("股數事件表讀取失敗")
    rows = [dict(e, date=pd.Timestamp(e["date"]))
            for e in ca.SPLITS.get(str(ticker).split(".")[0], [])]
    return sorted(rows, key=lambda e: e["date"])


def share_factor_after(ticker: str, t: pd.Timestamp) -> float:
    """t 之後（事件日 > t，不含 t）所有 m 有限且 >0 的事件 m 之乘積；無事件 = 1.0。
    用途：price_adj(t) = 原始收盤(t) ÷ share_factor_after(t)，把歷史價換到今天的股數基準（不做股利還原）。"""
    factor = 1.0
    for e in events(ticker):
        m = e.get("m")
        if e["date"] > pd.Timestamp(t) and m is not None and math.isfinite(m) and m > 0:
            factor *= m
    return factor


def _positive(value) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def common_par_today(basic: dict | None) -> float:
    """Official par, then paid-in capital per total issued share, then 10."""
    basic = basic or {}
    par = basic.get("par_value")
    if _positive(par):
        return float(par)
    issued = basic.get("issued_shares")
    pref = basic.get("preferred_shares")
    total = 0.0
    if issued is not None and math.isfinite(issued) and issued >= 0:
        total = issued + (pref if _positive(pref) else 0)
    capital = basic.get("paid_in_capital")
    return float(capital / total) if _positive(capital) and total > 0 else 10.0


def common_equity(ticker: str, latest, basic: dict | None = None) -> float | None:
    pref = (basic or {}).get("preferred_shares")
    pref = pref if _positive(pref) else 0.0
    par = par_value_at(ticker, latest["period_end"], common_par_today(basic))
    equity = latest["equity_parent"] - pref * par
    return float(equity) if _positive(equity) else None


def exchange_outstanding_ratio(ticker, q_rows, exch, upto) -> float | None:
    """Exchange outstanding/capital shares, using only visible, event-free days.

    q_rows.attrs['basic'] optionally supplies par and preferred-share metadata.
    All inputs are supplied in memory; this function performs no I/O.
    """
    if exch is None or exch.empty or not {'date', 'close', 'pbr'} <= set(exch.columns):
        return None
    upto = pd.Timestamp(upto)
    basic = q_rows.attrs.get('basic', {}) or {}
    days = exch[['date', 'close', 'pbr']].copy()
    days['date'] = pd.to_datetime(days['date'])
    days = days[(days.date <= upto) & (days.close > 0) & (days.pbr > 0)
                & days.close.map(math.isfinite) & days.pbr.map(math.isfinite)]
    days = days.drop_duplicates('date', keep='last')
    quarters = q_rows.sort_values('period_end').drop_duplicates('period_end', keep='last')
    visible = quarters[[ca.report_deadline(d) <= upto for d in quarters.period_end]].tail(4)
    ev = events(ticker)
    for row in reversed(visible.to_dict('records')):
        end = pd.Timestamp(row['period_end'])
        start = ca.report_deadline(end)
        stop = ca.report_deadline((end + pd.offsets.QuarterEnd(1)).normalize())
        sample = days[(days.date >= start) & (days.date < stop)]
        after = [e['date'] for e in ev if e['date'] > end]
        if after:
            sample = sample[sample.date < min(after)]
        if len(sample) < 5:
            continue
        par = par_value_at(ticker, end, common_par_today(basic))
        pref = basic.get('preferred_shares')
        pref = pref if _positive(pref) else 0.0
        cap = row.get('capital_stock')
        cap_shares = cap / par - pref if _positive(cap) and _positive(par) else None
        equity = common_equity(ticker, row, basic)
        bv = float((sample.close / sample.pbr).median())
        if _positive(cap_shares) and _positive(equity) and _positive(bv):
            return float(equity / bv / cap_shares)
    return None


def common_shares(ticker: str, latest, quarters: pd.DataFrame,
                  basic: dict | None = None, *, live: bool = False,
                  eps_min: float = 0.05, exch=None, upto=None) -> tuple[float | None, str]:
    """Capital base (live falls back to official issued), exchange treasury ratio, then reverse.

    Capital base comes first in live mode too: it is the same quarter as the equity, while
    issued_shares is today's count and drifts on CB conversions / capital changes that are not
    in the event table (11/3 r3 check: 42 of 45 such stocks matched the exchange via capital).
    """
    basic = basic or {}
    base = shares_today_basis(ticker, latest.get('capital_stock'), latest['period_end'],
                              common_par_today(basic), basic.get('preferred_shares'))
    src = 'capital'
    if not _positive(base) and live:
        base = basic.get('issued_shares')
        src = 'official'
    if _positive(base):
        rows = quarters[quarters.period_end <= latest['period_end']].copy()
        rows.attrs['basic'] = basic
        ratio = exchange_outstanding_ratio(ticker, rows, exch,
                    pd.Timestamp.today().normalize() if upto is None else upto)
        if ratio is not None and .5 <= ratio <= .97:
            return float(base * ratio), 'treasury'
        return float(base), src
    candidates = quarters[quarters.period_end <= latest['period_end']].sort_values('period_end').tail(5)
    for r in reversed(candidates.to_dict('records')):
        eps, ni = r.get('eps'), r.get('ni_parent')
        if (eps is not None and math.isfinite(eps) and abs(eps) >= eps_min
                and ni is not None and math.isfinite(ni) and _positive(ni / eps)):
            return float(ni / eps), 'reverse'
    return None, ''


def par_value_at(ticker: str, t: pd.Timestamp, today_par: float | None) -> float | None:
    """t 當時面額 = today_par × Π(事件日 > t 的 par_change 事件 m)；today_par 為 None → None。"""
    rows = events(ticker)
    if today_par is None:
        return None
    value = float(today_par)
    for e in rows:
        m = e.get("m")
        if (e["date"] > pd.Timestamp(t) and e.get("type") == "par_change"
                and m is not None and math.isfinite(m) and m > 0):
            value *= m
    return value



def shares_today_basis(ticker: str, capital_stock: float | None, period_end: pd.Timestamp,
                       par_today: float | None, preferred_shares: float | None) -> float | None:
    """季末股本依當期面額扣除特別股，再按期後事件換成今天基準普通股數。
    股本、當期面額或結果非有限正數回 None；EventsUnavailable 不攔截。
    """
    def positive(value):
        return value is not None and math.isfinite(value) and value > 0

    if not positive(capital_stock):
        return None
    par_t = par_value_at(ticker, period_end, par_today if positive(par_today) else 10.0)
    if not positive(par_t):
        return None
    pref = preferred_shares if positive(preferred_shares) else 0.0
    shares = (capital_stock / par_t - pref) * share_factor_after(ticker, period_end)
    return float(shares) if positive(shares) else None


def excluded_months(ticker: str) -> set[pd.Period]:
    """現金減資等無法換算的區間（月）。對每筆 type=="cap_reduction" 且 m 為 None 的事件 e：
    Q＝第一個 period_end ≥ e.date 的曆季季末；V＝report_deadline(Q)；
    剔除月份＝[e.date 所在月, V 所在月的前一個月]（V 當月月底財報已可見，不剔除）。
    回傳 pd.Period("M") 的集合。"""
    excluded = set()
    for e in events(ticker):
        if e.get("type") == "cap_reduction" and e.get("m") is None:
            quarter_end = e["date"].to_period("Q").end_time.normalize()
            visible = ca.report_deadline(quarter_end).to_period("M")
            excluded.update(pd.period_range(e["date"].to_period("M"), visible - 1, freq="M"))
    return excluded
