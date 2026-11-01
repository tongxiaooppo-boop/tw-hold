"""估值卡片資料（估值改版 A13，2026-11-01）：分類 → 前瞻 EPS → 月底倍數三價 → 12 個月基準情境價 → 可信度。

純函式，不讀檔：app 把個股的季報 `qf`、月營收 `rev`、股價 `px`、倍數 `per` 與
`data/derived/stock_class.json` 裡該檔的分類 dict `cls` 傳進來。定義見 `D:\\g\\claude\\估值定義定案草案.md`
§3～§6；第一版範圍（誠實揭露，卡片也會寫）：
- 一般／高成長：PE 三價（月底 P20/P50/P80 × EPS_NC）＋12 個月基準價（EPS_F4 × 倍數）。
- 金融、循環・資產重：PB 三價（× 最新 BVPS）；**12 個月價第一版不給**（需要 EPS_norm 與 BVPS 橋接）。
- 循環・資產輕、特殊、資料不足：不給價。
- 一般／高成長若狀態為虧損／獲利不穩／轉機：不給 PE 價，仍顯示前瞻 EPS 供參考。
- D4 高峰閘門（簡化版）：歷史高獲利區 ＋（疑似循環 或 單一景氣事件 或 營運回撤 ≥50%）→ 不給一般三價。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from screener import detect as dt
from screener import eps_nowcast as en
from screener import multiples as mu

CARD_VERSION = "card-v1-2026-11-01"
PE_NORMAL = dict(years=5, min_months=48, cap=30.0)
PE_NORMAL_EXC = dict(years=5, min_months=48, cap=50.0)      # 5 年每年獲利且年均 PE 都 >30
PE_GROWTH = dict(years=3, min_months=30, cap=50.0)
PB_ALL = dict(years=None, min_months=60, cap=None)
STATES_NO_PE = ("虧損", "獲利不穩", "轉機", "預估轉虧", "谷底回升")
DIFF_WARN = 0.15            # 主卡三價與「已公布 TTM 對照價」差 >15% → 警示
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
    return s[~s.index.duplicated(keep="last")].dropna().sort_index()


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
    """每股淨值 ＝ 收盤價 ÷ 交易所股價淨值比（同一天），與倍數序列同口徑。"""
    if per is None or per.empty or px is None or px.empty:
        return None
    p = per[["date", "pbr"]].copy()
    p["date"] = pd.to_datetime(p["date"])
    p = p[pd.to_numeric(p["pbr"], errors="coerce") > 0].sort_values("date")
    c = px[["date", "close"]].copy()
    c["date"] = pd.to_datetime(c["date"])
    j = p.merge(c.dropna(), on="date").tail(1)
    if j.empty:
        return None
    return float(j["close"].iloc[0]) / float(j["pbr"].iloc[0])


def _peak_block(cls: dict) -> str | None:
    st, sub, m = cls.get("state") or [], cls.get("subtags") or [], cls.get("metrics") or {}
    if "歷史高獲利區" not in st:
        return None
    dd = m.get("max_dd")
    if "疑似循環" in sub or "僅單一景氣事件" in sub or (isinstance(dd, (int, float)) and dd >= 0.5):
        return "目前處於自身歷史高獲利區，且有景氣循環跡象：用高峰 EPS 乘歷史倍數會高估，不給一般三價"
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
    if len(q) < 4:
        out["no_price"] = "財報不足 4 季"
        return out
    monthly = _monthly(rev)

    # ── 前瞻 EPS（非金融才有毛利欄可試算）──
    nc = None
    if typ != "financial" and len(monthly):
        nc = en.nowcast(q, monthly, g_far_zero=(typ == "cyclical"))
        out["eps"] = nc
        if nc.get("ok"):
            for f in nc.get("flags") or []:
                checks.append(dt.Check(f, "degrade", None, f))
            checks += [dt.shares_check(q), dt.bridge_residual(q, nc.get("params") or {}),
                       dt.nonop_gate(q), dt.revenue_caliber(q, monthly)]

    # ── 路由 ──
    if typ not in ("insufficient", "special", "financial", "cyclical", "normal", "growth"):
        out["no_price"] = f"未知分類「{typ}」，不給價"
        return _finish(out, checks)
    if typ in ("insufficient", "special"):
        out["no_price"] = {"insufficient": "財報不足 12 季，不分類不給價",
                           "special": "特殊類型（生技／建材營造／併購重組等），歷史倍數不可比，不給價"}[typ]
        return _finish(out, checks)
    is_pb = typ == "financial" or (typ == "cyclical" and "資產重" in subtags)
    if typ == "cyclical" and not is_pb:
        out["no_price"] = "景氣循環・資產輕：第一版不給價（需要多年平滑盈餘估值，尚未實作）"
        return _finish(out, checks)

    if is_pb:
        out["method"] = "PB"
        b = mu.band(per, "pbr", **PB_ALL)
        out["band"] = b
        bv = _bvps(per, px)
        checks += [dt.dist_check(b), dt.pb_events(per, share_events)]
        p = mu.prices(bv, b) if bv else None
        if p is None:
            out["no_price"] = "歷史股價淨值比或每股淨值不足"
        else:
            out["prices"] = {**p, "base": bv, "base_name": "每股淨值"}
            out["position"] = mu.classify_position(price, p) if price else "na"
            out["notes"].append("PB 三價＝歷史月底股價淨值比分位 × 最新每股淨值；12 個月基準價：循環・金融第一版不給。")
            if typ == "financial":
                out["notes"].append("金融股 2026 起 IFRS 17 淨值有斷點，跨年 PB 不完全可比。")
        return _finish(out, checks)

    # ── PE 路線（一般／高成長）──
    out["method"] = "PE"
    if not nc or not nc.get("ok"):
        out["no_price"] = (nc or {}).get("reason") or "月營收不足，無法試算前瞻 EPS"
        return _finish(out, checks)
    if any(s in states for s in STATES_NO_PE):
        hit = "、".join(s for s in states if s in STATES_NO_PE)
        out["no_price"] = f"目前狀態「{hit}」：PE 法不適用，只列前瞻 EPS 供參考"
        return _finish(out, checks)
    pk = _peak_block(cls)
    if pk:
        out["no_price"] = pk
        return _finish(out, checks)

    spec = PE_GROWTH
    if typ == "normal":
        spec = PE_NORMAL
        if mu.high_pe_exception(per, _yearly_eps(q)):
            spec = PE_NORMAL_EXC
            out["notes"].append("近 5 年每年獲利且年均 PE 都 >30：倍數上限放寬到 50。")
    b = mu.band(per, "per", **spec)
    out["band"] = b
    checks += [dt.dist_check(b), dt.near_zero_eps(nc.get("eps_nc"), q)]
    base = nc.get("eps_nc")
    if b.get("ok") and b.get("cap") and b["raw"]["p20"] >= b["cap"]:
        out["no_price"] = (f"歷史月底本益比 P20 已 ≥ 上限 {b['cap']:.0f}"
                           f"（原始 {b['raw']['p20']:.1f}/{b['raw']['p50']:.1f}/{b['raw']['p80']:.1f}），截斷後三價相同，不給價")
        return _finish(out, checks)
    p = mu.prices(base, b) if base else None
    if p is None:
        out["no_price"] = (b.get("reason") if b and not b.get("ok") else "預估 EPS ≤ 0 或歷史本益比不足")
        return _finish(out, checks)
    out["prices"] = {**p, "base": base, "base_name": "前瞻四季 EPS"}
    out["position"] = mu.classify_position(price, p) if price else "na"
    out["truncated"] = bool(b.get("truncated"))
    if b.get("truncated"):
        r, c = b["raw"], b["capped"]
        out["notes"].append(f"倍數上限 {b['cap']:.0f}：原始 P20/P50/P80 ＝ {r['p20']:.1f}/{r['p50']:.1f}/{r['p80']:.1f}，"
                            f"截斷後 {c['p20']:.1f}/{c['p50']:.1f}/{c['p80']:.1f}。")
        checks.append(dt.Check("倍數截斷", "degrade", None, "倍數被上限截斷"))
    # 對照：用已公布 TTM
    ttm = nc.get("eps_ttm")
    if ttm and ttm > 0 and not nc.get("fallback"):
        pt = mu.prices(ttm, b)
        if pt:
            diff = p["fair"] / pt["fair"] - 1
            out["compare"] = {"eps_ttm": ttm, "cheap": pt["cheap"], "fair": pt["fair"], "dear": pt["dear"],
                              "diff": diff, "warn": abs(diff) > DIFF_WARN}
    # 12 個月基準情境價（與現價無關）。財報過舊（k≥3，最新月營收已超過最後財報季三季以上）→ F4 的
    # 「未來 4 季」從最後財報季起算，可能已經是過去的季度，不給
    f4 = nc.get("eps_f4")
    if f4 and (nc.get("k") or 0) >= 3:
        f4 = None
        out["notes"].append("財報已落後 3 季以上，不給 12 個月基準價。")
    if f4 and f4 > 0:
        c = b["capped"]
        out["forward"] = {"eps_f4": f4, "lo": f4 * c["p20"], "base": f4 * c["p50"], "hi": f4 * c["p80"],
                          "implied_pe": price / f4 if price else None,
                          "upside": (f4 * c["p50"] / price - 1) if price else None,
                          "far_quarters": nc.get("f4_far_quarters")}
        if nc.get("f4_far_quarters"):
            out["notes"].append(f"12 個月價有 {nc['f4_far_quarters']} 季沒有任何月營收，純趨勢外推。")
    return _finish(out, checks)


def _finish(out: dict, checks: list[dt.Check]) -> dict:
    conf = dt.confidence(checks)
    out["checks"] = _check_pack(checks)
    out["confidence"] = conf
    if conf["level"] == "不給價" and out.get("prices"):
        out["no_price"] = "；".join(conf["blocks"])
        out["prices"] = out["forward"] = out["position"] = out["compare"] = None
    return out
