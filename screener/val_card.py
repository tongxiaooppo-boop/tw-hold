"""估值卡片資料（估值改版 A13，2026-11-01）：分類 → 前瞻 EPS → 月底倍數三價 → 12 個月基準情境價 → 可信度。

純函式，不讀檔：app 把個股的季報 `qf`、月營收 `rev`、股價 `px`、倍數 `per` 與
`data/derived/stock_class.json` 裡該檔的分類 dict `cls` 傳進來。定義見 `D:/g/claude/估值定義定案草案.md`
§3～§6；三價規則（使用者 2026-11-01 定案，取代 v1 的「閘門擋價」）：
- **賠錢（近四季 EPS ≤ 0）不給三價**；其餘一律給。
- 自身歷史 P20/P50/P80 有效就用自己的：一般／高成長／循環・資產輕＝PE × EPS；金融、循環・資產重＝PB × 每股淨值。
- 自身歷史無效（月數不足、分布 P80÷P20>4、倍數上限使三價相同、PB 窗內有大型股數事件、每股淨值缺）
  → 以 `FALLBACK_MULTS` 類型參考倍數 × EPS 補位；特殊、資料不足一律補位。補位＝可信度低、不給滾動獲利估值價與購買參考價。
- 風險閘門只決定 EPS 取哪個、要不要降級：試算閘門（橋接殘差／業外／月營收口徑／近零 EPS）擋下 → 過去 4 季 EPS、
  可信度低；歷史高獲利區＋循環跡象、或循環類 → 近四季與 3 年平均取低者。獲利狀態（不穩／轉機…）只降級。
- 滾動獲利估值價（前瞻 4 季 EPS × P50）與購買參考價：維持舊行為，只在前瞻 EPS 可用、自身歷史有效時給（滾動獲利估值價 EPS 之後依 H22 結果再定）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from screener import detect as dt
from screener import eps_nowcast as en
from screener import multiples as mu

CARD_VERSION = "card-v2-2026-11-01"
PE_NORMAL = dict(years=5, min_months=48, cap=30.0)
PE_NORMAL_EXC = dict(years=5, min_months=48, cap=50.0)      # 5 年每年獲利且年均 PE 都 >30
PE_GROWTH = dict(years=3, min_months=30, cap=50.0)
PB_ALL = dict(years=None, min_months=60, cap=None)
GATE_NAMES = ("橋接殘差", "業外閘門", "月營收口徑", "近零EPS")     # 前瞻 EPS 試算閘門（block＝改用過去 4 季 EPS）
STATES_NO_PE = ("虧損", "獲利不穩", "轉機", "預估轉虧", "谷底回升")
# 補位倍數（便宜／合理／昂貴；2026-11-01 使用者定案，推導與口徑見 HANDOFF A15、research/valuation_v2_experiment/）：
# 一般、高成長＝同類「有自身歷史倍數者」的三價倍數中位數（207／22 檔）；循環＝2021–2025 年底橫斷面 PE 收縮；
# 金融、特殊、資料不足＝2021–2025 年底橫斷面錨（口徑不同於前兩者，不往全體收縮）。
FALLBACK_MULTS = {"normal": (12.8, 16.5, 21.1), "growth": (17.2, 19.2, 26.2), "cyclical": (13.6, 17.6, 22.7),
                  "financial": (9.9, 11.8, 14.0), "special": (8.8, 11.5, 15.2), "insufficient": (13.1, 15.9, 19.4)}
BVPS_MAX_AGE_DAYS = 31
PER_STALE_DAYS = 10         # 反推 EPS 用的交易所本益比，最新一筆不得落後最新收盤日超過這麼多天
REF_MARGIN = 0.10          # 購買參考價：滾動獲利估值價須比現價高 ≥10%（使用者 2026-11-01 指定）
DIFF_WARN = 0.30            # 滾動與已公布獲利估值價差 >30% → 獲利口徑差異大（對照三價警示、gap_big 共用同一門檻）
Q_COLS = ["revenue", "gross_profit", "op_income", "pretax_income", "net_income", "ni_parent", "eps",
          "capital_stock", "equity_parent"]


def _q(qf: pd.DataFrame) -> pd.DataFrame:
    if qf is None or qf.empty:
        return pd.DataFrame(columns=["period_end"] + Q_COLS)
    d = qf.copy()
    d["period_end"] = pd.to_datetime(d["period_end"])
    for c in Q_COLS:
        d[c] = pd.to_numeric(d[c], errors="coerce") if c in d.columns else np.nan
    return (d[["period_end"] + Q_COLS].drop_duplicates("period_end", keep="last")
            .sort_values("period_end").reset_index(drop=True))


def _monthly(rev: pd.DataFrame) -> pd.Series:
    if rev is None or rev.empty:
        return pd.Series(dtype=float)
    m = pd.to_datetime(rev["month"]).dt.to_period("M").dt.to_timestamp()
    s = pd.Series(pd.to_numeric(rev["revenue"], errors="coerce").to_numpy(), index=m)
    return s[~s.index.duplicated(keep="last")].sort_index()


def _yearly_eps(q: pd.DataFrame) -> dict[int, float]:
    out = {}
    for y, g in q.groupby(q["period_end"].dt.year):
        if len(g) == 4 and g["eps"].notna().all():
            out[int(y)] = float(g["eps"].sum())
    return out


def _last_px(px: pd.DataFrame):
    if px is None or px.empty:
        return None, None
    r = px.sort_values("date").iloc[-1]
    c = pd.to_numeric(r["close"], errors="coerce")
    return (None if pd.isna(c) else float(c)), pd.Timestamp(r["date"])


def _bvps(per: pd.DataFrame, px: pd.DataFrame) -> float | None:
    """每股淨值 ＝ 收盤價 ÷ 交易所股價淨值比（同一天），與倍數序列同口徑。合併日期距股價最後一天不得超過 31 天。"""
    if per is None or per.empty or px is None or px.empty:
        return None
    p = per[["date", "pbr"]].copy()
    p["date"] = pd.to_datetime(p["date"])
    p = p[pd.to_numeric(p["pbr"], errors="coerce") > 0].sort_values("date")
    c = px[["date", "close"]].copy()
    c["date"] = pd.to_datetime(c["date"])
    j = p.merge(c.dropna(), on="date").tail(1)
    if j.empty or j["date"].iloc[0] < c["date"].max() - pd.Timedelta(days=BVPS_MAX_AGE_DAYS):
        return None
    return float(j["close"].iloc[0]) / float(j["pbr"].iloc[0])


def _peak_block(cls: dict) -> str | None:
    st, sub, m = cls.get("state") or [], cls.get("subtags") or [], cls.get("metrics") or {}
    if "歷史高獲利區" not in st:
        return None
    dd = m.get("max_dd")
    if "疑似循環" in sub or "僅單一景氣事件" in sub or (isinstance(dd, (int, float)) and dd >= 0.5):
        return "目前處於自身歷史高獲利區，且有景氣循環跡象：用高峰 EPS 乘歷史倍數會高估，EPS 改取近四季與 3 年平均較低者"
    return None


def _check_pack(checks: list[dt.Check]) -> list[dict]:
    return [{"name": c.name, "level": c.level, "why": c.why, "value": c.value} for c in checks if c.level != "ok"]


def build_card(qf: pd.DataFrame, rev: pd.DataFrame, px: pd.DataFrame, per: pd.DataFrame,
               cls: dict | None, share_events: list | None = None) -> dict:
    """share_events＝[(日期, m)]（reference.corporate_actions._events），PB 守門用。回傳 dict；ok=False 只在完全無法處理（無分類、無財報）。價格不給時 prices=None，並附 no_price 原因。"""
    out: dict = {"ok": False, "reason": None, "version": CARD_VERSION}
    if not cls:
        out["reason"] = "這檔不在分類母體（上市櫃且財報 ≥12 季），不做估值。"
        return out
    q = _q(qf)
    price, px_date = _last_px(px)
    typ = cls.get("type")
    states = list(cls.get("state") or [])
    subtags = list(cls.get("subtags") or [])
    out.update(ok=True, type=typ, display_type=cls.get("display_type"), state=states, subtags=subtags,
               why=list(cls.get("why") or []), price=price,
               px_date=px_date.strftime("%Y/%m/%d") if px_date is not None else None,
               class_asof=cls.get("decided_at"), prices=None, forward=None, position=None, eps=None,
               band=None, method=None, no_price=None, compare=None, notes=[], truncated=False)
    checks: list[dt.Check] = dt.class_flags(cls)
    from reference import corporate_actions as ca
    if not ca.EVENTS_OK:
        checks.append(dt.Check("股數事件表", "block", None,
                               "股數事件表讀取失敗，股數還原可能失效"))
    if len(q) < 4:
        out["no_price"] = "財報不足 4 季"
        return out
    monthly = _monthly(rev)
    # 分類是 build_classification 的快照；財報進來後分類沒重跑 → 狀態（虧損／獲利不穩）可能過期（Opus #6）
    try:
        ca, qmax = pd.Timestamp(cls.get("decided_at")), q["period_end"].max()
        if ca < qmax:
            checks.append(dt.Check("分類過期", "degrade", None,
                                   f"分類基準 {ca:%Y-%m-%d} 落後最新財報 {qmax:%Y-%m-%d}，狀態（虧損／獲利不穩）可能過期"))
    except (TypeError, ValueError):
        pass

    # ── 前瞻 EPS（非金融才有毛利欄可試算）──
    nc = None
    if typ != "financial" and monthly.notna().any():
        nc = en.nowcast(q, monthly, g_far_zero=(typ == "cyclical"))
        out["eps"] = nc
        if (nc.get("variability") or {}).get("flag"):
            checks.append(dt.Check("高變動", "severe", None,
                                   "最新一季偏離過去水準（" + "、".join(nc["variability"]["reasons"]) + "），預測季延續該季"))
        if not nc.get("ok"):
            checks.append(dt.Check("前瞻EPS不可用", "degrade", None, "前瞻 4 季無法試算：" + (nc.get("reason") or "原因不明")))
        if nc.get("ok"):
            hist = pd.to_numeric(q.sort_values("period_end")["eps"], errors="coerce").dropna().tail(8)
            trial = [d["eps"] for d in nc.get("nc_quarters") or [] if d.get("kind") in ("est", "copy")]
            if len(hist) >= 4 and trial and max(trial) > 2 * max(hist.max(), 0.05):
                out["notes"].append("試算單季 EPS 超過近 8 季最高 2 倍，營收暴增未必全轉成獲利。")
            for f in nc.get("flags") or []:
                checks.append(dt.Check(f, "degrade", None, f))
            checks += [dt.shares_check(q), dt.bridge_residual(q, nc.get("params") or {}),
                       dt.nonop_gate(q), dt.revenue_caliber(q, monthly)]
    # 財報矛盾跟月營收、試算成不成功無關（試算不出來的反而最該看）；金融業沒有毛利、營收口徑不同，不查
    if typ != "financial":
        checks.append(dt.quarter_sanity(q, construction=("construction" in
                      ((cls.get("metrics") or {}).get("special_triggers") or []))))

    # ── 路由 ──
    if typ not in ("insufficient", "special", "financial", "cyclical", "normal", "growth"):
        out["no_price"] = f"未知分類「{typ}」，不給價"
        return _finish(out, checks)
    # 賠錢（近四季 EPS ≤ 0）不給三價（使用者 2026-11-01）；其餘風險閘門只換 EPS 基準或降級，不擋價
    ttm, avg3 = _ttm_eps(q), _avg3_eps(q)
    is_pb = typ == "financial" or (typ == "cyclical" and "資產重" in subtags)      # PB 路線不需要 EPS
    if ttm is None:      # 最新季 EPS 缺值（金融股常見）→ 用收盤價 ÷ 交易所本益比反推近四季 EPS（同交易所口徑）
        ttm = _ttm_from_per(per, px)
        if ttm is not None:
            checks.append(dt.Check("EPS反推", "degrade", None, "近四季 EPS 缺值，改用收盤價 ÷ 交易所本益比反推"))
    if (ttm is None and not is_pb) or (ttm is not None and ttm <= 0):
        out["no_price"] = ("過去 4 季 EPS 缺值，且無法用本益比反推（本益比空白或資料過舊），不給三價" if ttm is None
                           else f"過去 4 季 EPS {ttm:.2f} ≤ 0（賠錢不給三價）")
        return _finish(out, checks)
    hit = [s for s in states if s in STATES_NO_PE]
    if hit:
        checks.append(dt.Check("獲利狀態", "degrade", None, f"目前狀態「{'、'.join(hit)}」：獲利不穩，估值參考性較低"))
    if typ in ("insufficient", "special"):
        why = {"insufficient": "財報不足 12 季，沒有自身歷史倍數",
               "special": "特殊類型（生技／建材營造／併購重組等），歷史倍數不可比"}[typ]
        _fallback(out, typ, ttm, "過去 4 季 EPS", price, why, checks)
        return _finish(out, checks)
    peak = _peak_block(cls)
    if peak:
        checks.append(dt.Check("高獲利區", "degrade", None, peak))
    eps, eps_name, use_nc = _eps_base(typ, nc, q, ttm, avg3, peak is not None, checks)

    if is_pb:
        b = mu.band(per, "pbr", **PB_ALL)
        out["band"] = b
        bv = _bvps(per, px)
        dc, ev = dt.dist_check(b), dt.pb_events(per, share_events)
        if bv and dc.level != "block" and ev.level != "block":
            out["method"] = "PB"
            checks += [dc, ev]
            p = mu.prices(bv, b)
            out["prices"] = {**p, "base": bv, "base_name": "每股淨值", "source": "歷史"}
            out["position"] = mu.classify_position(price, p) if price else "na"
            out["notes"].append("PB 三價＝歷史月底股價淨值比分位 × 最新每股淨值；不給估值價與購買參考價（循環・金融第一版）。")
            if typ == "financial":
                out["notes"].append("金融股 2026 起 IFRS 17 淨值有斷點，跨年 PB 不完全可比。")
        else:
            why = ("每股淨值不可得" if not bv else
                   ev.why if ev.level == "block" else dc.why)
            if eps is None:          # 沒有 EPS 可補位（金融股最新季 EPS 缺值）
                out["no_price"] = "PB 自身歷史不可用（" + why.replace("，PB 不給價", "") + "），且無 EPS 可補位"
                return _finish(out, checks)
            _fallback(out, typ, eps, eps_name, price, "PB 自身歷史不可用（" + why.replace("，PB 不給價", "") + "）", checks)
        return _finish(out, checks)

    # ── PE 路線（一般／高成長／循環・資產輕）──
    out["method"] = "PE"
    spec = PE_GROWTH if typ == "growth" else PE_NORMAL
    if typ == "normal" and mu.high_pe_exception(per, _yearly_eps(q)):
        spec = PE_NORMAL_EXC
        out["notes"].append("近 5 年每年獲利且年均 PE 都 >30：倍數上限放寬到 50。")
    b = mu.band(per, "per", **spec)
    out["band"] = b
    dc = dt.dist_check(b)
    flat = bool(b.get("ok") and b.get("cap") and b["raw"]["p20"] >= b["cap"])
    if dc.level == "block" or flat:
        why = (f"歷史月底本益比 P20 已 ≥ 上限 {b['cap']:.0f}，截斷後三價相同" if flat else dc.why)
        _fallback(out, typ, eps, eps_name, price, "PE 自身歷史不可用（" + why + "）", checks)
        return _finish(out, checks)
    checks.append(dc)
    p = mu.prices(eps, b)
    out["prices"] = {**p, "base": eps, "base_name": eps_name, "source": "歷史"}
    out["position"] = mu.classify_position(price, p) if price else "na"
    out["truncated"] = bool(b.get("truncated"))
    if b.get("truncated"):
        r, c = b["raw"], b["capped"]
        out["notes"].append(f"倍數上限 {b['cap']:.0f} 倍：歷史原始倍數 {r['p20']:.1f}／{r['p50']:.1f}／{r['p80']:.1f}，"
                            f"截斷後 {c['p20']:.1f}／{c['p50']:.1f}／{c['p80']:.1f}。")
        checks.append(dt.Check("倍數截斷", "degrade", None, "倍數被上限截斷"))
    if not use_nc or hit:
        return _finish(out, checks)      # EPS 基準不是前瞻 EPS（閘門／高獲利區／循環）或獲利狀態不穩：不給對照價與 12 個月價（維持舊行為）
    # 對照：用過去 4 季
    ttm_nc = nc.get("eps_ttm")
    if ttm_nc and ttm_nc > 0 and not nc.get("fallback"):
        pt = mu.prices(ttm_nc, b)
        if pt:
            diff = p["fair"] / pt["fair"] - 1
            out["compare"] = {"eps_ttm": ttm_nc, "cheap": pt["cheap"], "fair": pt["fair"], "dear": pt["dear"],
                              "diff": diff, "warn": abs(diff) > DIFF_WARN}
    c = b["capped"]
    def valuation(value):
        if value is None or value <= 0:
            return None
        return dict(eps=value, lo=value * c["p20"], base=value * c["p50"], hi=value * c["p80"])
    fallback = en.FALLBACK_FLAG in (nc.get("flags") or []) or nc.get("eps_nc") is None
    rolling = None if fallback else valuation(nc["eps_nc"])
    reported = valuation(nc.get("eps_ttm"))
    gap = rolling["base"] / reported["base"] - 1 if rolling and reported else None
    gap_big = gap is not None and abs(gap) > DIFF_WARN
    ref_ok = bool(rolling and not gap_big and price and rolling["base"] >= price * (1 + REF_MARGIN))
    out["forward"] = dict(rolling=rolling, reported=reported, gap=gap, gap_big=gap_big,
                          ref_ok=ref_ok,
                          ref_price=rolling["base"] / (1 + REF_MARGIN) if ref_ok else None,
                          margin=rolling["base"] / price - 1 if ref_ok else None,
                          implied_pe=price / rolling["eps"] if rolling and price else None,
                          mult_p50=c["p50"])
    if gap_big:
        out["position"] = "na"           # 兩個口徑差太多：不判便宜／昂貴（與「不給上漲空間」一致）
        out["notes"].append("獲利口徑差異大")
    return _finish(out, checks)


def _ttm_eps(q: pd.DataFrame) -> float | None:
    from screener import quarterly_prep as qp

    e = qp.last_n_quarters(q.set_index("period_end")["eps"], 4)
    return float(e.sum()) if e is not None else None


def _ttm_from_per(per: pd.DataFrame, px: pd.DataFrame) -> float | None:
    """近四季 EPS ＝ 收盤價 ÷ 交易所本益比（同一天，取最新一個同時有 PER 與收盤價的日子；該日 PER 空白或落後太久 → None）。"""
    if per is None or per.empty or px is None or px.empty:
        return None
    p = per[["date", "per"]].copy()
    p["date"] = pd.to_datetime(p["date"])
    p["per"] = pd.to_numeric(p["per"], errors="coerce")
    c = px[["date", "close"]].copy()
    c["date"] = pd.to_datetime(c["date"])
    c = c.dropna()
    j = p.merge(c, on="date").sort_values("date").tail(1)      # 最新一天：PER 空白（常見於賠錢）不往前找舊值
    if j.empty or not (j["per"].iloc[0] > 0) or (c["date"].max() - j["date"].iloc[0]).days > PER_STALE_DAYS:
        return None
    return float(j["close"].iloc[0]) / float(j["per"].iloc[0])


def _avg3_eps(q: pd.DataFrame) -> float | None:
    """近 12 季 EPS 合計 ÷ 3（3 年平均年 EPS）；不足 12 季或有缺值 → None。"""
    from screener import quarterly_prep as qp

    e = qp.last_n_quarters(q.set_index("period_end")["eps"], 12)
    return float(e.sum()) / 3 if e is not None else None


def _eps_base(typ: str, nc: dict | None, q: pd.DataFrame, ttm: float, avg3: float | None,
              peak: bool, checks: list[dt.Check]) -> tuple[float, str, bool]:
    """三價的 EPS 基準（呼叫端已確認近四季 EPS > 0）。回傳 (EPS, 名稱, 是否用前瞻 EPS)。
    一般／高成長：前瞻 4 季 EPS（NC）；NC ≤ 0 或任一試算閘門（橋接殘差／業外／月營收口徑／近零 EPS）擋下 → 近四季實際。
    循環、或歷史高獲利區＋循環跡象：近四季與 3 年平均取低者（不用高峰 EPS）；3 年平均不可用 → 近四季並降級。"""
    if ttm is None:          # 只有 PB 路線會走到這裡（金融股最新季 EPS 缺值）；PB 不用 EPS
        return None, "過去 4 季 EPS", False
    nc_eps = nc.get("eps_nc") if nc and nc.get("ok") else None
    nc_unusable = bool(nc and nc.get("ok") and (en.FALLBACK_FLAG in (nc.get("flags") or []) or (nc.get("k") or 0) >= 3))
    if nc_unusable:          # 前瞻退回過去 4 季，或財報已落後 3 季以上：三價用過去 4 季 EPS，不稱前瞻
        nc_eps = None
        if (nc.get("k") or 0) >= 3:
            checks.append(dt.Check("財報落後", "degrade", None, "財報已落後 3 季以上，三價改用過去 4 季 EPS"))
    if typ in ("normal", "growth") and nc_eps is not None and nc_eps > 0:
        checks.append(dt.near_zero_eps(nc_eps, q))
        gate = any(c.level == "block" and c.name in GATE_NAMES for c in checks)
        if not gate and not peak:
            return float(nc_eps), "前瞻 4 季 EPS", True
    elif typ in ("normal", "growth") and nc is not None and nc.get("ok") and not nc_unusable:
        checks.append(dt.Check("前瞻EPS≤0", "severe", None, "前瞻 4 季 EPS ≤ 0，改用過去 4 季 EPS"))
    if typ == "cyclical" or peak:
        if avg3 is not None and avg3 > 0:
            return min(ttm, avg3), "近四季與 3 年平均較低者", False
        checks.append(dt.Check("3年平均", "degrade", None, "3 年平均 EPS 不可用或 ≤ 0，改用過去 4 季 EPS"))
    return ttm, "過去 4 季 EPS", False


def _fallback(out: dict, typ: str, eps: float, eps_name: str, price, why: str, checks: list[dt.Check]) -> None:
    """自身歷史倍數不可用 → 以「類型參考倍數」補位（一律低可信度、不給滾動獲利估值價與購買參考價）。"""
    lo, mid, hi = FALLBACK_MULTS[typ]
    b = {"ok": True, "raw": dict(p20=lo, p50=mid, p80=hi), "capped": dict(p20=lo, p50=mid, p80=hi)}
    p = mu.prices(eps, b)
    out["method"] = "PE"
    out["prices"] = {**p, "base": eps, "base_name": eps_name, "source": "補位", "mults": [lo, mid, hi]}
    out["position"] = mu.classify_position(price, p) if price else "na"
    out["notes"].append(f"{why}；改用類型參考倍數 {lo}／{mid}／{hi} × {eps_name}。")
    checks.append(dt.Check("補位倍數", "severe", None, "自身歷史倍數不可用，改用類型參考倍數補位"))


def _finish(out: dict, checks: list[dt.Check]) -> dict:
    # 風險閘門不再擋價：剩下的 block（EPS 試算不可靠等）一律標成「嚴重」→ 可信度低（價格已換 EPS 基準或補位）
    checks = [dt.Check(c.name, "severe", c.value, c.why) if c.level == "block" else c for c in checks]
    out["checks"] = _check_pack(checks)
    out["confidence"] = dt.confidence(checks)
    return out
