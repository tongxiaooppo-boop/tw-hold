"""估值失效偵測與可信度（草案 §6、§8.3 的精簡版；2026-11-01）。

每個檢查回 `Check(name, level, value, why)`：level ∈ ok／degrade／severe／block。
`confidence()` 彙總：任何 block → 不給價；severe（仍給價）→ 低；degrade 0 條＝高、1 條＝中、≥2 條＝低。
（val_card 不再用 block 擋價：它把 block 轉成 severe，見 val_card 檔頭。）
純函式，不讀檔。

已做（草案 11 項裡的 8 項）：股數對不上(2)、橋接殘差(3)、業外閘門(4)、稅/少數股權超界(5，由
eps_nowcast 的 flags 轉入)、月營收口徑(6)、近零 EPS(10)、倍數分布失效(11)、歷史不可比/循環涵蓋(8、9，
看分類結果)。
未做：單季化混入(1，loader 已保證)、估計器實績(7，要先累積 estimator_log)。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

SHARES_DEGRADE = 0.03
SHARES_BLOCK = 0.15
BRIDGE_DEGRADE = 0.10
BRIDGE_BLOCK = 0.25
NONOP_SHARE = 0.20           # 近 8 季業外占稅前
NONOP_DISPERSION = 0.5       # 業外 P90−P10 ÷ |稅前中位數|
REV_CALIBER_TOL = 0.05
NEAR_ZERO_REL = 0.2          # EPS_NC < 近 5 年 TTM EPS 中位數 × 0.2 視為近零
RATIO_DEGRADE = 2.5
RATIO_BLOCK = 4.0


@dataclass
class Check:
    name: str
    level: str            # ok／degrade／severe（仍給價、可信度低）／block
    value: float | None
    why: str


def _ok(name: str, value: float | None = None) -> Check:
    return Check(name, "ok", value, "")


def shares_check(q: pd.DataFrame) -> Check:
    """capital_stock÷10（期末股數）vs 近 4 季隱含股數（歸母淨利÷EPS 中位數，是加權平均）。"""
    n = "股數對不上"
    if "capital_stock" not in q.columns:
        return _ok(n)
    t = q.tail(4)
    ni = t["ni_parent"].fillna(t["net_income"]) if "ni_parent" in t.columns else t["net_income"]
    s = (ni / t["eps"])[(t["eps"].abs() >= 0.05)]
    s = s[s > 0]
    cap = q["capital_stock"].dropna()
    if s.empty or cap.empty or cap.iloc[-1] <= 0:
        return _ok(n)
    dev = abs(float(s.median()) / (float(cap.iloc[-1]) / 10) - 1)
    if dev > SHARES_BLOCK:
        # EPS 已被 loader 依分割／配股調整、股本是帳面值 → 差距大多是調整時點，不是資料壞；降級不擋
        return Check(n, "degrade", dev, f"隱含股數與股本差 {dev:.0%}（>15%，可能是分割／配股調整），股數用隱含值")
    if dev > SHARES_DEGRADE:
        return Check(n, "degrade", dev, f"隱含股數與股本差 {dev:.0%}（>3%），股數用隱含值")
    return _ok(n, dev)


def bridge_residual(q: pd.DataFrame, params: dict) -> Check:
    """用實際近 8 季營業利益＋業外中位數，走「稅/少數股權/股數」橋接，重算 EPS 對比實際。"""
    n = "橋接殘差"
    try:
        t, m, S, N = params["t"], params["m"], params["shares"], params["nonop_med"]
        if None in (t, m, S, N) or not S:
            return _ok(n)
        d = q.tail(8)
        hat = (d["op_income"] + N) * (1 - t) * (1 - m) / S
        err = float((hat - d["eps"]).abs().sum())
        base = float(d["eps"].abs().sum())
        if base <= 0 or np.isnan(err):
            return _ok(n)
        r = err / base
    except (KeyError, TypeError):
        return _ok(n)
    if r > BRIDGE_BLOCK:
        return Check(n, "block", r, f"用實際營業利益重算 EPS，近 8 季平均誤差 {r:.0%}（>25%）")
    if r > BRIDGE_DEGRADE:
        return Check(n, "degrade", r, f"用實際營業利益重算 EPS，近 8 季平均誤差 {r:.0%}（>10%）")
    return _ok(n, r)


def nonop_gate(q: pd.DataFrame) -> Check:
    """業外占比 ≥20% 且離散 ≥0.5 → block（不給 PE 類價格）；占比高但穩定 → degrade。"""
    n = "業外閘門"
    d = q.tail(8)
    nonop = (d["pretax_income"] - d["op_income"]).dropna()
    pre = d["pretax_income"].dropna()
    if len(nonop) < 4 or pre.abs().sum() == 0:
        return _ok(n)
    share = abs(float(nonop.sum())) / abs(float(pre.sum())) if float(pre.sum()) != 0 else 9.9
    med = abs(float(pre.median()))
    disp = float(nonop.quantile(0.9) - nonop.quantile(0.1)) / med if med > 0 else 9.9
    if share >= NONOP_SHARE and disp >= NONOP_DISPERSION:
        return Check(n, "block", share, f"近 8 季業外占稅前 {share:.0%} 且逐季差距大，EPS 試算不可靠")
    if share >= NONOP_SHARE:
        return Check(n, "degrade", share, f"近 8 季業外占稅前 {share:.0%}（穩定，可能是控股/權益法）")
    return _ok(n, share)


def revenue_caliber(q: pd.DataFrame, monthly: pd.Series) -> Check:
    """近 4 季「3 個月月營收合計 ÷ 季報營收」≥2 季偏離 >5% → 月營收與季報口徑不符。"""
    n = "月營收口徑"
    bad = tot = 0
    for r in q.tail(4).itertuples():
        end = pd.Timestamp(r.period_end)
        months = [(end.to_period("M") - i).to_timestamp() for i in range(3)]
        if all(m in monthly.index for m in months) and r.revenue:
            tot += 1
            ratio = float(sum(monthly[m] for m in months)) / float(r.revenue)
            bad += abs(ratio - 1) > REV_CALIBER_TOL
    if tot >= 3 and bad >= 2:
        return Check(n, "block", float(bad), f"近 4 季有 {bad} 季月營收合計與季報營收差 >5%，前瞻 4 季不可靠")
    return _ok(n, float(bad))


def near_zero_eps(eps_base: float | None, q: pd.DataFrame) -> Check:
    n = "近零EPS"
    if eps_base is None:
        return _ok(n)
    e = q["eps"].dropna()
    if len(e) < 20:
        return _ok(n)
    ttm = e.rolling(4).sum().dropna().tail(20)
    med = float(ttm.median())
    if med > 0 and eps_base < med * NEAR_ZERO_REL:
        return Check(n, "block", eps_base, f"前瞻 4 季 EPS {eps_base:.2f} 遠低於近 5 年中位 {med:.2f}，改用過去 4 季 EPS")
    return _ok(n, eps_base)


def dist_check(b: dict | None) -> Check:
    n = "倍數分布"
    if not b or not b.get("ok"):
        return Check(n, "block", None, (b or {}).get("reason") or "歷史倍數不足")
    r = b.get("ratio")
    if r and r > RATIO_BLOCK:
        return Check(n, "block", r, f"歷史倍數 P80÷P20＝{r:.1f}（>4），分布太寬")
    if r and r > RATIO_DEGRADE:
        return Check(n, "degrade", r, f"歷史倍數 P80÷P20＝{r:.1f}（>2.5）")
    return _ok(n, r)


def class_flags(cls: dict | None) -> list[Check]:
    """分類結果帶來的降級原因（循環/歷史可比性/剛切換）。"""
    out: list[Check] = []
    if not cls:
        return out
    sub = cls.get("subtags") or []
    for s, why in (("疑似循環", "疑似景氣循環股（輔助條件未過）"),
                   ("循環未觀察完整", "循環沒觀察完整"),
                   ("僅單一景氣事件", "循環只靠單一景氣事件成立")):
        if s in sub:
            out.append(Check(s, "degrade", None, why))
    m = cls.get("metrics") or {}
    if m.get("comparability_pending"):
        out.append(Check("歷史可比性", "degrade", None, "歷史可比性待確認（股本/營收斷點）"))
    if m.get("switched"):
        out.append(Check("剛切換類型", "degrade", None, "分類上季剛切換"))
    return out


def confidence(checks: list[Check]) -> dict:
    """彙總：{'level': '不給價'|'高'|'中'|'低', 'blocks': [...], 'degrades': [...]}（中文原因句）。"""
    blocks = [c.why for c in checks if c.level == "block"]
    deg = list(dict.fromkeys(c.why for c in checks if c.level in ("degrade", "severe") and c.why))
    if blocks:
        lv = "不給價"
    elif any(c.level == "severe" for c in checks):      # 嚴重（試算不可靠改用實際 EPS／倍數補位）：可信度上限為低，不看條數
        lv = "低"
    elif not deg:
        lv = "高"
    elif len(deg) == 1:
        lv = "中"
    else:
        lv = "低"
    return {"level": lv, "blocks": blocks, "degrades": deg}


PB_EVENT_BLOCK = 0.10       # 股數事件 |m−1| ≥10% → PB 分布被汙染，不給價
PB_EVENT_DEGRADE = 0.03


def pb_events(per: pd.DataFrame, events: list[tuple[pd.Timestamp, float]] | None) -> Check:
    """交易所 PER 已由 fix_exchange_ratios 修回同一把尺，但 **PBR 沒人修**（交接 A8：6669 在 2026-09-02
    由 8.8 掉到 3.5）。倍數窗內有股數事件（分割／配股／減資，events＝[(日期, m)]）→ PB 分布被汙染：
    |m−1| ≥10% → block；3～10% → degrade。events 為 None＝不知道（呼叫端沒給）→ 視為 ok 並無從把關。"""
    n = "PB股數事件"
    if events is None:
        return Check(n, "degrade", None, "未取得股數事件資料，PB 歷史分布是否被股數調整汙染無從確認")
    if not events or per is None or per.empty:
        return _ok(n)
    d0, d1 = pd.to_datetime(per["date"]).min(), pd.to_datetime(per["date"]).max()
    hit = [(pd.Timestamp(t), float(m)) for t, m in events if d0 <= pd.Timestamp(t) <= d1 and m]
    if not hit:
        return _ok(n)
    t, m = max(hit, key=lambda x: abs(x[1] - 1))
    dev = round(abs(m - 1), 9)      # 0.9 → 0.09999999999999998 會漏過 ≥10% 的門檻
    msg = f"{t:%Y-%m-%d} 有股數調整事件（股數 ×{m:.2f}），交易所股價淨值比未修正，PB 歷史分布被汙染"
    if dev >= PB_EVENT_BLOCK:
        return Check(n, "block", dev, msg + "，PB 不給價")
    if dev >= PB_EVENT_DEGRADE:
        return Check(n, "degrade", dev, msg + "（影響小）")
    return _ok(n, dev)
