"""自建歷史倍數（估值 2.0，upgrade_guide §4、§5-4）：PE、前瞻 PE、PB 月度序列、有效月數、上修判斷。

【框架由 Opus 定，實作者不得改介面、常數、欄位、docstring】函式本體由 P2 實作。

每個完整月份的月底交易日 t（asof＝t，live=False）：
- price_adj(t) = 原始收盤(t) ÷ share_basis.share_factor_after(ticker, t)。**不做股利還原**。
- eps_ttm = eps_windows.ttm_window(q, monthly_rev, asof=t, live=False, financial).eps；
  eps_fwd = eps_windows.fwd_window(..., base=上面的 ttm).eps；窗口 ok=False → NaN。
  q 由呼叫端先做 corporate_actions.adjust_eps（EPS 已在最新股數基準），這裡不再調整。
- bvps(t)：最近一季「quarter_visible(period_end, t)」且 equity_parent 有限 >0 的季 Q；
  股數＝Q 的隱含股數 ni_parent ÷ eps（|eps| ≥ EPS_MIN、結果有限 >0；ni_parent（loader 已依規則頂替）；eps 已在最新基準，
  所以股數也在最新基準）。Q 推不出股數 → 往前找最多 4 個「可見」季中最近一個推得出的；都沒有 → NaN。
  bvps = Q 的 equity_parent ÷ 該股數。
- 倍數（T-3：有效值＝有限且 >0）：
  pe     = price_adj ÷ eps_ttm，有效＝price_adj 有限 >0、eps_ttm 有限 ≥ EPS_MIN、pe ≤ MULT_MAX_PE、非 excluded
  pe_fwd = 同上，用 eps_fwd
  pb     = price_adj ÷ bvps，有效＝price_adj、bvps 有限 >0、非 excluded（PB 無上限）
  無效月 pe／pe_fwd／pb 寫 NaN、valid_* 寫 False；**月份列保留**（T-4、T-7）。
- excluded：月份 ∈ share_basis.excluded_months(ticker)。
- pe_exchange：交易所 PER 在同一天 t 的值（ticker 裸代號比對）；沒有、≤0 或非有限 → NaN。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from reference import share_basis as sb
from screener import eps_windows as ew

MULT_MAX_PE = 100.0
EPS_MIN = 0.05
VALID_MIN = {"normal": 36, "growth": 30, "pb": 60}
VALID_EXIT = {"normal": 33, "growth": 27, "pb": 54}
WINDOW_MONTHS = {"normal": 60, "cyclical": 60, "growth": 36, "pb": None}   # None＝全部歷史
MULT_CAP = {"normal": 30.0, "normal_exc": 50.0, "growth": 50.0, "pb": None}
PCTS = (0.20, 0.50, 0.80)
REV_STEP = 0.02
REV_STREAK = 2
REV_EVENTS = ("normal", "roll", "report")

HIST_COLUMNS = ("ticker", "month", "date", "price_adj", "eps_ttm", "eps_fwd", "bvps",
                "n_est_ttm", "n_est_fwd", "pe", "pe_fwd", "pb",
                "valid_pe", "valid_pe_fwd", "valid_pb", "excluded", "pe_exchange")


def last_complete_month(asof: pd.Timestamp) -> pd.Period:
    """asof ≥ 該月最後一個日曆日 → 該月算完整；否則上一個月。回傳 pd.Period("M")。
    例：2026-11-02 → 2026-10；2026-10-31 → 2026-10；2026-10-30 → 2026-09。"""
    asof = pd.Timestamp(asof)
    month = asof.to_period("M")
    return month if asof.normalize() >= month.end_time.normalize() else month - 1


def monthly_closes(raw_close: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """日線原始收盤（ticker, date, close；ticker 可帶 .TW／.TWO）→ 每檔每個完整月份
    （≤ last_complete_month(asof)）**最後一個交易日那一列**（ticker 裸代號, month "YYYY-MM", date, close）。
    T-5：先取月底那一列再看值；月底那天 close 是 NaN 就保留 NaN，不往前找。依 ticker、month 排序。"""
    rows = raw_close.loc[:, ["ticker", "date", "close"]].copy()
    rows["ticker"] = rows["ticker"].astype(str).str.split(".").str[0]
    rows["date"] = pd.to_datetime(rows["date"])
    rows["month"] = rows["date"].dt.to_period("M")
    rows = rows[rows["month"] <= last_complete_month(asof)]
    rows = rows.sort_values(["ticker", "date"], kind="stable")
    rows = rows.drop_duplicates(["ticker", "month"], keep="last")
    rows["month"] = rows["month"].astype(str)
    return rows[["ticker", "month", "date", "close"]].reset_index(drop=True)


def build_history(ticker: str, q: pd.DataFrame, monthly_rev: pd.Series, closes: pd.DataFrame,
                  per: pd.DataFrame | None, financial: bool = False) -> pd.DataFrame:
    """單檔月度倍數序列，欄位＝HIST_COLUMNS（順序照常數），每個 closes 列一列，month 舊→新。
    q＝該檔季報（已 adjust_eps）；monthly_rev＝月營收（index＝月初 Timestamp）；
    closes＝該檔 monthly_closes 結果；per＝交易所 PER（ticker, date, per；可為 None → pe_exchange 全 NaN）。
    算法見模組說明。n_est_*＝窗口 n_est（窗口 ok=False 時 0）。
    share_basis.EventsUnavailable 不攔截，往上丟。"""
    excluded = sb.excluded_months(ticker)
    quarters = q.copy()
    quarters["period_end"] = pd.to_datetime(quarters["period_end"])
    quarters = quarters.sort_values("period_end", kind="stable").drop_duplicates("period_end", keep="last")
    exchange = {}
    if per is not None and not per.empty:
        selected = per[per["ticker"].astype(str).str.split(".").str[0] == str(ticker)]
        exchange = dict(zip(pd.to_datetime(selected["date"]), selected["per"]))
    result = []
    for r in closes.sort_values("month").itertuples(index=False):
        t = pd.Timestamp(r.date)
        price = r.close / sb.share_factor_after(ticker, t)
        ttm = ew.ttm_window(q, monthly_rev, asof=t, live=False, financial=financial)
        fwd = ew.fwd_window(q, monthly_rev, asof=t, base=ttm, live=False, financial=financial)
        eps_ttm = ttm.eps if ttm.ok else np.nan
        eps_fwd = fwd.eps if fwd.ok else np.nan
        visible = quarters[[ew.quarter_visible(d, t) for d in quarters["period_end"]]]
        bvps = np.nan
        equity_rows = visible[np.isfinite(visible["equity_parent"]) & (visible["equity_parent"] > 0)]
        if not equity_rows.empty:
            latest = equity_rows.iloc[-1]
            candidates = visible[visible["period_end"] <= latest["period_end"]].tail(5)   # 本季＋往前 4 季
            for v in candidates.iloc[::-1].itertuples(index=False):
                ni = v.ni_parent
                if np.isfinite(v.eps) and abs(v.eps) >= EPS_MIN and np.isfinite(ni):
                    shares = ni / v.eps
                    if _positive(shares):
                        bvps = latest["equity_parent"] / shares
                        break
        is_excluded = pd.Period(r.month, "M") in excluded
        mults = {}
        for name, denominator in (("pe", eps_ttm), ("pe_fwd", eps_fwd), ("pb", bvps)):
            valid = _positive(price) and _positive(denominator) and not is_excluded
            value = price / denominator if valid else np.nan
            valid = valid and _positive(value)
            if name != "pb":
                valid = valid and denominator >= EPS_MIN and value <= MULT_MAX_PE
            mults[name] = value if valid else np.nan
            mults["valid_" + name] = bool(valid)
        pe_exchange = exchange.get(t, np.nan)
        result.append(dict(ticker=ticker, month=r.month, date=t, price_adj=price,
                           eps_ttm=eps_ttm, eps_fwd=eps_fwd, bvps=bvps,
                           n_est_ttm=ttm.n_est if ttm.ok else 0,
                           n_est_fwd=fwd.n_est if fwd.ok else 0,
                           excluded=is_excluded,
                           pe_exchange=pe_exchange if _positive(pe_exchange) else np.nan, **mults))
    return pd.DataFrame(result, columns=HIST_COLUMNS)


def window_stats(mh: pd.DataFrame, kind: str, metric: str, asof: pd.Timestamp,
                 cap: float | None) -> dict:
    """倍數窗統計（T-4：窗口以估值日錨定）。kind ∈ WINDOW_MONTHS；metric ∈ {"pe","pe_fwd","pb"}。
    end＝last_complete_month(asof)；start＝end − (WINDOW_MONTHS[kind] − 1)，None → mh 最早月份。
    只看 start ≤ month ≤ end 的列；mh 沒有的月份就是沒有（不補列，不算有效）。
    n_valid＝valid_{metric} 為 True 的列數；n_loss＝窗內 eps 有限且 ≤0 的列數
    （pe／pb 看 eps_ttm，pe_fwd 看 eps_fwd）。
    raw_mults＝有效值的 PCTS 分位（pandas quantile 預設線性內插）；n_valid=0 → (None, None, None)。
    mults＝raw 各值 min(v, cap)（cap=None 不截）；capped＝cap 不是 None 且任一 raw > cap。
    回傳 {start:"YYYY-MM", end:"YYYY-MM", n_valid:int, n_loss:int, mults:tuple, raw_mults:tuple, capped:bool}。"""
    end = last_complete_month(asof)
    size = WINDOW_MONTHS[kind]
    if metric not in {"pe", "pe_fwd", "pb"}:
        raise KeyError(metric)
    start = str(end - (size - 1)) if size is not None else (str(mh["month"].min()) if not mh.empty else str(end))
    rows = mh[(mh["month"] >= start) & (mh["month"] <= str(end))]
    valid = rows["valid_" + metric].fillna(False).astype(bool)
    values = rows.loc[valid, metric]
    raw = tuple(float(v) for v in values.quantile(PCTS)) if len(values) else (None, None, None)
    eps = rows["eps_fwd" if metric == "pe_fwd" else "eps_ttm"]
    return dict(start=start, end=str(end), n_valid=int(valid.sum()),
                n_loss=int((np.isfinite(eps) & (eps <= 0)).sum()), raw_mults=raw,
                mults=tuple(min(v, cap) if cap is not None and v is not None else v for v in raw),
                capped=bool(cap is not None and any(v is not None and v > cap for v in raw)))


def is_valid_tier_a(n_valid: int, kind: str, was_a: bool) -> bool:
    """A 層門檻含緩衝：was_a 時 n_valid ≥ VALID_EXIT[k]，否則 ≥ VALID_MIN[k]。
    k＝kind；"cyclical" 視為 "normal"；其他不在 VALID_MIN 的 kind → KeyError。"""
    key = "normal" if kind == "cyclical" else kind
    return n_valid >= (VALID_EXIT if was_a else VALID_MIN)[key]


def revision_event(prev: dict | None, cur: dict) -> str:
    """eps_revision 的 event 欄。prev／cur＝{"window": "2026Q1-2026Q4", "actual_qs": tuple[str, ...]}。
    cur 或 prev 的 window 為 None（前瞻窗口不可用）→ "roll"；
    prev 為 None 或 window 不同 → "roll"；window 相同但 actual_qs 不同（試算季換成財報）→ "report"；
    其餘 → "normal"。"""
    if prev is None or cur["window"] is None or prev["window"] is None or cur["window"] != prev["window"]:
        return "roll"
    return "report" if cur["actual_qs"] != prev["actual_qs"] else "normal"


def hist_position(mh: pd.DataFrame | None, metric: str, asof: pd.Timestamp, months: int | None) -> dict | None:
    """P4（三軌體檢「本益比／股價淨值比歷史位置（自建）」）：取 month ≤ last_complete_month(asof) 且 valid_{metric}
    為 True 的列；months 不是 None → 只留 month ≥ last_complete_month(asof) − (months−1)（以月份算，不是列數）。
    沒有列 → None。回傳 {"now": 最後一列 metric 值, "pct": (值 ≤ now 的列數) ÷ 列數, "n": 列數, "month": 最後一列 month}。"""
    if mh is None or mh.empty:
        return None
    end = last_complete_month(asof)
    periods = pd.PeriodIndex(mh["month"], freq="M")
    mask = (periods <= end) & mh[f"valid_{metric}"].fillna(False).to_numpy(dtype=bool)
    if months is not None:
        mask &= periods >= end - (months - 1)
    rows = mh.loc[mask].sort_values("month")
    if rows.empty:
        return None
    now = float(rows.iloc[-1][metric])
    return dict(now=now, pct=float((rows[metric] <= now).mean()), n=len(rows), month=str(rows.iloc[-1]["month"]))


def revision_streak(rev_hist: pd.DataFrame) -> dict:
    """上修判斷（§5-4）。rev_hist＝該檔 eps_revision（欄 month, window, eps_fwd, event），依 month 舊→新處理。
    從第 2 列起逐列：
    - event 為 "roll"／"report" → 不比較，streak、direction 不變；
    - event "normal"：pct = 本列 eps_fwd ÷ 上一列 eps_fwd − 1（任一非有限或上一列 ≤0 → 視為持平）；
      pct ≥ REV_STEP → 上修；pct ≤ −REV_STEP → 下修；其餘持平。
      同方向 → streak+1；方向相反 → streak=1、direction 換邊；持平 → streak=0、direction=None。
    回傳 {"last_pct": 最後一列為 normal 時的 pct（持平因非有限者為 None），否則 None,
          "streak": int, "direction": "up"|"down"|None}。空表或只有 1 列 → {None, 0, None}。"""
    result = dict(last_pct=None, streak=0, direction=None)
    rows = rev_hist.sort_values("month")
    for i in range(1, len(rows)):
        cur, prev = rows.iloc[i], rows.iloc[i - 1]
        result["last_pct"] = None
        if cur["event"] in ("roll", "report"):
            continue
        a, b = cur["eps_fwd"], prev["eps_fwd"]
        pct = a / b - 1 if np.isfinite(a) and _positive(b) else None
        result["last_pct"] = pct
        direction = "up" if pct is not None and pct >= REV_STEP else ("down" if pct is not None and pct <= -REV_STEP else None)
        result["streak"] = (result["streak"] + 1 if direction == result["direction"] else 1) if direction else 0
        result["direction"] = direction
    return result


def _positive(value) -> bool:
    return value is not None and bool(np.isfinite(value) and value > 0)
