"""三軌體檢——把「長波段 / 價值 / 定存」三套判準逐條攤開成檢核表。

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


def summarize(rows: list[dict]) -> dict:
    """檢核列 → 白話「亮點 / 缺口 / 待確認」。**不加總分、不給 verdict**——
    只是把成立/未達/無資料的項目名挑出來，讓人一眼看到卡在哪。"""
    good = [r["項目"] for r in rows if r["狀態"].startswith("✅")]
    bad = [r["項目"] for r in rows if r["狀態"].startswith("❌")]
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
    roe, gm, fs = _get(r, "roe"), _get(r, "gross_margin"), _get(r, "f_score")
    ttm_eps, ryoy = _get(r, "ttm_eps"), _get(r, "rev_yoy")
    debt, cr = _get(r, "debt_ratio"), _get(r, "current_ratio")
    fcf, ocf = _get(r, "ttm_fcf"), _get(r, "ttm_ocf")
    rows: list[dict] = []

    g = _G(rows, "估值")
    g("現價有安全邊際", "現價 ≤ 便宜門檻（normalized EPS × PE P30）",
      f"現價 {_f(close)} / 門檻 {_f(cheap)}",
      None if close is None or cheap is None else close <= cheap)

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


def swing_checks(d: dict) -> list[dict]:
    """`d`：`_stock_data()` 的輸出（px / per / qf / rev / chips …）。"""
    q, rev, px = d.get("qf"), d.get("rev"), d.get("px")
    per, chp = d.get("per"), d.get("chips")
    rows: list[dict] = []

    g = _G(rows, "營收動能")
    if rev is not None and len(rev) >= 13:
        r = rev.sort_values("month").reset_index(drop=True)
        r["yoy"] = r["revenue"] / r["revenue"].shift(12) - 1.0
        r["mom"] = r["revenue"] / r["revenue"].shift(1) - 1.0
        yoy, yoy_p, mom = r["yoy"].iloc[-1], r["yoy"].iloc[-2], r["mom"].iloc[-1]
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
