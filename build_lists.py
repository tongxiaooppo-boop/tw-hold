"""screen 結果 → `data/derived/*_list.json`（Streamlit app 只讀這裡）。

M0.5 + M2。價值 / 定存兩清單來自 `build_factors.screen_all()`；長波段是 M1，這裡空。

## 季表 + 候補（PRD §6.1「月看季換」/ §3.2）

**成分每季凍結**——只在換股日（PRD §6.1：3/31、5/15、8/14、11/14，財報公告後）
重算 `holdings`（前 15、單一產業 ≤ 40%）。換股日輸出正式「新進 / 移除 + 原因 +
換手率」。期間內每次 rebuild：`holdings` 的**代號不動**，只用當下資料刷新每檔的
現價 / verdict / 買價；另外算 `candidates`——「若今天重選誰會進 / 誰會出」，
這是提示、**不進正式變動表**。

用法：
    python build_lists.py
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from build_factors import DERIVED, screen_all

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

N = 15                                        # 成分檔數（使用者裁決 2026-09-08）
INDUSTRY_CAP = 0.40                            # 單一產業上限（PRD §6.1 / §7.4）
REBALANCE_MD = [(3, 31), (5, 15), (8, 14), (11, 14)]   # 換股日（PRD §6.1）

#: 每個清單在 holdings / candidates 裡揭露的欄位（存在才帶）。
VALUE_COLS = ["name", "close", "verdict", "value_score", "f_score", "roe", "norm_pe",
              "norm_ey", "fcf_yield", "ev_ebit", "net_cash_to_mktcap", "gross_margin",
              "industry", "cheap_threshold", "valuation_ceiling", "upside_pct",
              "cyclical_peak_flag", "eps_basis_suspect", "pe_p30", "pe_p70", "pe_market",
              "buy_low", "buy_high", "buy_note", "reject_reason"]
DEPOSIT_COLS = ["name", "close", "verdict", "safety_score", "cur_yield", "yield_floor",
                "est_buy_price", "buy_low", "buy_high", "buy_note", "industry",
                "fill_rate", "ret3y_incl", "avg_yield_3y", "avg_yield_5y",
                "yield_pctile_5y", "div_years", "last_cash_dividend", "fcf_yield",
                "ann_vol", "roe", "payout_ratio_ttm", "cyclical_penalty",
                "debt_ratio", "reject_reason"]


def current_rebalance(asof: date) -> date:
    """asof 當下所屬期間的換股日（<= asof 的最近一個 REBALANCE_MD）。"""
    cands = [date(y, m, d) for y in (asof.year - 1, asof.year)
             for m, d in REBALANCE_MD if date(y, m, d) <= asof]
    return max(cands)


def select_composition(df: pd.DataFrame, score: str, has_industry: bool) -> list[str]:
    """過門檻 & 在宇宙內的，按 `score` 由高到低取前 N；單一產業滿 40%（N×0.4）就跳過。"""
    ok = df[df["passes"] & df["in_top500"]].sort_values(score, ascending=False)
    max_per_ind = int(N * INDUSTRY_CAP)        # 15 × 0.4 = 6
    picked: list[str] = []
    ind_n: dict[str, int] = {}
    for _, r in ok.iterrows():
        if len(picked) >= N:
            break
        ind = r.get("industry") or "未分類"
        if has_industry and ind_n.get(ind, 0) >= max_per_ind:
            continue
        picked.append(str(r["ticker"]))
        ind_n[ind] = ind_n.get(ind, 0) + 1
    return picked


def _cell(v):
    if v is None:
        return None
    if not isinstance(v, str):
        try:
            if pd.isna(v):
                return None
        except (TypeError, ValueError):
            pass
    if hasattr(v, "item"):                     # numpy 純量 → Python 原生型別
        v = v.item()
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return round(v, 4)
    return v


def _rows_for(df: pd.DataFrame, tickers: list[str], score: str,
              cols: list[str]) -> list[dict]:
    """取指定 tickers 的列（用當下資料），按 `score` 由高到低。清單裡沒有的 ticker
    給一個 stub（下季會被移除）。"""
    di = df.set_index(df["ticker"].astype(str))
    keep = [c for c in cols if c in df.columns]
    out = []
    for tk in tickers:
        if tk not in di.index:
            out.append({"ticker": tk, "verdict": "已不在清單資料中（下季移除）"})
            continue
        r = di.loc[tk]
        out.append({"ticker": tk, **{c: _cell(r[c]) for c in keep}})
    out.sort(key=lambda d: (d.get(score) is None, -(d.get(score) or 0)))
    return out


def _rebalance_changes(new_tks: list[str], prev_tks: list[str],
                       df: pd.DataFrame) -> dict:
    """換股日的正式變動：新進 / 移除（每檔原因）/ 換手率。"""
    added = sorted(t for t in new_tks if t not in prev_tks)
    removed = sorted(t for t in prev_tks if t not in new_tks)
    di = df.set_index(df["ticker"].astype(str))
    rem = []
    for t in removed:
        if t not in di.index:
            why = "掉出可投資宇宙或資料缺"
        elif not bool(di.loc[t, "passes"]):
            why = f"觸發硬門檻：{di.loc[t, 'reject_reason']}"
        else:
            why = f"分數掉出前 {N}"
        rem.append({"ticker": t, "reason": why})
    turnover = (len(added) + len(removed)) / (2 * N) if prev_tks else 1.0
    return {"added": added, "removed": rem, "turnover_pct": round(turnover, 3)}


def _candidates(df: pd.DataFrame, score: str, holding_tks: list[str],
                has_industry: bool) -> dict:
    """若今天就換股，誰會進 / 誰會出（提示，不進正式變動表）。"""
    today = select_composition(df, score, has_industry)
    di = df.set_index(df["ticker"].astype(str))
    out = []
    for t in holding_tks:
        if t in today:
            continue
        if t not in di.index or not bool(di.loc[t, "passes"]):
            why = "已觸發硬門檻" if t in di.index else "資料缺"
        else:
            why = "分數掉出前 15"
        out.append({"ticker": t, "reason": why})
    return {
        "likely_in": sorted(t for t in today if t not in holding_tks),
        "likely_out": out,
        "as_if_rebalanced_today": today,
    }


def _diff_simple(name: str, current: list[dict]) -> dict:
    prev_p = DERIVED / f"{name}_list.json"
    prev_tk: set[str] = set()
    if prev_p.exists():
        try:
            prev_tk = {h["ticker"] for h in
                       json.loads(prev_p.read_text(encoding="utf-8")).get("holdings", [])}
        except Exception:
            pass
    cur_tk = {h["ticker"] for h in current}
    return {"added": sorted(cur_tk - prev_tk), "removed": sorted(prev_tk - cur_tk)}


def _load_prev(name: str) -> dict:
    p = DERIVED / f"{name}_list.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(name: str, payload: dict) -> None:
    (DERIVED / f"{name}_list.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    n = len(payload.get("holdings") or payload.get("candidates_pool") or [])
    tag = ("，本期凍結" if payload.get("_meta", {}).get("frozen")
           else "，候補池" if "candidates_pool" in payload else "，換股日重算")
    print(f"  → data/derived/{name}_list.json　({n} 檔{tag})")


def _build(name: str, df: pd.DataFrame, score: str, cols: list[str],
           meta: dict, has_industry: bool, asof: date) -> dict:
    prev = _load_prev(name)
    period = current_rebalance(asof).isoformat()
    prev_period = prev.get("_meta", {}).get("period")
    prev_tks = [h["ticker"] for h in prev.get("holdings", [])]

    frozen = bool(prev_period == period and prev_tks)
    if frozen:
        holding_tks = prev_tks
        changes = prev.get("changes", {"added": [], "removed": [], "turnover_pct": 0.0})
    else:
        holding_tks = select_composition(df, score, has_industry)
        # 舊清單存在、但沒有 period 欄（M2 前的 30 檔版）→ 格式轉換，不算換股變動
        if prev and prev_period is None:
            changes = {"added": [], "removed": [], "turnover_pct": 0.0,
                       "note": "季表格式轉換——非換股變動"}
        else:
            changes = _rebalance_changes(holding_tks, prev_tks, df)

    return {
        "_meta": {**meta, "period": period, "frozen": frozen,
                  "n_target": N, "industry_cap": INDUSTRY_CAP},
        "holdings": _rows_for(df, holding_tks, score, cols),
        "candidates": _candidates(df, score, holding_tks, has_industry),
        "changes": changes,
    }


def main() -> int:
    r = screen_all()
    ctx = r["context"]
    asof = date.fromisoformat(ctx["trading_date"]) if ctx.get("trading_date") \
        else date.today()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    has_ind = ctx.get("has_industry", False)
    meta = {
        "trading_date": ctx["trading_date"],
        "rebuilt_at": now,
        "bundle_schema": ctx["bundle_schema"],
        "universe_filtered": ctx["universe_filtered"],
        "note": ctx["universe_note"],
        "u1b_pending": not ctx["has_prices"],
        "has_pe_bands": ctx.get("has_pe_bands", False),
        "has_fill_rate": ctx.get("has_fill_rate", False),
        "has_industry": has_ind,
        "g2_note": ctx.get("g2_note"),
    }
    DERIVED.mkdir(parents=True, exist_ok=True)

    from build_factors import detect_unhandled_splits
    split_warn = detect_unhandled_splits()
    for w in split_warn:
        print(f"  ⚠ 疑似未還原分割：{w}")
    if split_warn:
        meta["split_warning"] = "；".join(split_warn)

    _write("value", _build("value", r["value"], "value_score", VALUE_COLS,
                           meta, has_ind, asof))
    _write("deposit", _build("deposit", r["deposit"], "safety_score", DEPOSIT_COLS,
                             {**meta, "warning":
                              "定存線已知偏誤：(1) 金控/金融股被『EPS 近4季非全正』刷掉"
                              "——FinMind 對金融業報不同 XBRL type、EPS/淨利是 NaN"
                              "（PRD §7 / 實驗 B）；(2) 填息率只涵蓋有未還原股價的 ~500 檔。"},
                             has_ind, asof))
    pool = r.get("pool", [])
    pool_prev = {c["ticker"] for c in _load_prev("swing").get("candidates_pool", [])}
    pool_cur = {c["ticker"] for c in pool}
    _write("swing", {
        "_meta": {**meta, "pool_note": ctx.get("pool_note"),
                  "disclaimer": "🔴 這個區間沒有回測支撐——這是風控算術不是驗證過的買點。"
                                "只回答「這個進場點承擔多少風險」，不回答「會不會賺」。"
                                "候選池 = 狀態成立的標的 + 支持/反對證據，**不是推薦清單**，"
                                "不給 verdict、不給買價、不排名次，買賣由你決定。每週重算。"},
        "holdings": [],
        "candidates_pool": pool,
        "changes": {"added": sorted(pool_cur - pool_prev),
                    "removed": sorted(pool_prev - pool_cur)},
    })

    (DERIVED / "_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → data/derived/_meta.json　trading_date {meta['trading_date']}"
          f"　本期換股日 {current_rebalance(asof).isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
