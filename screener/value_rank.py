"""合理價以下排行：分組與排名的純函式（不做 IO）。任務書 2026-11-19 v1。"""
from __future__ import annotations

import math

import pandas as pd

GROWTH_REV = 0.30      # 近 4 季營收 ÷ 前 4 季營收 − 1 ≥ 30% → 高成長
SPIKE_EPS = 2.0        # 近 4 季 EPS ÷ 前 3 年平均年 EPS > 2 → EPS 暴增
TOP_N = 20
DECEL_PTS = 0.20   # 高成長組：近12月年增 − 近3月年增 ≥ 20 個百分點 → 降溫
GROUPS = ("一般", "循環", "高成長")


def _finite(v) -> bool:
    try:
        return v is not None and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def eps_ratio(q: pd.DataFrame) -> float | None:
    """近 4 季 EPS 合計 ÷ 前 3 年（各 4 季）平均年 EPS；不足 16 季或平均 ≤ 0 → None。"""
    if q is None or len(q) == 0 or "eps" not in q.columns:
        return None
    d = q.sort_values("period_end")
    eps = [float(x) for x in d["eps"] if _finite(x)]
    if len(eps) < 16:
        return None
    ttm = sum(eps[-4:])
    years = [sum(eps[-8:-4]), sum(eps[-12:-8]), sum(eps[-16:-12])]
    avg = sum(years) / 3
    if avg <= 0:
        return None
    return ttm / avg


def revenue_growth(q: pd.DataFrame) -> float | None:
    """最後 4 季營收合計 ÷ 前 4 季合計 − 1；資料不足、有缺值或分母 ≤ 0 → None。"""
    if q is None or len(q) == 0 or "revenue" not in q.columns:
        return None
    d = q.sort_values("period_end").tail(8)
    if len(d) < 8:
        return None
    vals = list(d["revenue"])
    if not all(_finite(v) for v in vals):
        return None
    vals = [float(v) for v in vals]
    prev, last = sum(vals[:4]), sum(vals[4:])
    if prev <= 0:
        return None
    return last / prev - 1


def category(typ: str | None, eps_x: float | None, rev_g: float | None) -> tuple[str, str]:
    """回傳 (組別, 原因短句)。"""
    grow = rev_g is not None and rev_g >= GROWTH_REV and typ != "cyclical"
    if grow:
        return "高成長", f"近4季營收年增 {rev_g:.0%}"
    if typ == "cyclical":
        return "循環", "分類為景氣循環"
    if eps_x is not None and eps_x > SPIKE_EPS:
        return "循環", f"EPS 為前3年平均 {eps_x:.1f} 倍、營收沒同步暴增，可能是循環高峰或一次性收益"
    return "一般", ""


def rank(rows: list[dict]) -> dict[str, list[dict]]:
    """只留股價 ≤ 合理價；gap＝price/fair−1 由小到大取前 TOP_N；三組都在。"""
    out: dict[str, list[dict]] = {g: [] for g in GROUPS}
    for r in rows:
        p, f = r.get("price"), r.get("fair")
        if not (_finite(p) and _finite(f)) or float(f) <= 0 or float(p) > float(f):
            continue
        r["gap"] = float(p) / float(f) - 1
        out.setdefault(r.get("group"), []).append(r)
    for g in out:
        out[g] = sorted(out[g], key=lambda r: (r["gap"], str(r.get("ticker"))))[:TOP_N]
    return out


def rev_yoy(m: pd.DataFrame) -> tuple[float | None, float | None, str | None]:
    """月營收長表（month 'YYYY-MM'、revenue）→ (近3月年增, 近12月年增, 最新月)；缺月或分母 ≤ 0 → 該值 None。"""
    if m is None or len(m) == 0 or "month" not in m.columns or "revenue" not in m.columns:
        return None, None, None
    by: dict[pd.Period, float] = {}
    for mo, rv in zip(m["month"], m["revenue"]):
        if not _finite(rv):
            continue
        try:
            by[pd.Period(str(mo), "M")] = float(rv)
        except Exception:  # noqa: BLE001
            continue
    if not by:
        return None, None, None
    last = max(by)

    def _yoy(n: int) -> float | None:
        cur = [last - i for i in range(n)]
        prev = [p - 12 for p in cur]
        if not all(p in by for p in cur + prev):
            return None
        d = sum(by[p] for p in prev)
        if d <= 0:
            return None
        return sum(by[p] for p in cur) / d - 1

    return _yoy(3), _yoy(12), str(last)


def rev_flag(group: str, y3: float | None, y12: float | None) -> str:
    """月營收警示文字；無警示 → ""。只提醒、不影響排名。"""
    if y3 is None:
        return ""
    if y3 < 0:
        x = "不到 1%" if abs(y3) * 100 < 0.5 else f" {abs(y3) * 100:.0f}%"
        return f"近三月營收比去年少{x}，過去獲利可能撐不住"
    if group == "高成長" and y12 is not None and y12 - y3 >= DECEL_PTS - 1e-9:
        return f"營收仍在增加，但成長放慢（近12月年增 {y12:.0%} → 近三月 {y3:.0%}），合理價要再確認"
    return ""


REC_MIN_HIST = 36      # 創新高至少要有這麼多個月的更早歷史，否則不稱創新高


def rev_month_info(m: pd.DataFrame, month: str | None) -> dict:
    """月營收長表（欄 month、revenue）＋最新月 'YYYY-MM' → 單月年增、連續年增月數、創新高、低基期。
    month 為 None 或表空 → 全預設值。rev_record 另需目標月之前至少 REC_MIN_HIST 個月資料。"""
    from screener import revenue_watch as rw
    empty = {"rev_m_yoy": None, "rev_streak": 0, "rev_record": False, "rev_low_base": False}
    if (month is None or m is None or len(m) == 0
            or "month" not in m.columns or "revenue" not in m.columns):
        return dict(empty)
    try:
        period = pd.Period(str(month), "M")
    except Exception:  # noqa: BLE001
        return dict(empty)
    h = m[["month", "revenue"]].copy()
    h["revenue"] = pd.to_numeric(h["revenue"], errors="coerce")
    h["month"] = h["month"].map(lambda x: _to_month_ts(x))
    h = h.dropna(subset=["month", "revenue"])
    h = h[h["revenue"].map(_finite)]
    if h.empty:
        return dict(empty)
    h = h.drop_duplicates(subset="month", keep="last").reset_index(drop=True)
    by = {pd.Period(ts, freq="M"): float(v) for ts, v in zip(h["month"], h["revenue"])}
    cur, prev = by.get(period), by.get(period - 12)
    yoy = low = None
    low = False
    if cur is not None and prev is not None and prev > 0:
        yoy = cur / prev - 1
        low = prev < rw.LOW_BASE_REV
    streak = rw.yoy_streak(h, period)
    earlier = int((h["month"] < period.to_timestamp()).sum())
    record = bool(earlier >= REC_MIN_HIST and rw.record_high(h, period))
    return {"rev_m_yoy": yoy, "rev_streak": streak, "rev_record": record, "rev_low_base": bool(low)}


def _to_month_ts(x):
    try:
        return pd.Period(pd.Timestamp(x) if not isinstance(x, str) else x, "M").to_timestamp()
    except Exception:  # noqa: BLE001
        return pd.NaT


def rev_progress(rows: list[dict], asof: str) -> dict:
    """目標月＝asof 所在月的上一個月；published＝rev_month 等於目標月的列數，total＝rows 數。"""
    month = str(pd.Period(pd.Timestamp(asof), "M") - 1)
    pub = sum(1 for r in rows if r.get("rev_month") == month)
    return {"month": month, "published": pub, "total": len(rows)}


def _pct(v: float) -> str:
    return "±0%" if abs(v) < 0.005 else f"{v * 100:+.0f}%"


def rev_text(r: dict) -> str:
    """排行表「月營收（年增）」欄文字。"""
    rm = r.get("rev_month")
    if not rm:
        return "—"
    s = f"{int(str(rm)[5:7])}月 "
    if r.get("rev_low_base"):
        s += "低基期"
    elif r.get("rev_m_yoy") is None:
        s += "—"
    else:
        s += _pct(r["rev_m_yoy"])
    if r.get("rev3m_yoy") is not None:
        s += "｜近3月 " + _pct(r["rev3m_yoy"])
    tags = []
    if r.get("rev_record"):
        tags.append("創新高")
    if (r.get("rev_streak") or 0) >= 3:
        tags.append(f"連 {r['rev_streak']} 月成長")
    if tags:
        s += "・" + "・".join(tags)
    return s


# ── 月營收成長排行（2026-11-20 決策；任務書 collab/to-sonnet-growth-rank.md）──────────
# 只排目標月（asof 上一個月）已公布者，沒公布的天然不在榜、公布後下次重算補回。
# MoM 不刪人，只標記（研究：research/rev_growth_rank_2026-11/，被刪者下月 YoY 跟留下的差不到 2 個百分點）。
MOM_WARN = -0.03            # 單月 MoM < −3% → 標「月減」；農曆新年窗碰到的月份不標
GROWTH_TOP_N = 30
GROWTH_PROVISIONAL = 0.90   # 已公布 < 90% 母體 → 暫排
EXCLUDE_INDUSTRY = ("建材營造",)


def rev_mom(m: pd.DataFrame, month: str | None) -> float | None:
    """月營收長表（欄 month、revenue；month 可為 'YYYY-MM' 字串或 Timestamp）＋目標月 'YYYY-MM'
    → 目標月 ÷ 上月 − 1。目標月或上月缺、上月 ≤ 0、month None、表空 → None。"""
    raise NotImplementedError


def mom_warn(mom: float | None, month: str | None) -> bool:
    """mom < MOM_WARN 且 month 不碰農曆新年窗（screener.lny.month_touches_lny）→ True；mom 或 month None → False。"""
    raise NotImplementedError


def growth_rank(rows: list[dict], month: str) -> dict:
    """月營收成長排行。rows＝build_value_rank 的列（需 rev_month、rev_m_yoy、rev_low_base、industry、ticker）。
    回傳 {"month", "published", "total", "provisional", "excluded_construction", "top_n", "rows"}：
      published＝rev_month == month 的列數；total＝len(rows)；provisional＝published < GROWTH_PROVISIONAL × total
      excluded_construction＝已公布列中 industry ∈ EXCLUDE_INDUSTRY 的列數
      rows＝已公布、rev_m_yoy 非 None 且 > 0、rev_low_base 為假、industry ∉ EXCLUDE_INDUSTRY，
            依 rev_m_yoy 由大到小（同值依 ticker 由小到大），取前 GROWTH_TOP_N；每列是原 dict 的淺複製並加 "rank"（1 起）。
    不改動傳入的 rows。"""
    raise NotImplementedError
