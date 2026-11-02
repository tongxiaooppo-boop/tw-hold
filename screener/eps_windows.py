"""EPS 窗口：近 4 季／前瞻 4 季／已公布 4 季（估值 2.0，upgrade_guide §3）。

【框架由 Opus 定，實作者不得改介面、常數名、dataclass 欄位】函式本體由 P1 實作。

輸入
- q：單季財報 DataFrame，欄位 period_end（季末 Timestamp）、revenue、gross_profit、op_income、
  pretax_income、net_income、ni_parent、eps（皆元／元每股，EPS 已由 loader 調到最新股數基準）。
  可能未排序、可能有重複季（取最後一筆）、可能缺季。
- monthly：月營收 Series，index＝月初 Timestamp，值＝元；可能缺月、可能有 NaN。
- asof：評價日。歷史重建（build_multiples）用同一組函式、asof＝各月底。
- live：True＝產品端「抓到就用」：資料裡有的財報季、有的月營收都視為已可見（tw-hold `d0900f3`
  線上口徑）；False＝回測／歷史重建：財報季要 asof ≥ report_deadline(period_end)，
  月營收要 asof ≥ 次月 10 日。

可見性（live=False）
- 財報季已公布 ⇔ eps、revenue 皆有限值，且 asof ≥ reference.corporate_actions.report_deadline(period_end)
  （Q1 5/15、Q2 8/14、Q3 11/14、Q4 隔年 3/31）。
- 月份 m 營收可見 ⇔ 值有限且 > 0，且 asof ≥ (m 的次月) 10 日。
- 「應公布未公布」：asof ≥ 次月 10 日但值缺 → 該季不可試算（status="not_estimable"）。
live=True 時「已到期但缺」的判斷照樣做（到期日同上），只是「有值就可見」不必等到期。

窗口規則（§3-1）
- P＝最新已公布季。四季必須是曆季相鄰（用 pd.Period("Q")），中間缺季 → ok=False、status="no_data"。
- 近 4 季：P+1 三個月營收都可見 → 末季＝P+1（試算）；否則末季＝P。最多 1 個試算季。
- 財報延遲：P+1、P+2 兩季三個月營收都可見 → 近 4 季＝P−3..P 全實際、status="report_late"；
  前瞻也回傳同一組、status="report_late"。
- 前瞻 4 季：E＝近 4 季末季；E+1 有 ≥1 個可見月 → 末季＝E+1（試算），窗口內非實際的季都試算，
  最多 2 個試算季；E+1 沒有可見月 → 與近 4 季相同（quarters 相同、status 同近 4 季）。
- 試算失敗（§3-2 參數不可用）：近 4 季退回 P−3..P 全實際、status="ok"、reason 寫原因；
  前瞻 ok=False、status="not_estimable"、reason 寫原因。

試算季公式（§3-2）— 參數一律來自 P（params_from＝str(P)）
  revenue = 已可見月份實際 + Σ 缺月補值（§3-3）
  gm_last = P.gross_profit / P.revenue；opex_last = (P.gross_profit − P.op_income) / P.revenue
  op      = revenue × (gm_last − opex_last)
  nonop   = median(近 8 個已公布季的 pretax − op_income)，有效 <4 季 → 不試算
  tax8    = 1 − Σnet_income / Σpretax（近 8 季）；抵銷比(pretax) < OFFSET_MIN → 不試算；
            Σpretax ≤ 0 或超出 [0, TAX_MAX] → TAX_DEFAULT 並 flag
  minority8 = 1 − Σni_parent / Σnet_income；抵銷比(net) < OFFSET_MIN、Σni_parent×Σnet < 0、
            或 minority8 ∉ [−MINORITY_MAX, MINORITY_MAX] → 不試算
  稅只課在賺錢的季：pretax = op + nonop；pretax ≤ 0 時 t = 0（沿用 bug4 H1，tw-hold 98809e2）
  ni_par  = pretax × (1 − t) × (1 − minority8)
  shares  = P.ni_parent / P.eps（|P.eps| ≥ EPS_MIN 才可推）；推不出 → 不試算，不退回中位數
            T-19：與 P−1 隱含股數差 > SHARE_JUMP 且 P−1 可推 → 改用 P−1 並 flag（股數事件判斷在 P3 接）
  eps     = ni_par / shares
  抵銷比(x) = |Σx| / Σ|x|

缺月補值（§3-3）
- 一般：去年同月 × (1 + g_q)，g_q＝該季已可見月份合計 ÷ 去年同月份合計 − 1；fill_method="yoy_q"
- 該季是 Q1 且只有 1 月可見（農曆年）：g_q 改用「最近 3 個可見月合計 ÷ 去年同 3 個月合計 − 1」；"q1_3m"
- 去年同月缺或 ≤0：用該季已可見月份平均；"avg"
- 三個月都可見 → 不算 g_q（T-8），fill_method=None
- 金融股（caller 傳 financial=True）→ 不試算
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import math

import pandas as pd

from reference import corporate_actions as ca

# ── 常數（upgrade_guide §12；實作者不得改名或改值）──
EPS_MIN = 0.05          # 推隱含股數的最小 |EPS|
OFFSET_MIN = 0.10       # 抵銷比門檻
TAX_DEFAULT = 0.20
TAX_MAX = 0.35
MINORITY_MAX = 0.5
NONOP_QUARTERS = 8
NONOP_MIN_VALID = 4
SHARE_JUMP = 0.10       # T-19 隱含股數跳動
MAX_EST_TTM = 1
MAX_EST_FWD = 2
REVENUE_VISIBLE_DAY = 10

STATUS = ("ok", "report_late", "no_data", "not_estimable")
FILL_METHODS = (None, "yoy_q", "q1_3m", "avg")


@dataclass(frozen=True)
class QuarterRow:
    q: str                   # "2026Q3"
    kind: str                # "actual" | "est"
    eps: float
    rev: float | None
    months_known: int        # est 季已可見月數（actual 為 3）
    fill_method: str | None  # None | "yoy_q" | "q1_3m" | "avg"
    params_from: str | None  # 參數來源季，如 "2026Q2"；actual 為 None


@dataclass(frozen=True)
class EstDetail:
    """一個試算季的推導（畫面 9-1 推導表用；同一試算季在近 4 季與前瞻共用同一個物件）。"""
    q: str
    months: tuple[tuple[str, float, str], ...]   # (YYYY-MM, 營收, "actual"|fill_method)
    revenue: float
    gm_last: float
    opex_last: float
    op: float
    nonop: float
    tax: float               # 實際套用的稅率（pretax ≤0 時 0）
    minority: float
    ni_parent: float
    shares: float
    shares_from: str         # "2026Q2"；T-19 改用前季時寫 "2026Q1（Q2 股數跳動）"
    eps: float
    flags: tuple[str, ...]   # 例："稅率超出 0～35%，改用 20%"


@dataclass(frozen=True)
class EpsWindow:
    ok: bool
    status: str              # STATUS 之一
    reason: str | None
    quarters: tuple[QuarterRow, ...]   # 連續 4 季，舊→新；ok=False 時可為空
    eps: float | None        # 四季合計
    n_est: int
    details: tuple[EstDetail, ...] = ()   # 窗口內試算季的推導，舊→新

    def to_dict(self) -> dict:
        return asdict(self)


def quarter_visible(period_end: pd.Timestamp, asof: pd.Timestamp) -> bool:
    """live=False 口徑：asof ≥ report_deadline(period_end)。"""
    return pd.Timestamp(asof) >= ca.report_deadline(period_end)


def month_visible(month: pd.Timestamp, asof: pd.Timestamp) -> bool:
    """asof ≥ month 的次月 REVENUE_VISIBLE_DAY 日。"""
    deadline = pd.Timestamp(month).to_period("M").start_time + pd.offsets.MonthBegin(1)
    deadline += pd.Timedelta(days=REVENUE_VISIBLE_DAY - 1)
    return pd.Timestamp(asof) >= deadline


def reported_window(q: pd.DataFrame, asof: pd.Timestamp, live: bool = False) -> EpsWindow:
    """已公布 4 季：P−3..P，全 actual。少於 4 季或有缺季 → ok=False、status="no_data"。
    所有股票（含金融）都要給（T-9）。"""
    actual = _actuals(q, asof, live)
    if not actual:
        return _unavailable("no_data", "沒有已公布財報")
    return _assemble(actual, max(actual))


def ttm_window(q: pd.DataFrame, monthly: pd.Series, asof: pd.Timestamp,
               live: bool = False, financial: bool = False) -> EpsWindow:
    """近 4 季（見模組說明）。financial=True → 等於 reported_window。"""
    actual = _actuals(q, asof, live)
    if not actual:
        return _unavailable("no_data", "沒有已公布財報")
    p = max(actual)
    reported = _assemble(actual, p)
    if financial:
        return reported
    months = _months(monthly, asof, live)
    if _known(p + 1, months) == 3 and _known(p + 2, months) == 3:
        return _assemble(actual, p, status="report_late", reason="財報延遲")
    if _known(p + 1, months) < 3:
        return _assemble(actual, p, reason="新季營收未齊")
    try:
        row, detail = _estimate(p + 1, actual, months, asof)
    except ValueError as exc:
        return _assemble(actual, p, reason=str(exc))
    return _assemble(actual, p + 1, {p + 1: (row, detail)})


def fwd_window(q: pd.DataFrame, monthly: pd.Series, asof: pd.Timestamp,
               base: EpsWindow | None = None, live: bool = False,
               financial: bool = False) -> EpsWindow:
    """前瞻 4 季（見模組說明）。base＝同一 asof 的 ttm_window 結果（None 就自己算）。
    financial=True → 與近 4 季相同。"""
    if base is None:
        base = ttm_window(q, monthly, asof, live=live, financial=financial)
    if financial or base.status in ("report_late", "no_data") or not base.quarters:
        return base
    end = pd.Period(base.quarters[-1].q, freq="Q")
    months = _months(monthly, asof, live)
    if _known(end + 1, months) == 0:
        return base
    actual = _actuals(q, asof, live)
    estimates = {
        pd.Period(row.q, freq="Q"): (row, detail)
        for row in base.quarters if row.kind == "est"
        for detail in base.details if detail.q == row.q
    }
    try:
        for period in pd.period_range(end - 2, end + 1, freq="Q"):
            if period not in actual and period not in estimates:
                estimates[period] = _estimate(period, actual, months, asof)
    except ValueError as exc:
        return _unavailable("not_estimable", str(exc))
    return _assemble(actual, end + 1, estimates)


def windows(q: pd.DataFrame, monthly: pd.Series, asof: pd.Timestamp,
            live: bool = False, financial: bool = False) -> dict[str, EpsWindow]:
    """一次算三個：{"reported", "ttm", "fwd"}。前瞻與近 4 季共用的試算季必須是同一個 EstDetail。"""
    reported = reported_window(q, asof, live=live)
    ttm = ttm_window(q, monthly, asof, live=live, financial=financial)
    fwd = fwd_window(q, monthly, asof, base=ttm, live=live, financial=financial)
    return {"reported": reported, "ttm": ttm, "fwd": fwd}



def nonop_median(rows: list[dict]) -> float | None:
    """P4：業外中位數（_estimate 與 val_card 共用，不准兩份）。rows＝最近 NONOP_QUARTERS 個已公布季（dict 含
    pretax_income、op_income）；有限的 pretax−op 少於 NONOP_MIN_VALID 個 → None；否則中位數（float）。
    _estimate 改呼叫本函式，None 時照舊 raise「試算停用：業外有效季數不足」。"""
    raise NotImplementedError


def _finite(value) -> bool:
    return value is not None and bool(pd.notna(value)) and math.isfinite(float(value))


def _actuals(q: pd.DataFrame, asof: pd.Timestamp, live: bool) -> dict:
    if q.empty:
        return {}
    rows = {}
    # 先按輸入順序去重，再判可見性，不讓舊筆蓋過最後一筆。
    for row in q.to_dict("records"):
        pe = pd.Timestamp(row["period_end"])
        if pd.notna(pe):
            rows[pe.to_period("Q")] = row
    return {p: r for p, r in rows.items()
            if _finite(r.get("eps")) and _finite(r.get("revenue"))
            and (live or quarter_visible(p.end_time.normalize(), asof))}


def _months(monthly: pd.Series, asof: pd.Timestamp, live: bool) -> dict:
    raw = {pd.Timestamp(m).to_period("M"): v for m, v in monthly.items()}
    return {m: float(v) for m, v in raw.items()
            if _finite(v) and v > 0 and (live or month_visible(m.start_time, asof))}


def _quarter_months(period: pd.Period) -> pd.PeriodIndex:
    return pd.period_range(period.asfreq("M", "start"), periods=3, freq="M")


def _known(period: pd.Period, months: dict) -> int:
    return sum(m in months for m in _quarter_months(period))


def _unavailable(status: str, reason: str) -> EpsWindow:
    return EpsWindow(False, status, reason, (), None, 0)


def _assemble(actual: dict, end: pd.Period, estimates: dict | None = None,
              status: str = "ok", reason: str | None = None) -> EpsWindow:
    estimates = estimates or {}
    rows, details = [], []
    for period in pd.period_range(end - 3, end, freq="Q"):
        if period in estimates:
            row, detail = estimates[period]
            rows.append(row)
            details.append(detail)
        elif period in actual:
            r = actual[period]
            rows.append(QuarterRow(str(period), "actual", float(r["eps"]),
                                   float(r["revenue"]), 3, None, None))
        else:
            return _unavailable("no_data", f"缺少 {period} 財報")
    return EpsWindow(True, status, reason, tuple(rows), sum(r.eps for r in rows),
                     len(details), tuple(details))


def _revenue(period: pd.Period, months: dict, asof: pd.Timestamp) -> tuple:
    target = _quarter_months(period)
    known = [m for m in target if m in months]
    for m in target:
        if m not in months and month_visible(m.start_time, asof):
            raise ValueError(f"{m.month} 月營收應公布未公布")
    if not known:
        raise ValueError("新季營收未出")
    if len(known) == 3:
        return tuple((str(m), months[m], "actual") for m in target), None, 3
    average = sum(months[m] for m in known) / len(known)
    growth_months = known
    method = "yoy_q"
    if period.quarter == 1 and known == [target[0]]:
        growth_months = sorted(m for m in months if m <= known[0])[-3:]
        method = "q1_3m"
    usable = (len(growth_months) == (3 if method == "q1_3m" else len(known))
              and all(m - 12 in months for m in growth_months))
    factor = (sum(months[m] for m in growth_months)
              / sum(months[m - 12] for m in growth_months)) if usable else None
    result, methods = [], []
    for m in target:
        if m in months:
            result.append((str(m), months[m], "actual"))
        else:
            fill = method if factor is not None and m - 12 in months else "avg"
            value = months[m - 12] * factor if fill != "avg" else average
            result.append((str(m), value, fill))
            methods.append(fill)
    return tuple(result), ("avg" if "avg" in methods else method), len(known)


def _shares(row: dict) -> float | None:
    eps, ni = row.get("eps"), row.get("ni_parent")
    if not _finite(eps) or abs(eps) < EPS_MIN or not _finite(ni):
        return None
    shares = ni / eps
    return float(shares) if _finite(shares) and shares > 0 else None


def _estimate(period: pd.Period, actual: dict, months: dict,
              asof: pd.Timestamp) -> tuple[QuarterRow, EstDetail]:
    p = max(actual)
    last = actual[p]
    month_rows, fill, count = _revenue(period, months, asof)
    revenue = sum(r[1] for r in month_rows)
    flags = []
    if (last["revenue"] <= 0 or not _finite(last.get("gross_profit"))
            or not _finite(last.get("op_income"))):
        raise ValueError("試算停用：最新季毛利或費用率缺漏")
    gm = last["gross_profit"] / last["revenue"]
    opex = (last["gross_profit"] - last["op_income"]) / last["revenue"]
    # 取最近八個已公布季；個別參數缺值不當成零。
    recent = [actual[k] for k in sorted(actual)[-NONOP_QUARTERS:]]
    nonops = [r["pretax_income"] - r["op_income"] for r in recent
              if _finite(r.get("pretax_income")) and _finite(r.get("op_income"))]
    if len(nonops) < NONOP_MIN_VALID:
        raise ValueError("試算停用：業外有效季數不足")
    nonop = float(pd.Series(nonops).median())
    tax_rows = [r for r in recent if _finite(r.get("pretax_income"))
                and _finite(r.get("net_income"))]
    pretax_sum = sum(r["pretax_income"] for r in tax_rows)
    pretax_abs = sum(abs(r["pretax_income"]) for r in tax_rows)
    if pretax_abs == 0 or abs(pretax_sum) / pretax_abs < OFFSET_MIN:
        raise ValueError("試算停用：稅前抵銷比過小")
    tax = 1 - sum(r["net_income"] for r in tax_rows) / pretax_sum
    if pretax_sum <= 0 or not 0 <= tax <= TAX_MAX:
        tax = TAX_DEFAULT
        flags.append("稅率不適用，改用 20%")
    minority_rows = [r for r in recent if _finite(r.get("net_income"))
                     and _finite(r.get("ni_parent"))]
    net_sum = sum(r["net_income"] for r in minority_rows)
    net_abs = sum(abs(r["net_income"]) for r in minority_rows)
    parent_sum = sum(r["ni_parent"] for r in minority_rows)
    if net_abs == 0 or abs(net_sum) / net_abs < OFFSET_MIN:
        raise ValueError("試算停用：淨利抵銷比過小")
    minority = 1 - parent_sum / net_sum
    if parent_sum * net_sum < 0 or not -MINORITY_MAX <= minority <= MINORITY_MAX:
        raise ValueError("試算停用：少數股權比不適用")
    shares = _shares(last)
    if shares is None:
        raise ValueError(f"試算停用：{p} EPS 太小或歸母淨利缺漏，推不出股數")
    shares_from = str(p)
    previous = _shares(actual[p - 1]) if p - 1 in actual else None
    if previous is not None and abs(shares / previous - 1) > SHARE_JUMP:
        shares = previous
        shares_from = f"{p - 1}（Q{p.quarter} 股數跳動）"
        flags.append(f"{p} 股數跳動，改用前季")
    op = revenue * (gm - opex)
    pretax = op + nonop
    applied_tax = tax if pretax > 0 else 0.0
    parent = pretax * (1 - applied_tax) * (1 - minority)
    eps = parent / shares
    if not all(_finite(v) for v in (revenue, gm, opex, op, nonop, parent, eps)):
        raise ValueError("試算停用：推算結果非有限值")
    detail = EstDetail(str(period), month_rows, revenue, gm, opex, op, nonop,
                       applied_tax, minority, parent, shares, shares_from, eps, tuple(flags))
    row = QuarterRow(str(period), "est", eps, revenue, count, fill, str(p))
    return row, detail
