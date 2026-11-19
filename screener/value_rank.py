"""合理價以下排行：分組與排名的純函式（不做 IO）。任務書 2026-11-19 v1。"""
from __future__ import annotations

import math

import pandas as pd

GROWTH_REV = 0.30      # 近 4 季營收 ÷ 前 4 季營收 − 1 ≥ 30% → 高成長
SPIKE_EPS = 2.0        # 近 4 季 EPS ÷ 前 3 年平均年 EPS > 2 → EPS 暴增
TOP_N = 20
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
