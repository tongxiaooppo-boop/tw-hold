"""年增率共用模組（估值 2.0，upgrade_guide §6）。

全站「季 EPS 年增」「最新月營收年增」「近 4 季 EPS 年增」等一律呼叫這裡，名稱與例外詞固定：
去年 ≤0 → 虧轉盈、今年 <0 → 轉虧、兩期都虧 → 虧損擴大／縮小（不給百分比，避免 −2→−4 算成 +100%）。
基期低：EPS 去年絕對值 <1 元或不到今年 1/5；營收去年不到今年 1/5。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

LOW_BASE_ABS = 1.0     # EPS 基期低：去年同期絕對值 < 1 元（定案）
LOW_BASE_REL = 0.2     # 基期低：去年同期 < 今年 × 0.2（定案）

TEXT = {
    "turn_profit": "虧轉盈",
    "turn_loss": "轉虧",
    "loss_wider": "虧損擴大",
    "loss_narrower": "虧損縮小",
    "base_zero": "去年同期為 0",
    "flat": "今年為 0",
    "na": "—",
}


@dataclass(frozen=True)
class Growth:
    value: float | None    # 比例（0.35＝+35%）；label 不是 "pct" 時一律 None
    label: str             # "pct" | "turn_profit" | "turn_loss" | "loss_wider" | "loss_narrower" | "base_zero" | "flat" | "na"
    low_base: bool
    text: str              # 畫面用短字，如 "+35%（基期低）"、"虧轉盈"

    def passes(self, threshold: float) -> bool:
        """門檻判斷（推薦卡用）：只有 label=="pct" 且 value > threshold 才算過；例外詞一律不過。"""
        return self.label == "pct" and self.value is not None and self.value > threshold


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _make(label: str, value: float | None = None, low_base: bool = False) -> Growth:
    if label == "pct":
        text = f"{value:+.0%}" + ("（基期低）" if low_base else "")
    else:
        text = TEXT[label]
    return Growth(value=value if label == "pct" else None, label=label, low_base=low_base, text=text)


def yoy_eps(cur, prev) -> Growth:
    """EPS（或任何可正可負的獲利）年增。cur／prev 缺值或非有限 → na。"""
    c, p = _num(cur), _num(prev)
    if c is None or p is None:
        return _make("na")
    if p == 0:
        return _make("base_zero")
    if c == 0:
        return _make("flat")
    if p > 0 and c > 0:
        low = abs(p) < LOW_BASE_ABS or p < c * LOW_BASE_REL
        return _make("pct", c / p - 1.0, low)
    if p < 0 < c:
        return _make("turn_profit")
    if p > 0 > c:
        return _make("turn_loss")
    return _make("loss_wider" if abs(c) > abs(p) else "loss_narrower")


def yoy_revenue(cur, prev) -> Growth:
    """營收年增。營收 ≤0 視為不可用（T-20）→ na。"""
    c, p = _num(cur), _num(prev)
    if c is None or p is None or c <= 0 or p <= 0:
        return _make("na")
    return _make("pct", c / p - 1.0, p < c * LOW_BASE_REL)


def accel(cur: Growth, prev: Growth) -> bool | None:
    """營收加速／減速：本月年增 vs 上月年增，兩者都是 pct 才比；否則 None（未知）。"""
    if cur.label != "pct" or prev.label != "pct":
        return None
    return cur.value > prev.value
