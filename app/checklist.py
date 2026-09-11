"""多軌體檢——把「短線 / 長波段 / 價值 / 定存」四套判準逐條攤開成檢核表。

**只打勾、不加總、不加權、不給 verdict / 買價 / 排名**（PRD §4.1、§5.1）。
骨架回收自舊專案 `books/claude/me/taiwan-stock-analyzer-v3` 的六子項設計，
但那邊的 0–100 加權分全部丟掉，只留「這條門檻成立了沒」。

每列帶一個「組」欄（面向分類）→ UI 分區塊顯示，不再是一張長平表。

門檻來源：
  - 價值 / 定存：讀 `data/derived/factors_{value,deposit}.parquet`（清單頁同一份
    已算好的因子，口徑一致），逐檔一列。
  - 長波段：候選池沒有落地成 parquet → 用 `bundle_data` 的原始 df 現算。
    趨勢模板只做 7 條（不含相對強弱 RS——需全市場橫斷面，個股頁不划算）。

⚠️ 利息保障倍數（舊專案定存子項）：bundle 沒有利息費用欄 → 這條**直接不出現**。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_OK, _NG, _NA = "✅ 成立", "❌ 未達", "— 無資料"


def _state(ok) -> str:
    if ok is None or (isinstance(ok, float) and np.isnan(ok)):
        return _NA
    return _OK if bool(ok) else _NG


def _pct(x, dp: int = 1) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{x * 100:.{dp}f}%"


def _f(x, dp: int = 2) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{x:,.{dp}f}"


def _get(r, k):
    v = r.get(k) if isinstance(r, dict) else (r[k] if k in r.index else None)
    return None if v is None or (np.isscalar(v) and pd.isna(v)) else v


def is_finance(industry) -> bool:
    s = str(industry or "")
    return any(w in s for w in ("金融", "銀行", "保險", "證券"))


class _G:
    """一個面向組——`g("項目", "門檻", "現值", ok)` 累積成帶「組」欄的列。"""

    def __init__(self, sink: list, name: str):
        self.sink, self.name = sink, name

    def __call__(self, item: str, gate: str, cur: str, ok, *, raw: str | None = None):
        self.sink.append({"組": self.name, "項目": item, "門檻": gate, "現值": cur,
                          "狀態": raw or _state(ok)})


def _active_etf_row(g: "_G", active_etf: dict | None) -> None:
    """主動式 ETF 認養——context 列，狀態型（不影響成立與否的判斷，只是攤開）。

    `active_etf`：`build_active_etf_flags.py` 產的 per-ticker 旗標。
      - `None`  → 來源未提供／已過期 → **整列不出現**（同利息保障倍數、融資融券處理）
      - `{}`    → 來源正常但這檔近一日沒有主動式 ETF 動作 → 顯示「無」
    """
    if active_etf is None:
        return
    kind = active_etf.get("kind")
    # 某檔基金漏抓一天時，它的差分跨 > 1 個交易日——門檻欄照實講，不要寫死「近一日」
    sp = active_etf.get("span_days")
    win = f"近 {int(sp)} 個交易日" if isinstance(sp, int) and sp > 1 else "近一日"
    ns = active_etf.get("net_shares")
    lots = f"{ns / 1000:+,.0f} 張" if isinstance(ns, (int, float)) else "—"
    ic = active_etf.get("issuer_count")
    who = f"{ic} 檔 ETF" if isinstance(ic, int) else "主動 ETF"
    cons = active_etf.get("consensus") or 0
    tag = f"、{abs(cons)} 檔共識" if abs(cons) >= 2 else ""
    if kind in ("consensus_buy", "buy"):
        g("主動式 ETF 認養（前五大主動 ETF PCF，非官方三大法人）",
          f"狀態型：{win}主動式 ETF 淨買超", f"{who}淨買超 {lots}{tag}", True)
    elif kind in ("consensus_sell", "sell"):
        g("主動式 ETF 認養（前五大主動 ETF PCF，非官方三大法人）",
          f"狀態型：{win}主動式 ETF 淨賣超", f"{who}淨賣超 {lots.lstrip('+')}{tag}",
          None, raw="⚠️ 命中")
    else:
        g("主動式 ETF 認養（前五大主動 ETF PCF，非官方三大法人）",
          f"狀態型：{win}主動式 ETF 買賣", f"{win}無主動式 ETF 買賣", None)


def summarize(rows: list[dict]) -> dict:
    """檢核列 → 白話「亮點 / 缺口 / 待確認」。**不加總分、不給 verdict**——
    只是把成立/未達/無資料的項目名挑出來，讓人一眼看到卡在哪。"""
    good = [r["項目"] for r in rows if r["狀態"].startswith("✅")]
    bad = [r["項目"] for r in rows
           if r["狀態"].startswith("❌") and not r["項目"].endswith("（參考）")]
    na = [r["項目"] for r in rows if r["狀態"] == _NA]        # 「— 無資料」；風險列的裸「—」不算
    hit = [r["項目"] for r in rows if r["狀態"].startswith("⚠️")]
    return {"亮點": good, "缺口": bad, "待確認": na, "風險命中": hit}


# ─────────────────────────────  價值軌  ─────────────────────────────

def value_checks(r) -> list[dict]:
    """`r`：`factors_value.parquet` 的單列（dict 或 Series）。"""
    if r is None:
        return []
    fin = is_finance(_get(r, "industry"))
    close, cheap = _get(r, "close"), _get(r, "cheap_threshold")
    ceiling, upside = _get(r, "valuation_ceiling"), _get(r, "upside_pct")
    peak, eps_susp = _get(r, "cyclical_peak_flag"), _get(r, "eps_basis_suspect")
    roe, gm, fs = _get(r, "roe"), _get(r, "gross_margin"), _get(r, "f_score")
    ttm_eps, ryoy = _get(r, "ttm_eps"), _get(r, "rev_yoy")
    debt, cr = _get(r, "debt_ratio"), _get(r, "current_ratio")
    fcf, ocf = _get(r, "ttm_fcf"), _get(r, "ttm_ocf")
    rows: list[dict] = []

    g = _G(rows, "估值")
    # 主門檻用「估值上緣」——這才是價值清單判 verdict「無安全邊際」的實際觸發線（§6.3）。
    g("現價未過估值上緣", "現價 ≤ 估值上緣（normalized EPS × PE 均值/P70）",
      f"現價 {_f(close)} / 上緣 {_f(ceiling)}（空間 {_pct(upside)}）",
      None if close is None or ceiling is None else close <= ceiling)
    # 便宜門檻是「深度價值進場價」（5 年均 EPS × PE 三成分位）——結構性成長股常年摸不到，
    # ❌ 是常態、不是警訊；放這裡當參考，不當主判準。
    g("現價落在便宜區（參考）", "現價 ≤ 便宜門檻（= 5 年均 EPS × PE P30；成長股通常摸不到）",
      f"門檻 {_f(cheap)}",
      None if close is None or cheap is None else close <= cheap)
    if peak:
        g("景氣循環高峰旗標", "命中 → 現價 EPS 可能在循環高點，便宜門檻改用均值 EPS 才保守",
          "命中", None, raw="⚠️ 命中")
    if eps_susp:
        g("EPS 基準存疑", "命中 → 近期 EPS 口徑異常，估值數字打折看", "命中", None, raw="⚠️ 命中")

    g = _G(rows, "獲利品質")
    g("ROE（TTM）≥ 10%", "≥ 10%", _pct(roe), None if roe is None else roe >= 0.10)
    g("毛利率 ≥ 30%", "≥ 30%（服務/金融業本就偏低，僅供參考）", _pct(gm),
      None if gm is None else gm >= 0.30)
    g("F-Score ≥ 6", "≥ 6（9 分制）", _f(fs, 0), None if fs is None else fs >= 6)

    g = _G(rows, "成長")
    g("TTM EPS ≥ 8 元", "≥ 8（舊專案成長能力『良』級）", _f(ttm_eps),
      None if ttm_eps is None else ttm_eps >= 8)
    g("營收 YoY ≥ 10%", "TTM 營收年增 ≥ 10%", _pct(ryoy),
      None if ryoy is None else ryoy >= 0.10)

    g = _G(rows, "財務安全")
    if fin:
        g("負債比 ≤ 45%", "金融業不適用（結構性高槓桿）", _pct(debt), None)
        g("流動比 ≥ 2.0", "金融業不適用", _f(cr), None)
    else:
        g("負債比 ≤ 45%", "≤ 45%", _pct(debt), None if debt is None else debt <= 0.45)
        g("流動比 ≥ 2.0", "≥ 2.0", _f(cr), None if cr is None else cr >= 2.0)

    g = _G(rows, "現金流")
    if fin:
        g("自由現金流 / 營運現金流為正", "金融業不適用", "—", None)
    else:
        g("TTM 自由現金流為正", "> 0",
          f"{_f((fcf or 0) / 1e8)} 億" if fcf is not None else "—",
          None if fcf is None else fcf > 0)
        g("TTM 營運現金流為正", "> 0",
          f"{_f((ocf or 0) / 1e8)} 億" if ocf is not None else "—",
          None if ocf is None else ocf > 0)
    return rows


# ─────────────────────────────  定存軌  ─────────────────────────────

def deposit_checks(r) -> list[dict]:
    """`r`：`factors_deposit.parquet` 的單列。"""
    if r is None:
        return []
    fin = is_finance(_get(r, "industry"))
    dy, cy = _get(r, "div_years"), _get(r, "cur_yield")
    floor = _get(r, "yield_floor") or 0.05
    cut, payout = _get(r, "div_cut_5y"), _get(r, "payout_ratio_ttm")
    fcf_cov, fill, ret3 = _get(r, "fcf_cover"), _get(r, "fill_rate"), _get(r, "ret3y_incl")
    debt, roe = _get(r, "debt_ratio"), _get(r, "roe")
    ann_vol, yld_pctile = _get(r, "ann_vol"), _get(r, "yield_pctile_5y")
    rows: list[dict] = []

    g = _G(rows, "配息紀錄")
    g("連續配息 ≥ 7 年", "≥ 7 年（連續不中斷）", f"{_f(dy, 0)} 年",
      None if dy is None else dy >= 7)
    g("近 5 年無實質減配", "近 3 年不得減配；更早的減配須已回復",
      "有減配" if cut else "無", None if cut is None else not cut)
    g(f"現價殖利率 ≥ {floor * 100:.1f}%", f"≥ {floor * 100:.1f}%（硬底線 5%）", _pct(cy),
      None if cy is None else cy >= floor)
    g("殖利率處於 5 年相對高檔", "5 年分位 ≥ 50%（越高越便宜）", _pct(yld_pctile, 0),
      None if yld_pctile is None else yld_pctile >= 0.50)

    g = _G(rows, "配息品質")
    g("配息率適中（≤ 90%）", "TTM 配息率 ≤ 90%", _pct(payout),
      None if payout is None else payout <= 0.90)
    g("近 5 年填息率 ≥ 60%", "≥ 60%", _pct(fill),
      None if fill is None else fill >= 0.60)
    g("近 3 年含息報酬 ≥ 0", "≥ 0（配息沒把股價賠光）", _pct(ret3),
      None if ret3 is None else ret3 >= 0)

    g = _G(rows, "現金流")
    if fin:
        g("自由現金流覆蓋股利", "金融業不適用", "—", None)
    else:
        g("自由現金流覆蓋股利", "TTM FCF ÷ 現金股利 ≥ 1.0", _f(fcf_cov),
          None if fcf_cov is None else fcf_cov >= 1.0)

    g = _G(rows, "財務安全")
    if fin:
        g("負債比 ≤ 45%", "金融業不適用（結構性高槓桿）", _pct(debt), None)
    else:
        g("負債比 ≤ 45%", "≤ 45%", _pct(debt), None if debt is None else debt <= 0.45)
    g("ROE（TTM）≥ 8%", "≥ 8%（獲利撐得起配息）", _pct(roe),
      None if roe is None else roe >= 0.08)

    g = _G(rows, "波動")
    g("年化週波動 ≤ 30%", "≤ 30%（波動別像成長股）", _pct(ann_vol),
      None if ann_vol is None else ann_vol <= 0.30)
    return rows


# ─────────────────────────────  長波段軌  ─────────────────────────────

def _rsi(close: pd.Series, n: int = 6) -> float:
    d = close.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return float(out.iloc[-1]) if len(out) and pd.notna(out.iloc[-1]) else np.nan


def _pctile(hist: pd.Series, val) -> float | None:
    h = pd.to_numeric(hist, errors="coerce")
    h = h[h > 0]
    if val is None or pd.isna(val) or h.empty:
        return None
    return float((h <= val).mean())


def swing_checks(d: dict, active_etf: dict | None = None) -> list[dict]:
    """`d`：`_stock_data()` 的輸出（px / per / qf / rev / chips …）。
    `active_etf`：主動式 ETF 認養旗標（見 `_active_etf_row`），None → 該列不出現。"""
    q, rev, px = d.get("qf"), d.get("rev"), d.get("px")
    per, chp = d.get("per"), d.get("chips")
    rows: list[dict] = []

    g = _G(rows, "營收動能")
    if rev is not None and len(rev) >= 13:
        r = rev.dropna(subset=["revenue"]).sort_values("month").reset_index(drop=True)
        # YoY / MoM 對齊曆月，不是位移 N 列——有缺月的公司用 shift() 會拿錯月份比，
        # 而且完全不報錯（canonical 版見 screener.candidate_pool.monthly_yoy）。
        _rv = dict(zip(pd.to_datetime(r["month"]), r["revenue"]))

        def _rev_at(ts):
            return _rv.get(pd.Timestamp(ts))

        def _rev_yoy(ts):
            cur, ly = _rev_at(ts), _rev_at(pd.Timestamp(ts) - pd.DateOffset(years=1))
            return cur / ly - 1.0 if (cur is not None and ly) else np.nan

        m_now = pd.Timestamp(r["month"].iloc[-1])
        m_pre = m_now - pd.DateOffset(months=1)
        yoy, yoy_p = _rev_yoy(m_now), _rev_yoy(m_pre)
        _pre_rev = _rev_at(m_pre)
        mom = (r["revenue"].iloc[-1] / _pre_rev - 1.0) if _pre_rev else np.nan
        high12 = r["revenue"].iloc[-1] >= r["revenue"].tail(12).max()
        high6 = r["revenue"].iloc[-1] >= r["revenue"].tail(6).max()
        cagr = None
        if len(r) >= 19 and r["revenue"].iloc[-19] > 0:
            cagr = (r["revenue"].iloc[-1] / r["revenue"].iloc[-19]) ** (1 / 1.5) - 1
        g("月營收 YoY > 0", "> 0", _pct(yoy), None if pd.isna(yoy) else yoy > 0)
        g("月營收 YoY ≥ 20%", "≥ 20%（『良』級）", _pct(yoy),
          None if pd.isna(yoy) else yoy >= 0.20)
        g("月營收 MoM ≥ 0", "≥ 0", _pct(mom), None if pd.isna(mom) else mom >= 0)
        g("營收動能加速", "本月 YoY > 上月 YoY", f"{_pct(yoy)} vs {_pct(yoy_p)}",
          None if pd.isna(yoy) or pd.isna(yoy_p) else yoy > yoy_p)
        g("單月營收創高", "創近 6 / 12 個月新高",
          "創 12 月新高" if high12 else ("創 6 月新高" if high6 else "未創高"),
          bool(high6 or high12))
        g("1.5 年營收 CAGR ≥ 8%", "≥ 8%（年化）", _pct(cagr),
          None if cagr is None else cagr >= 0.08)
    else:
        g("營收動能", "需 ≥ 13 個月營收", "資料不足", None)

    g = _G(rows, "獲利成長")
    if q is not None and not q.empty:
        qq = q.sort_values("period_end").reset_index(drop=True)
        last = qq.iloc[-1]
        eps_yoy = None
        if len(qq) >= 5 and pd.notna(qq["eps"].iloc[-5]) and qq["eps"].iloc[-5] != 0:
            eps_yoy = qq["eps"].iloc[-1] / qq["eps"].iloc[-5] - 1.0
        ttm_eps = last.get("ttm_eps")
        ttm_eps_3y = qq["ttm_eps"].shift(12).iloc[-1] if len(qq) >= 13 else np.nan
        roe = last.get("roe")
        gm, gm1, gm2 = (qq["gross_margin"].iloc[-1],
                        qq["gross_margin"].shift(1).iloc[-1],
                        qq["gross_margin"].shift(2).iloc[-1])
        gm_ok = None if any(pd.isna(x) for x in (gm, gm1, gm2)) else not (gm < gm1 < gm2)
        g("季 EPS YoY > 25%", "> 25%（候選池 CANSLIM 門檻）", _pct(eps_yoy),
          None if eps_yoy is None else eps_yoy > 0.25)
        g("近 3 年 TTM EPS 成長", "本期 TTM EPS > 3 年前，且 > 0",
          f"{_f(ttm_eps)} vs {_f(ttm_eps_3y)}",
          None if pd.isna(ttm_eps_3y) or ttm_eps is None
          else (ttm_eps > ttm_eps_3y and ttm_eps > 0))
        g("ROE > 15%", "> 15%（候選池門檻）", _pct(roe),
          None if roe is None or pd.isna(roe) else roe > 0.15)
        g("毛利率未連兩季惡化", "非（本季 < 前季 < 前前季）",
          f"{_pct(gm)} / {_pct(gm1)} / {_pct(gm2)}", gm_ok)

    g = _G(rows, "中期趨勢")
    if px is not None and not px.empty:
        c = px.sort_values("date")["close"].astype(float)
        if len(c) >= 200:
            ma50, ma150, ma200 = (c.rolling(w).mean().iloc[-1] for w in (50, 150, 200))
            ma200_1m = c.rolling(200).mean().shift(21).iloc[-1]
            n252 = min(len(c), 252)
            lo52, hi52 = c.tail(n252).min(), c.tail(n252).max()
            last_c = c.iloc[-1]
            t = [last_c > ma150 and last_c > ma200, ma150 > ma200, ma200 > ma200_1m,
                 ma50 > ma150 > ma200, last_c > ma50, last_c >= lo52 * 1.30,
                 last_c >= hi52 * 0.75]
            cnt = sum(bool(x) for x in t)
            g("Minervini 趨勢模板", "7 項通過 ≥ 6（不含相對強弱 RS）", f"{cnt}/7", cnt >= 6)
        else:
            g("Minervini 趨勢模板", "需 ≥ 200 個交易日", "資料不足", None)

    g = _G(rows, "籌碼")
    if chp is not None and not chp.empty:
        c = chp.sort_values("date")
        net20 = (c["foreign"] + c["trust"] + c["dealer"]).tail(20).sum()
        g("法人 20 日淨買超 > 0", "> 0（外資＋投信＋自營，單位：張）",
          f"{_f(net20, 0)} 張", None if pd.isna(net20) else net20 > 0)
    _active_etf_row(g, active_etf)

    g = _G(rows, "估值位置")
    if per is not None and not per.empty:
        pp = per.sort_values("date")
        pe_valid = pd.to_numeric(pp["per"], errors="coerce")
        pe_now = pe_valid[pe_valid > 0].iloc[-1] if (pe_valid > 0).any() else None
        pb_now = pd.to_numeric(pp["pbr"], errors="coerce").iloc[-1]
        pe_ptile, pb_ptile = _pctile(pp["per"], pe_now), _pctile(pp["pbr"], pb_now)
        g("PE 位於自身歷史低檔", "5+ 年分位 ≤ 40%",
          f"PE {_f(pe_now)}（分位 {_pct(pe_ptile, 0)}）",
          None if pe_ptile is None else pe_ptile <= 0.40)
        g("PB 位於自身歷史低檔", "5+ 年分位 ≤ 40%",
          f"PB {_f(pb_now)}（分位 {_pct(pb_ptile, 0)}）",
          None if pb_ptile is None else pb_ptile <= 0.40)

    g = _G(rows, "風險揭露")
    if q is not None and not q.empty:
        debt = q.sort_values("period_end").iloc[-1].get("debt_ratio")
        if debt is not None and pd.notna(debt):
            g("負債比偏高", "> 70% 視為風險", _pct(debt),
              None, raw="⚠️ 命中" if debt > 0.70 else "—")
    if px is not None and not px.empty:
        rsi6 = _rsi(px.sort_values("date")["close"].astype(float))
        if pd.notna(rsi6):
            g("短線超賣（可能是機會或下跌中）", "RSI(6) < 30", _f(rsi6, 0),
              None, raw="⚠️ 命中" if rsi6 < 30 else "—")
    return rows


# ─────────────────────────────  短線軌  ─────────────────────────────
# tw-hold 是長期持有工具，短線是 tw-swing 的守備範圍。這一軌只把「日線技術面
# 條件」逐條攤開讓人自己看，**零回測支撐**，措辭要最保守（見 SHORT_DISCLAIMER）。
# 融資融券變化：bundle 沒這份資料 → 相關條件直接不出現（同利息保障倍數處理）。

def _macd(close: pd.Series):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    return dif, dea


def _ccp(close: pd.Series, vol: pd.Series, lookback: int = 60, bins: int = 30):
    """近 `lookback` 日成交量密集區價（Chip Concentration Price）——多日收盤 × 量的
    直方圖峰值，取代單日盤中 POC。"""
    c, v = close.tail(lookback), vol.tail(lookback)
    if len(c) < 10 or c.max() == c.min():
        return None
    edges = np.linspace(c.min(), c.max(), bins + 1)
    idx = np.clip(np.digitize(c, edges) - 1, 0, bins - 1)
    w = np.zeros(bins)
    for i, vv in zip(idx, v):
        w[i] += vv if pd.notna(vv) else 0
    peak = int(np.argmax(w))
    return float((edges[peak] + edges[peak + 1]) / 2)


def short_checks(d: dict, active_etf: dict | None = None) -> list[dict]:
    """`d`：`_stock_data()` 的輸出。純日線技術面，**不評分、不給買賣點**。
    `active_etf`：主動式 ETF 認養旗標（見 `_active_etf_row`），None → 該列不出現。"""
    px, chp = d.get("px"), d.get("chips")
    rows: list[dict] = []
    if px is None or px.empty:
        _G(rows, "趨勢結構")("日線技術面", "需 bundle 有價量資料", "資料不足", None)
        return rows

    p = px.sort_values("date").reset_index(drop=True)
    c = p["close"].astype(float)
    vol = p["volume"].astype(float) if "volume" in p.columns else pd.Series(np.nan, index=p.index)
    last = c.iloc[-1]
    ma5, ma10, ma20 = (c.rolling(w).mean().iloc[-1] for w in (5, 10, 20))
    up = c.diff().gt(0)
    dn = c.diff().lt(0)
    consec_up = int(up.tail(10).iloc[::-1].cumprod().sum())   # 從最後一天往回數連漲
    consec_dn = int(dn.tail(10).iloc[::-1].cumprod().sum())
    hi10 = c.iloc[-11:-1].max() if len(c) >= 11 else np.nan
    lo10 = c.iloc[-11:-1].min() if len(c) >= 11 else np.nan

    g = _G(rows, "趨勢結構")
    g("收盤站上 5 日均線", "收盤 > MA5", f"{_f(last)} / MA5 {_f(ma5)}",
      None if pd.isna(ma5) else last > ma5)
    g("收盤站上 20 日均線", "收盤 > MA20", f"{_f(last)} / MA20 {_f(ma20)}",
      None if pd.isna(ma20) else last > ma20)
    g("均線多頭排列", "MA5 > MA10 > MA20", f"{_f(ma5)} / {_f(ma10)} / {_f(ma20)}",
      None if any(pd.isna(x) for x in (ma5, ma10, ma20)) else ma5 > ma10 > ma20)

    g = _G(rows, "動能")
    rsi6, rsi14 = _rsi(c, 6), _rsi(c, 14)
    g("RSI(14) 偏多未過熱", "50 ≤ RSI(14) ≤ 80", _f(rsi14, 0),
      None if pd.isna(rsi14) else 50 <= rsi14 <= 80)
    dif, dea = _macd(c)
    g("MACD 動能翻正", "DIF > DEA（快線在慢線之上）",
      f"DIF {_f(dif.iloc[-1])} / DEA {_f(dea.iloc[-1])}",
      None if pd.isna(dif.iloc[-1]) else dif.iloc[-1] > dea.iloc[-1])
    bias20 = (last - ma20) / ma20 if pd.notna(ma20) and ma20 else None
    g("月線乖離未過大", "|收盤 − MA20| / MA20 ≤ 15%", _pct(bias20),
      None if bias20 is None else abs(bias20) <= 0.15)

    g = _G(rows, "量能")
    v_now = vol.iloc[-1]
    v_ma5, v_ma20 = vol.rolling(5).mean().iloc[-1], vol.rolling(20).mean().iloc[-1]
    g("今日放量", "今日量 > 20 日均量",
      f"{_f(v_now / 1000, 0)} / 均 {_f(v_ma20 / 1000, 0)} 張"
      if pd.notna(v_now) and pd.notna(v_ma20) else "—",
      None if pd.isna(v_now) or pd.isna(v_ma20) else v_now > v_ma20)
    g("量能轉強", "5 日均量 > 20 日均量", "—" if pd.isna(v_ma5) else f"{_f(v_ma5 / 1000, 0)} 張",
      None if pd.isna(v_ma5) or pd.isna(v_ma20) else v_ma5 > v_ma20)

    g = _G(rows, "慣性")
    g("突破近 10 日高 或 連漲 ≥ 3 日", "任一成立",
      f"距 10 日高 {_pct((last / hi10 - 1) if pd.notna(hi10) else None)} · 連漲 {consec_up} 日",
      None if pd.isna(hi10) else (last > hi10 or consec_up >= 3))
    g("未破近 10 日低、未連跌 ≥ 3 日", "兩者皆須成立",
      f"距 10 日低 {_pct((last / lo10 - 1) if pd.notna(lo10) else None)} · 連跌 {consec_dn} 日",
      None if pd.isna(lo10) else (last >= lo10 and consec_dn < 3))

    g = _G(rows, "籌碼")
    if chp is not None and not chp.empty:
        cc = chp.sort_values("date")
        net5 = (cc["foreign"] + cc["trust"] + cc["dealer"]).tail(5).sum()
        g("法人 5 日淨買超 > 0", "> 0（外資＋投信＋自營，單位：張）", f"{_f(net5, 0)} 張",
          None if pd.isna(net5) else net5 > 0)
    _active_etf_row(g, active_etf)

    g = _G(rows, "籌碼密集區")
    ccp = _ccp(c, vol)
    if ccp is not None:
        dist = last / ccp - 1
        g("站在 60 日成交量密集區之上", "距密集區價 ≥ +1%",
          f"密集區 {_f(ccp)} · 距 {_pct(dist)}", dist >= 0.01)

    g = _G(rows, "風險揭露")
    if pd.notna(rsi6):
        g("短線過熱", "RSI(6) > 85", _f(rsi6, 0), None,
          raw="⚠️ 命中" if rsi6 > 85 else "—")
    atr = (p["high"].astype(float) - p["low"].astype(float)).rolling(20).mean().iloc[-1]
    atr_pct = atr / last if pd.notna(atr) and last else None
    if atr_pct is not None:
        g("日內波動偏大", "ATR20 / 收盤 > 4%", _pct(atr_pct), None,
          raw="⚠️ 命中" if atr_pct > 0.04 else "—")
    return rows
