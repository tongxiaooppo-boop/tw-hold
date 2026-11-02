"""估值卡引擎（估值 2.0，upgrade_guide §5；取代 card-v2）。

【框架由 Opus 定（P3，2026-11-02），實作者不得改介面、常數名與值、回傳欄位、字串常數】函式本體由 P3 實作。
純函式，不讀檔（share_basis 事件表例外）。app 只讀 build_card 的回傳排版，不重算。

輸入（build_card）
- qf：單季財報（reference.loader.load_quarterly(live=True) 的該檔，已 corporate_actions.adjust_eps）。
  需要欄位 Q_COLS；缺欄補 NaN。
- rev：月營收（month "YYYY-MM"、revenue）。
- px：日線（date、close；原始收盤）。price＝最後一列 close。
- cls：stock_class.json 該檔 dict（ticker、industry、industry_group、type、display_type、state、subtags、
  why、decided_at、metrics）。None → tier D。
- mh：multiples_self.build_history 的該檔列（HIST_COLUMNS）；None／空 → 視為 0 個有效月。
- rev_hist：eps_revision.parquet 的該檔列；None／空 → revision＝{last_pct: None, streak: 0, direction: None}。
- industry_pe：industry_pe.json 的 "industries"（{產業: {median_pe, n, values}}）；None → B 層只給 pe_now。
- asof：評價日（app 傳今天台北日期）。所有窗口用 live=True。

決策順序（§5-1）
  1. cls None → D「這檔不在分類母體（上市櫃且財報 ≥12 季），不做估值」；q 少於 4 季 → D「財報不足 4 季」
  2. 算 windows＝eps_windows.windows(q, monthly, asof, live=True, financial=FIN)，
     FIN＝cls["industry_group"]=="financial" 或 type=="financial"
     checks＝detect.data_checks + share_checks + comparability_checks(cls, 採用的 stats) + estimate_checks；
     status＝detect.summarize(checks)。estimate stop → 近 4 季改用 windows["reported"]、前瞻＝None，
     eps["est_disabled"]＝stop 的 why。
  3. share_basis stop → D，reason＝stopped 的 why（PE、PB 都不給）
  4. route_pb(cls)（金融、循環・資產重、特殊且 metrics.special_triggers 含 "construction"）→
     PB 窗（kind "pb"、metric "pb"、cap None、全歷史）tier_a 過且 bvps_live 有值 → A-PB；否則 D
     （reason：PB_NO_HIST 或 BVPS_NA）。PB 路線不看近 4 季 EPS 正負。
  5. 近 4 季窗口不可用（data stop 或 ttm.ok False）→ D，reason＝f"近 4 季 EPS 不可用（{原因}）"
  6. 近 4 季 EPS < EPS_MIN（≤0 虧損；0～0.05 微利，c_tier.text＝C_TEXT_THIN）→ C
  7. type ∈ {"special", "insufficient"} 或不在 PE_KIND → D（reason 用 D_REASONS）
  8. PE 窗 tier_a 過 → A-PE；否則 B
  route：第 4 步起 route_pb → "PB"，第 5、6、8 步 → "PE"；第 1、3、7 步 → None。
  comparability_checks 在決定採用哪組 stats 之後才加（D 層傳 None），status 最後才 summarize；
  estimate stop 要在第 5 步之前套用。notes 不重複（同句只加一次）。

A-PE
- kind＝PE_KIND[type]；cap＝pe_cap(type, mh, q, asof)
- 基準 EPS：cyclical 或 peak_block(cls) → min(近 4 季, eps_avg(q, 12)) 名稱 BASE_LOW（eps_avg 為 None 或 ≤0
  → 近 4 季、名稱 BASE_TTM，notes 加 NOTE_AVG_NA）；其餘 → 近 4 季，BASE_TTM。cyclical 或 peak 另給 eps_3y_avg＝eps_avg(q, 12)
  （畫面三價旁並列「3 年平均 Y；近 4 季 Z」；使用者 11/2：不列 5 年平均）。
- prices＝three_prices(基準, stats)；raw P20 ≥ cap → cheap／fair／dear 皆 None、position="na"、notes 加 NOTE_CAP_FLAT、
  buy_range None。
- fwd_prices（只在：非 cyclical、非 peak、前瞻可用、前瞻季≠近 4 季季別、前瞻 EPS ≥ EPS_MIN、
  PE_FWD 窗 n_valid ≥ multiples_self.VALID_MIN[kind 的 key]（不套緩衝）時給）＝three_prices(前瞻 EPS, 前瞻 stats)，
  base_name＝BASE_FWD；否則 None，前瞻季＝近 4 季季別時 notes 加 NOTE_FWD_SAME。
- buy_range＝buy_range(prices, fwd_prices, revision, price)
A-PB：prices＝three_prices(bvps_live, pb stats)，base_name＝BASE_BVPS；fwd_prices None；buy_range 只 normal；
  金融另給 roe＝roe_ttm(q)。
B：b_tier＝b_tier(price, 近 4 季 EPS, industry_pe.get(cls["industry"]))
C：c_tier＝c_tier(price, bvps_live(q), mh, asof)
所有層：growth＝growth_rows(...)、revision、quality（cfo_ni、accrual）、status、notes。
position：A 層 multiples.classify_position 同規則（price < cheap → cheap；≤ dear → fair…；任一 None → "na"）。

回傳欄位（§5-5，app 只讀這些；缺的一律給 None，不省略 key）
  ok(bool：cls 不是 None 就 True), tier, route("PE"|"PB"|None), reason(str|None), price, px_date("YYYY/MM/DD"),
  ticker, type, display_type, state(list), subtags(list), why(list), class_asof,
  eps{reported, ttm, fwd: EpsWindow.to_dict() | None, est_disabled: str|None},
  growth(list，見 growth_rows), prices(dict|None), position(str), fwd_prices(dict|None),
  buy_range(dict|None), revision(dict), b_tier(dict|None), c_tier(dict|None), roe(float|None),
  eps_3y_avg(float|None), price_note(str|None：沒有三價時放在三價位置的短句，見 price_note()), quality{cfo_ni, accrual}, status(summarize 結果), notes(list[str]), version
  P4 新增：nonop_hist(list，nonop_rows)、nonop_median(float|None，eps_windows.nonop_median)、fwd_note(str|None，fwd_note())、
  revision["last_event"]（rev_hist 最後一列 event，無 → None）、buy_range 多 where／gap（buy_where()）
prices／fwd_prices dict：{cheap, fair, dear, base, base_name, metric("pe"|"pe_fwd"|"pb"), mults(tuple 截斷後),
  raw_mults(tuple), capped(bool), cap(float|None), n_valid, n_loss, window("YYYY-MM～YYYY-MM")}
"""
from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pandas as pd

from reference import share_basis as sb
from screener import detect as dt
from screener import eps_windows as ew
from screener import growth as gr
from screener import multiples_self as ms
from screener.quarterly_prep import last_n_quarters, to_single_quarter_cashflow


def _finite(x) -> bool:
    return x is not None and bool(np.isfinite(x))


def _number(x):
    return float(x) if _finite(x) else None


def _quarters(q):
    d = q.copy() if q is not None else pd.DataFrame()
    if "period_end" not in d:
        d["period_end"] = pd.Series(dtype="datetime64[ns]")
    d["period_end"] = pd.to_datetime(d["period_end"])
    d = d.sort_values("period_end", kind="stable").drop_duplicates("period_end", keep="last")
    for c in Q_COLS:
        if c not in d:
            d[c] = np.nan
        d[c] = pd.to_numeric(d[c], errors="coerce").astype(float)
        d[c] = d[c].where(np.isfinite(d[c]))
    return d


def _monthly(rev):
    if rev is None or rev.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    s = pd.Series(pd.to_numeric(rev["revenue"], errors="coerce").to_numpy(),
                  index=pd.to_datetime(rev["month"]).dt.to_period("M").dt.to_timestamp())
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s.where(np.isfinite(s))


def _history(mh):
    if mh is None or mh.empty:
        return pd.DataFrame({c: pd.Series(dtype=float if c.startswith("eps_") else object)
                             for c in ms.HIST_COLUMNS})
    return mh


def _tail(q, col, n=4):
    d = _quarters(q)
    return last_n_quarters(pd.Series(d[col].to_numpy(), index=pd.DatetimeIndex(d["period_end"])), n)


def _end_mean(q, col):
    values = [q.iloc[i][col] for i in (0, -1) if _finite(q.iloc[i][col])]
    return float(np.mean(values)) if values else None

CARD_VERSION = "card-v4-val2"
Q_COLS = ["revenue", "gross_profit", "op_income", "pretax_income", "net_income", "ni_parent", "eps",
          "capital_stock", "equity_parent", "total_assets", "ocf"]
TIERS = ("A", "B", "C", "D")
PE_KIND = {"normal": "normal", "growth": "growth", "cyclical": "cyclical"}
EPS_MIN = 0.05
HYST_MONTHS = 24            # tier_a 緩衝：往回模擬幾個完整月份
INDUSTRY_MIN_N = 8          # 【起始值】§12
C_PB_MIN = 12               # C 層 PB 位置至少要幾個有效月
HIGH_PE_YEARS = 5
HIGH_PE_LEVEL = 30.0

BASE_TTM = "近 4 季 EPS"
BASE_FWD = "前瞻 4 季 EPS"
BASE_LOW = "較低獲利情境"
BASE_BVPS = "每股淨值"
D_REASONS = {"special": "特殊類型（生技／併購重組等），歷史倍數不可比，不做估值",
             "insufficient": "財報不足 12 季，資料不足，不做估值"}
PB_NO_HIST = "股價淨值比自身歷史不足（有效月數未達門檻）"
BVPS_NA = "每股淨值推不出（缺歸母權益或股數）"
C_TEXT = "虧損中，不用獲利估價"
C_TEXT_THIN = "獲利接近零（近 4 季 EPS 不到 0.05 元），不用獲利估價"
NOTE_CAP_FLAT = "歷史倍數高於上限，三價不給（只列原始倍數）"
NOTE_FWD_SAME = "新季營收未出，前瞻 4 季與近 4 季相同"
NOTE_AVG_NA = "3 年平均 EPS 不可用，較低獲利情境改用近 4 季"
BUY_NOTE_ABOVE = "現價高於購買區間上緣"
BUY_NOTE_FWD = "前瞻 4 季 EPS 連續上修，上緣改用前瞻合理價"
# 沒有三價時，卡片三價位置的短句（使用者 11/2：簡單說明放三價那裡，詳細點開看；app 後面接「詳見 📊 估值定位細節」）
PRICE_NOTES = {"universe": "不在估值範圍", "few": "財報太少，不估價", "reduction": "減資後等新財報，暫不估價",
               "events": "股數資料讀取失敗，暫不估價", "pb_hist": "淨值比歷史太短，不估價",
               "bvps": "缺每股淨值，不估價", "gap": "財報不連續，不估價", "special": "特殊類型，不估價",
               "loss": "虧損中，不估價", "thin": "獲利接近零，不估價", "b_peer": "自身歷史太短，改看產業本益比",
               "b_only": "自身歷史太短，只列本益比", "cap": "歷史本益比高於上限，不估價"}


# P4：前瞻三價那格沒有三價時的短句（P4_spec §1；畫面一定要有字）
FWD_NOTES = {"est_off": "試算停用，不給前瞻三價", "pb": "淨值比路線，不給前瞻三價",
             "cyclical": "循環股不給前瞻三價（用較低獲利情境）", "same": "新季營收未出，前瞻＝近 4 季，不另給",
             "window": "前瞻 4 季不可用（{}），不給", "thin": "前瞻獲利接近零，不給",
             "hist": "前瞻倍數歷史太短，不給"}


def fwd_note(card: dict, cls: dict | None) -> str | None:
    """P4_spec §1：fwd_prices 有值或 tier≠"A" → None；否則依序 est_off（eps.est_disabled）、pb（route=="PB"）、
    cyclical（type=="cyclical" 或 peak_block(cls)）、same（NOTE_FWD_SAME ∈ notes）、window（eps.fwd 為 None 或 ok False，
    {} 填 eps.fwd 的 reason，None 時填「無資料」）、thin（eps.fwd.eps < EPS_MIN）、其餘 hist。"""
    if card.get("fwd_prices") is not None or card.get("tier") != "A":
        return None
    eps = card.get("eps") or {}
    if eps.get("est_disabled"):
        return FWD_NOTES["est_off"]
    if card.get("route") == "PB":
        return FWD_NOTES["pb"]
    if card.get("type") == "cyclical" or peak_block(cls or {}):
        return FWD_NOTES["cyclical"]
    if NOTE_FWD_SAME in card.get("notes", []):
        return FWD_NOTES["same"]
    fwd = eps.get("fwd")
    if not fwd or not fwd.get("ok"):
        return FWD_NOTES["window"].format(fwd.get("reason") if fwd else "無資料")
    if fwd["eps"] < EPS_MIN:
        return FWD_NOTES["thin"]
    return FWD_NOTES["hist"]


def nonop_rows(q: pd.DataFrame) -> list[dict]:
    """P4_spec §1：最近 eps_windows.NONOP_QUARTERS 個有實際財報的季（舊→新），每列
    {"q": "2026Q2", "nonop": pretax_income−op_income, "pretax": pretax_income, "share": nonop÷|pretax|}；
    非有限 → None（share 另在 pretax 為 0 時 None）。q 少於 1 季 → []。"""
    rows = []
    actual = _quarters(q)
    actual = actual[actual["eps"].notna() & actual["revenue"].notna()]
    for r in actual.tail(ew.NONOP_QUARTERS).to_dict("records"):
        pretax = _number(r["pretax_income"])
        nonop = _number(r["pretax_income"] - r["op_income"])
        rows.append(dict(q=str(pd.Timestamp(r["period_end"]).to_period("Q")), nonop=nonop,
                         pretax=pretax, share=nonop / abs(pretax) if nonop is not None and pretax else None))
    return rows


def buy_where(buy: dict | None, price: float | None) -> dict | None:
    """P4_spec §1：buy 為 None → None；回傳 buy 的複本加 where（"below"／"in"／"above"／None）與 gap
    （above：price÷high−1；below：price÷low−1；其餘 None）。"""
    if buy is None:
        return None
    where, gap = None, None
    if _finite(price):
        where = "below" if price < buy["low"] else "above" if price > buy["high"] else "in"
        if where != "in":
            edge = buy["low"] if where == "below" else buy["high"]
            gap = price / edge - 1 if edge else None
    return dict(buy, where=where, gap=gap)


def build_card(qf: pd.DataFrame | None, rev: pd.DataFrame | None, px: pd.DataFrame | None,
               cls: dict | None, mh: pd.DataFrame | None, rev_hist: pd.DataFrame | None,
               industry_pe: dict | None, asof: pd.Timestamp) -> dict:
    """見模組說明。不得丟例外給呼叫端以外的情況：share_basis.EventsUnavailable 由 share_checks 轉成 stop。"""
    q, monthly = _quarters(qf), _monthly(rev)
    cls_data = cls or {}
    price = px_date = None
    if px is not None and not px.empty:
        last = px.iloc[-1]
        price = _number(last["close"])
        px_date = pd.Timestamp(last["date"]).strftime("%Y/%m/%d")
    revision = (ms.revision_streak(rev_hist) if rev_hist is not None and not rev_hist.empty
                else dict(last_pct=None, streak=0, direction=None))
    revision["last_event"] = rev_hist.sort_values("month").iloc[-1]["event"] if rev_hist is not None and not rev_hist.empty else None
    actual = q[q["eps"].notna() & q["revenue"].notna()].tail(ew.NONOP_QUARTERS)
    result = dict(ok=cls is not None, tier="D", route=None, reason=None, price=price, px_date=px_date,
                  ticker=cls_data.get("ticker"), type=cls_data.get("type"),
                  display_type=cls_data.get("display_type"), state=cls_data.get("state") or [],
                  subtags=cls_data.get("subtags") or [], why=cls_data.get("why") or [],
                  class_asof=cls_data.get("decided_at"),
                  eps=dict(reported=None, ttm=None, fwd=None, est_disabled=None), growth=[], prices=None,
                  position="na", fwd_prices=None, buy_range=None, revision=revision, b_tier=None,
                  c_tier=None, roe=None, eps_3y_avg=None, price_note=None, quality=quality(q), status=dt.summarize([]),
                  notes=[], version=CARD_VERSION, nonop_hist=nonop_rows(q) if len(q) >= 4 else [],
                  nonop_median=ew.nonop_median(actual.to_dict("records")) if len(q) >= 4 else None, fwd_note=None)
    if cls is None:
        result["reason"] = "這檔不在分類母體（上市櫃且財報 ≥12 季），不做估值"
        result["price_note"] = price_note(result)
        return result
    if len(q) < 4:
        result["reason"] = "財報不足 4 季"
        result["price_note"] = price_note(result)
        return result
    typ = cls.get("type")
    financial = cls.get("industry_group") == "financial" or typ == "financial"
    construction = "construction" in ((cls.get("metrics") or {}).get("special_triggers") or [])
    windows = ew.windows(q, monthly, asof, live=True, financial=financial)
    checks = dt.data_checks(q, monthly, windows, cls, asof, financial=financial, construction=construction)
    checks += dt.share_checks(str(cls.get("ticker") or ""), q, asof)
    checks += dt.estimate_checks(q, monthly, windows)
    status = dt.summarize(checks)
    disabled = dt.stopped(status, "estimate")
    ttm = windows["reported"] if disabled else windows["ttm"]
    fwd = None if disabled else windows["fwd"]
    result["eps"] = dict(reported=windows["reported"].to_dict(), ttm=ttm.to_dict(),
                         fwd=fwd.to_dict() if fwd is not None else None, est_disabled=disabled)
    result["growth"] = growth_rows(q, monthly, ttm, fwd, asof)
    stats = None
    share_stop = dt.stopped(status, "share_basis")
    if share_stop:
        result["reason"] = share_stop
    elif route_pb(cls):
        result["route"] = "PB"
        valid, pb_stats = tier_a(mh, "pb", "pb", asof, None)
        bvps = bvps_live(q)
        if not valid:
            result["reason"] = PB_NO_HIST
        elif bvps is None:
            result["reason"] = BVPS_NA
        else:
            result["tier"], stats = "A", pb_stats
            result["prices"] = three_prices(bvps, stats, "pb", BASE_BVPS, None)
            if financial:
                result["roe"] = roe_ttm(q)
    elif dt.stopped(status, "data") or not ttm.ok:
        result["route"] = "PE"
        result["reason"] = f"近 4 季 EPS 不可用（{dt.stopped(status, 'data') or ttm.reason}）"
    elif ttm.eps < EPS_MIN:      # P3：微利跟虧損一樣不用獲利估價（PE 會上千）
        result["tier"], result["route"] = "C", "PE"
        result["c_tier"] = c_tier(price, bvps_live(q), mh, asof)
        if ttm.eps > 0:
            result["c_tier"]["text"] = C_TEXT_THIN
    elif typ not in PE_KIND:
        result["reason"] = D_REASONS.get(typ, D_REASONS["special"])
    else:
        kind, cap = PE_KIND[typ], pe_cap(typ, mh, q, asof)
        valid, pe_stats = tier_a(mh, kind, "pe", asof, cap)
        result["route"] = "PE"
        if not valid:
            result["tier"] = "B"
            result["b_tier"] = b_tier(price, ttm.eps, (industry_pe or {}).get(cls.get("industry")))
            result["b_tier"].update(n_valid=pe_stats["n_valid"], n_loss=pe_stats["n_loss"],
                                    window=f"{pe_stats['start']}～{pe_stats['end']}")
            stats = pe_stats
        else:
            result["tier"], stats = "A", pe_stats
            base, name = ttm.eps, BASE_TTM
            peak = peak_block(cls)
            if typ == "cyclical" or peak:
                avg = eps_avg(q, 12)
                result["eps_3y_avg"] = avg
                if avg is not None and avg > 0:
                    base, name = min(base, avg), BASE_LOW
                else:
                    result["notes"].append(NOTE_AVG_NA)
            result["prices"] = three_prices(base, stats, "pe", name, cap)
            if _finite(stats["raw_mults"][0]) and stats["raw_mults"][0] >= cap:
                result["prices"].update(cheap=None, fair=None, dear=None)
                result["notes"].append(NOTE_CAP_FLAT)
            same = fwd is not None and tuple(r.q for r in fwd.quarters) == tuple(r.q for r in ttm.quarters)
            if same:
                result["notes"].append(NOTE_FWD_SAME)
            if (typ != "cyclical" and not peak and fwd is not None and fwd.ok and not same
                    and _finite(fwd.eps) and fwd.eps >= EPS_MIN):
                fs = ms.window_stats(_history(mh), kind, "pe_fwd", asof, cap)
                key = "normal" if kind == "cyclical" else kind
                if fs["n_valid"] >= ms.VALID_MIN[key]:
                    result["fwd_prices"] = three_prices(fwd.eps, fs, "pe_fwd", BASE_FWD, cap)
    result["position"] = position(price, result["prices"])
    result["buy_range"] = buy_where(buy_range(result["prices"], result["fwd_prices"], revision, price), price)
    checks += dt.comparability_checks(cls, stats)
    result["status"] = dt.summarize(checks)
    result["notes"] = list(dict.fromkeys(result["notes"]))
    result["price_note"] = price_note(result)
    result["fwd_note"] = fwd_note(result, cls)
    return result


def price_note(card: dict) -> str | None:
    """三價（prices 的 cheap／fair／dear）都有值 → None；否則依序回 PRICE_NOTES 的短句：
    ok False → universe；tier C → c_tier.text 為 C_TEXT_THIN 時 thin，否則 loss；
    tier B → b_tier.industry_pct 有值 b_peer，否則 b_only；tier A（三價被 P20≥上限清空）→ cap；
    tier D 依 reason：「財報不足」few、含「現金減資」reduction、含「股數事件表」events、＝PB_NO_HIST pb_hist、
    ＝BVPS_NA bvps、以「近 4 季 EPS 不可用」開頭 gap、其餘（特殊類型、資料不足 12 季）→ 資料不足 12 季為 few，否則 special。"""
    p = card.get("prices") or {}
    if all(_finite(p.get(k)) for k in ("cheap", "fair", "dear")):
        return None
    tier, reason = card.get("tier"), card.get("reason") or ""
    if not card.get("ok"):
        key = "universe"
    elif tier == "C":
        key = "thin" if (card.get("c_tier") or {}).get("text") == C_TEXT_THIN else "loss"
    elif tier == "B":
        key = "b_peer" if (card.get("b_tier") or {}).get("industry_pct") is not None else "b_only"
    elif tier == "A":
        key = "cap"
    elif "財報不足" in reason:
        key = "few"
    elif "現金減資" in reason:
        key = "reduction"
    elif "股數事件表" in reason:
        key = "events"
    elif reason == PB_NO_HIST:
        key = "pb_hist"
    elif reason == BVPS_NA:
        key = "bvps"
    elif reason.startswith("近 4 季 EPS 不可用"):
        key = "gap"
    else:
        key = "special"
    return PRICE_NOTES[key]


# ── 路由與分層 ────────────────────────────────────────────────────

def route_pb(cls: dict) -> bool:
    """type=="financial" 或 industry_group=="financial"（P3：銀行／證券沒有營收欄，分類會判成資料不足，仍走 PB）；
    或 type=="cyclical" 且 "資產重" ∈ subtags；
    或 type=="special" 且 "construction" ∈ metrics.special_triggers。"""
    typ = cls.get("type")
    return (typ == "financial" or cls.get("industry_group") == "financial" or (typ == "cyclical" and "資產重" in (cls.get("subtags") or []))
            or (typ == "special" and "construction" in
                ((cls.get("metrics") or {}).get("special_triggers") or [])))


def peak_block(cls: dict) -> bool:
    """沿用 card-v2 `_peak_block` 判斷（"歷史高獲利區" ∈ state 且（疑似循環／僅單一景氣事件 ∈ subtags 或 max_dd ≥ 0.5））。"""
    st, sub, m = cls.get("state") or [], cls.get("subtags") or [], cls.get("metrics") or {}
    dd = m.get("max_dd")
    return ("歷史高獲利區" in st and ("疑似循環" in sub or "僅單一景氣事件" in sub
                                    or (_finite(dd) and dd >= 0.5)))


def tier_a(mh: pd.DataFrame | None, kind: str, metric: str, asof: pd.Timestamp,
           cap: float | None) -> tuple[bool, dict]:
    """A 層門檻含緩衝（§4-3、§12 VALID_MIN／VALID_EXIT）。
    M0＝multiples_self.last_complete_month(asof)；對 m＝M0−(HYST_MONTHS−1) … M0 逐月：
      n_m＝window_stats(mh, kind, metric, asof=m 的月底, cap)["n_valid"]；
      state＝multiples_self.is_valid_tier_a(n_m, k, was_a=state)，起始 state=False；
      k＝kind（metric=="pb" 時 k="pb"）。
    回傳 (最後 state, window_stats(mh, kind, metric, asof, cap))。mh None／空 → (False, 該 stats 以空表算)。"""
    mh = _history(mh)
    stats = ms.window_stats(mh, kind, metric, asof, cap)
    if mh.empty:
        return False, stats
    state = False
    end = ms.last_complete_month(asof)
    for m in pd.period_range(end - (HYST_MONTHS - 1), end, freq="M"):
        n = ms.window_stats(mh, kind, metric, m.end_time.normalize(), cap)["n_valid"]
        state = ms.is_valid_tier_a(n, "pb" if metric == "pb" else kind, was_a=state)
    return state, stats


def pe_cap(typ: str, mh: pd.DataFrame | None, q: pd.DataFrame, asof: pd.Timestamp) -> float:
    """growth → MULT_CAP["growth"]；normal 且 high_pe_exception → MULT_CAP["normal_exc"]；其餘 MULT_CAP["normal"]。"""
    key = "growth" if typ == "growth" else "normal_exc" if typ == "normal" and high_pe_exception(mh, q, asof) else "normal"
    return ms.MULT_CAP[key]


def high_pe_exception(mh: pd.DataFrame | None, q: pd.DataFrame, asof: pd.Timestamp) -> bool:
    """近 HIGH_PE_YEARS 個完整曆年（asof 年之前的 5 年）每一年：該年 4 季 EPS 都有限且合計 >0，
    且 mh 該年 valid_pe 的 pe 平均 > HIGH_PE_LEVEL（該年沒有有效月 → False）。全部成立才 True。"""
    if mh is None or mh.empty:
        return False
    q = _quarters(q)
    periods = q["period_end"].dt.to_period("Q")
    for year in range(pd.Timestamp(asof).year - HIGH_PE_YEARS, pd.Timestamp(asof).year):
        rows = q[periods.dt.year == year]
        if len(rows) != 4 or not np.isfinite(rows["eps"]).all() or rows["eps"].sum() <= 0:
            return False
        hist = mh[mh["month"].str.startswith(str(year)) & mh["valid_pe"].fillna(False).astype(bool)]
        values = hist.loc[np.isfinite(hist["pe"]) & (hist["pe"] > 0), "pe"]
        if values.empty or values.mean() <= HIGH_PE_LEVEL:
            return False
    return True


# ── 價格 ──────────────────────────────────────────────────────────

def three_prices(base: float, stats: dict, metric: str, base_name: str, cap: float | None) -> dict:
    """{cheap, fair, dear}＝base × stats["mults"]（P20/P50/P80，截斷後）；任一倍數 None → 三價皆 None。
    其餘欄位照模組說明的 prices dict 填（window＝f"{start}～{end}"）。"""
    mults = tuple(_number(v) for v in stats["mults"])
    values = [base * v for v in mults] if _finite(base) and all(v is not None for v in mults) else [None] * 3
    return dict(zip(("cheap", "fair", "dear"), values), base=_number(base), base_name=base_name,
                metric=metric, mults=mults, raw_mults=tuple(_number(v) for v in stats["raw_mults"]),
                capped=stats["capped"], cap=cap, n_valid=stats["n_valid"], n_loss=stats["n_loss"],
                window=f"{stats['start']}～{stats['end']}")


def position(price: float | None, prices: dict | None) -> str:
    """"cheap"／"fair"／"dear"／"na"：price < cheap → cheap；cheap ≤ price ≤ dear → fair；> dear → dear；
    任一 None → na（與 screener.multiples.classify_position 同規則）。"""
    if prices is None or not all(_finite(v) for v in (price, prices.get("cheap"), prices.get("fair"), prices.get("dear"))):
        return "na"
    if price < prices["cheap"]:
        return "cheap"
    if price <= prices["dear"]:
        return "fair"
    return "dear"


def buy_range(prices: dict | None, fwd_prices: dict | None, revision: dict, price: float | None) -> dict | None:
    """§5-3。prices 或其 cheap／fair 為 None → None。
    low＝prices.cheap；state="fwd_up" 當且僅當 revision.direction=="up" 且 streak ≥ multiples_self.REV_STREAK
    且 fwd_prices 的 fair 不是 None 且 > prices.fair → high＝fwd_prices.fair、note＝BUY_NOTE_FWD；
    否則 state="normal"、high＝prices.fair、note＝None。high < low → None。
    price 不是 None 且 > high → note 改為 BUY_NOTE_ABOVE（fwd_up 時兩句用「；」接：BUY_NOTE_FWD；BUY_NOTE_ABOVE）。
    回傳 {low, high, state, note}。"""
    if prices is None or not all(_finite(prices.get(k)) for k in ("cheap", "fair")):
        return None
    low, high, state, note = prices["cheap"], prices["fair"], "normal", None
    if (revision.get("direction") == "up" and revision.get("streak", 0) >= ms.REV_STREAK
            and fwd_prices is not None and _finite(fwd_prices.get("fair")) and fwd_prices["fair"] > high):
        high, state, note = fwd_prices["fair"], "fwd_up", BUY_NOTE_FWD
    if high < low:
        return None
    if _finite(price) and price > high:
        note = (note + "；" if note else "") + BUY_NOTE_ABOVE
    return dict(low=low, high=high, state=state, note=note)


# ── B／C 層 ───────────────────────────────────────────────────────

def b_tier(price: float | None, eps_ttm: float, peers: dict | None) -> dict:
    """pe_now＝price ÷ eps_ttm（price None → None）。peers＝{median_pe, n, values}。
    peers None 或 n < INDUSTRY_MIN_N → {pe_now, industry_pct: None, eps_needed: None, n_peers: n 或 0, median_pe: None}；
    否則 industry_pct＝values 中 < pe_now 的比例（0～1）、eps_needed＝price ÷ median_pe、median_pe。"""
    pe = price / eps_ttm if _finite(price) and _finite(eps_ttm) and eps_ttm > 0 else None
    peers = peers or {}
    n = peers.get("n", 0)
    result = dict(pe_now=pe, industry_pct=None, eps_needed=None, n_peers=n, median_pe=None)
    median = peers.get("median_pe")
    if n >= INDUSTRY_MIN_N and _finite(median) and median > 0:
        values = [v for v in peers.get("values", []) if _finite(v) and v > 0]
        result.update(median_pe=median, eps_needed=price / median if _finite(price) else None,
                      industry_pct=float(np.mean(np.array(values) < pe)) if values and pe is not None else None)
    return result


def c_tier(price: float | None, bvps: float | None, mh: pd.DataFrame | None, asof: pd.Timestamp) -> dict:
    """pb_now＝price ÷ bvps（任一 None／≤0 → None）。歷史＝mh 中 month ≤ last_complete_month(asof) 且 valid_pb 的 pb。
    有效月 ≥ C_PB_MIN 且 pb_now 有值 → pb_pct＝歷史 pb < pb_now 的比例；否則 None。
    回傳 {pb_now, pb_pct, n_valid, text: C_TEXT}。"""
    pb = price / bvps if _finite(price) and price > 0 and _finite(bvps) and bvps > 0 else None
    mh = _history(mh)
    hist = mh[(mh["month"] <= str(ms.last_complete_month(asof))) & mh["valid_pb"].fillna(False).astype(bool)]
    values = hist.loc[np.isfinite(hist["pb"].astype(float)) & (hist["pb"].astype(float) > 0), "pb"].astype(float)
    return dict(pb_now=pb, pb_pct=float((values < pb).mean()) if len(values) >= C_PB_MIN and pb is not None else None,
                n_valid=len(values), text=C_TEXT)


# ── 基準數字 ──────────────────────────────────────────────────────

def bvps_live(q: pd.DataFrame) -> float | None:
    """與 multiples_self.build_history 的 bvps 同算法，但所有財報季都視為可見（live）：
    最近一季 equity_parent 有限 >0 的季 Q；股數＝Q 起往前共 5 季中最近一個 |eps| ≥ EPS_MIN 且 ni_parent÷eps 有限 >0 者
    （ni_parent（loader 已依規則頂替），與 build_history 相同）；
    都推不出 → None。回傳 Q.equity_parent ÷ 股數。"""
    q = _quarters(q)
    eq = q[np.isfinite(q["equity_parent"]) & (q["equity_parent"] > 0)]
    if eq.empty:
        return None
    latest = eq.iloc[-1]
    for r in q[q["period_end"] <= latest["period_end"]].tail(5).iloc[::-1].itertuples(index=False):
        ni = r.ni_parent
        if _finite(r.eps) and abs(r.eps) >= EPS_MIN and _finite(ni):
            shares = ni / r.eps
            if _finite(shares) and shares > 0:
                return float(latest["equity_parent"] / shares)
    return None


def eps_avg(q: pd.DataFrame, n: int) -> float | None:
    """最近 n 個曆季相鄰、EPS 都有限的實際季合計 ÷ (n/4)（年化平均）；用 screener.quarterly_prep.last_n_quarters；
    不足或斷季 → None。n=12 → 3 年平均；n=20 → 5 年平均。"""
    tail = _tail(q, "eps", n)
    return float(tail.sum() / (n / 4)) if tail is not None else None


def roe_ttm(q: pd.DataFrame) -> float | None:
    """近 4 季（曆季相鄰）ni_parent 合計 ÷ 平均 equity_parent（第 −4 季與最新季兩期平均；任一缺 → 用有值的那期）。
    分母 ≤0 或 ni_parent 不全 → None。"""
    q = _quarters(q)
    ni = _tail(q, "ni_parent")
    if ni is None:
        return None
    equity = _end_mean(q.tail(4), "equity_parent")
    return float(ni.sum() / equity) if equity is not None and equity > 0 else None


def quality(q: pd.DataFrame) -> dict:
    """近 4 季（曆季相鄰）：cfo_ni＝Σocf ÷ Σni_parent（Σni_parent ≤0 → None）；
    accrual＝(Σnet_income − Σocf) ÷ 平均 total_assets（第 −4 季與最新季；≤0 → None）。缺值 → None。
    ocf 在財報裡是年初至今累計（11/2 對帳發現），先用 quarterly_prep.to_single_quarter_cashflow 轉單季再加總。"""
    q = _quarters(q)
    if "ocf" in q.columns and "ticker" in q.columns:
        q = to_single_quarter_cashflow(q, ("ocf",))
    ocf, ni, net = (_tail(q, c) for c in ("ocf", "ni_parent", "net_income"))
    cfo = float(ocf.sum() / ni.sum()) if ocf is not None and ni is not None and ni.sum() > 0 else None
    assets = None
    if len(q) >= 4 and last_n_quarters(pd.Series(1.0, index=pd.DatetimeIndex(q["period_end"])), 4) is not None:
        ends = q.tail(4).iloc[[0, -1]]["total_assets"]
        if np.isfinite(ends).all():
            assets = float(ends.mean())
    accrual = float((net.sum() - ocf.sum()) / assets) if (net is not None and ocf is not None
                                                       and assets is not None and assets > 0) else None
    return dict(cfo_ni=cfo, accrual=accrual)


# ── 年增率（§6、§9 EPS 卡表格「期間｜營收｜EPS」）──────────────────

def growth_rows(q: pd.DataFrame, monthly: pd.Series, ttm: ew.EpsWindow, fwd: ew.EpsWindow | None,
                asof: pd.Timestamp) -> list[dict]:
    """回傳列（順序固定，不適用的列不放）：每列 {key, period, kind, months_known, rev, eps}，
    rev／eps＝growth.Growth 的 dict（dataclasses.asdict）或 None（畫面印「—」）。
    1. key="month"：最新可見月 m（live：monthly 最後一個有限 >0 的月）；period＝"YYYY-MM"；
       rev＝yoy_revenue(m, 去年同月)；eps=None；kind=None、months_known=None。monthly 空 → 不放。
    2. key="last_q"：近 4 季末季 L（ttm.quarters[-1]）；period＝L.q；kind＝L.kind；
       months_known＝該季已有營收的月數（actual＝3）；
       rev＝yoy_revenue(L 季已有月份營收合計, 去年同月份合計)（任一月缺 → 該月不計入兩邊）；
       eps＝yoy_eps(L.eps, 去年同季實際 EPS)。ttm 不 ok → 不放。
    3. key="ttm"：period＝f"{第一季}～{最後一季}"；rev＝yoy_revenue(Σ近 4 季 rev, Σ一年前 4 季實際 revenue)；
       eps＝yoy_eps(ttm.eps, Σ一年前 4 季實際 EPS)；一年前任一季缺 → 該欄 yoy(…, None)（label "na"）。
    4. key="fwd"：只在 fwd 不是 None、ok、且季別 ≠ 近 4 季時放；rev=None；
       eps＝yoy_eps(fwd.eps, Σ一年前同 4 季實際 EPS)。"""
    q = _quarters(q)
    actual = q.set_index(q["period_end"].dt.to_period("Q"))

    def actual_value(period, col):
        if period not in actual.index:
            return None
        return _number(actual.loc[period, col])

    def previous_sum(rows, col):
        values = [actual_value(pd.Period(r.q, "Q") - 4, col) for r in rows]
        return sum(values) if all(v is not None for v in values) else None

    def row(key, period, kind=None, months_known=None, rev=None, eps=None):
        return dict(key=key, period=period, kind=kind, months_known=months_known,
                    rev=asdict(rev) if rev is not None else None, eps=asdict(eps) if eps is not None else None)

    out = []
    visible = monthly[np.isfinite(monthly) & (monthly > 0)]
    if not visible.empty:
        m = visible.index[-1]
        out.append(row("month", m.strftime("%Y-%m"), rev=gr.yoy_revenue(visible.iloc[-1], monthly.get(m - pd.DateOffset(years=1)))))
    if ttm is None or not ttm.ok or not ttm.quarters:
        return out
    last = ttm.quarters[-1]
    p = pd.Period(last.q, "Q")
    pairs = []
    for m in pd.period_range(p.start_time, p.end_time, freq="M"):
        cur, prev = monthly.get(m.start_time), monthly.get((m - 12).start_time)
        if _finite(cur) and cur > 0 and _finite(prev) and prev > 0:
            pairs.append((cur, prev))
    cur = sum(v[0] for v in pairs) if pairs else None
    prev = sum(v[1] for v in pairs) if pairs else None
    out.append(row("last_q", last.q, last.kind, last.months_known, gr.yoy_revenue(cur, prev),
                   gr.yoy_eps(last.eps, actual_value(p - 4, "eps"))))
    revs = [r.rev for r in ttm.quarters]
    revsum = sum(revs) if all(_finite(v) for v in revs) else None
    out.append(row("ttm", f"{ttm.quarters[0].q}～{last.q}", rev=gr.yoy_revenue(revsum, previous_sum(ttm.quarters, "revenue")),
                   eps=gr.yoy_eps(ttm.eps, previous_sum(ttm.quarters, "eps"))))
    if fwd is not None and fwd.ok and tuple(r.q for r in fwd.quarters) != tuple(r.q for r in ttm.quarters):
        out.append(row("fwd", f"{fwd.quarters[0].q}～{fwd.quarters[-1].q}",
                       eps=gr.yoy_eps(fwd.eps, previous_sum(fwd.quarters, "eps"))))
    return out
