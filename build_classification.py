"""產 `data/derived/stock_class.json`＋`data/derived/class_history.parquet`（估值分類，類型＋狀態）。

依據：`D:\\g\\claude\\估值定義定案草案.md` §8.2；規格見 `screener/classify.py` 檔頭。
本檔只負責「接真實資料」，判斷全在 screener/ 的純函式裡。

步驟：
1. 讀 `reference.loader.load_quarterly()`（季度面板）、`data/upstream/revenue.parquet`（月營收長表）、
   `data/upstream/fundamentals/universe.parquet`（母體＝universe 全部列，不只 in_universe）。
2. `assemble_inputs`（純函式）：現金流累計→單季、逐檔算 OROA 振幅／資產強度後做**全體**橫斷面分位、
   營收指數（全市場／產業／排除自己）、beta、同步度、g3，組成 {ticker: ClassInputs}。
   eps_nc／eps_f4 尚未實作 → None。
3. `classify.classify` 逐檔（單檔例外只記錄略過）→ 讀既有 class_history.parquet → `apply_hysteresis`
   → 寫 JSON 與 history。整批 0 檔 → 不寫檔、exit 1。

用法：
    python build_classification.py                         # 全市場，寫預設路徑
    python build_classification.py --tickers 2330,2317     # 只輸出這幾檔（橫斷面仍用全體算）
    python build_classification.py --out x.json --no-history
    python build_classification.py --asof 2026-06-30       # 預設＝資料內最新季
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "app"))

from screener import classify as cl  # noqa: E402
from screener import quarterly_prep as qp  # noqa: E402
from screener import rev_index as ri  # noqa: E402
from screener import rev_momentum as rm  # noqa: E402

OUT_JSON = REPO / "data" / "derived" / "stock_class.json"
OUT_HISTORY = REPO / "data" / "derived" / "class_history.parquet"
UNIVERSE = REPO / "data" / "upstream" / "fundamentals" / "universe.parquet"
REVENUE = REPO / "data" / "upstream" / "revenue.parquet"


def _t(code) -> str:
    """與 app/bundle_data._t 同規則：去空白、去 .TW/.TWO 後綴 → 裸代號。"""
    return str(code).strip().split(".")[0]


def _json_safe(v):
    """numpy／Timestamp 轉 Python 原生；NaN／Inf／NaT → None。"""
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if (np.isnan(f) or np.isinf(f)) else f
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_json_safe(x) for x in v]
    if isinstance(v, np.ndarray):
        return [_json_safe(x) for x in v.tolist()]
    return str(v)


def _prep_monthly(monthly_rev: pd.DataFrame) -> pd.DataFrame:
    """月營收長表正規化：裸代號、month→月初 Timestamp、(ticker, month) 去重（留最後一筆）。"""
    d = monthly_rev[["ticker", "month", "revenue"]].copy()
    d["ticker"] = d["ticker"].map(_t)
    d["month"] = pd.to_datetime(d["month"]).dt.to_period("M").dt.to_timestamp()
    d["revenue"] = d["revenue"].astype(float)
    return d.drop_duplicates(["ticker", "month"], keep="last").reset_index(drop=True)


def assemble_inputs(quarterly: pd.DataFrame, monthly_rev: pd.DataFrame, universe: pd.DataFrame,
                    tickers: list[str] | None = None, asof: pd.Timestamp | None = None,
                    skipped: dict[str, str] | None = None) -> dict[str, cl.ClassInputs]:
    """季度面板＋月營收＋universe → {ticker: ClassInputs}（純函式，不讀檔）。

    母體＝universe 的 ticker 且在季度面板有至少一列者（橫斷面分位、產業指數都用這個母體；
    全市場營收指數用 monthly_rev 全部）。tickers 只限制**輸出**哪幾檔。
    asof：季度面板只留 period_end ≤ asof，月營收只留 month ≤ asof；預設不截。
    skipped：傳入 dict 時，把單檔略過原因（ticker → 原因）寫進去。
    """
    skipped = skipped if skipped is not None else {}
    q = quarterly.copy()
    q["ticker"] = q["ticker"].map(_t)
    q["period_end"] = pd.to_datetime(q["period_end"])
    pe = q["period_end"]
    q = q[pe.dt.month.isin([3, 6, 9, 12]) & pe.dt.is_month_end]          # 非季末列丟掉
    q = q.drop_duplicates(["ticker", "period_end"], keep="last")
    if asof is not None:
        q = q[q["period_end"] <= pd.Timestamp(asof)]
    q = qp.to_single_quarter_cashflow(q)

    uni = universe.copy()
    uni["ticker"] = uni["ticker"].map(_t)
    uni = uni.drop_duplicates("ticker").set_index("ticker")
    have_q = set(q["ticker"])
    pop = [t for t in uni.index if t in have_q]
    for t in uni.index:
        if t not in have_q:
            skipped[t] = "季度面板無資料"

    for c in cl.QUARTER_COLS:
        if c not in q.columns:
            q[c] = np.nan
    qcols = list(cl.QUARTER_COLS) + [c for c in cl.QUARTER_COLS_OPTIONAL if c in q.columns]
    by_t = {t: g.set_index("period_end")[qcols].astype(float).sort_index()
            for t, g in q[q["ticker"].isin(pop)].groupby("ticker")}

    m = _prep_monthly(monthly_rev)
    if asof is not None:
        m = m[m["month"] <= pd.Timestamp(asof)]
    market = ri.build_market_index(m)["ttm_yoy"] if len(m) else pd.Series(dtype=float)
    ind_of = {t: qp.normalize_industry(uni.loc[t, "industry"]) if "industry" in uni.columns else None
              for t in pop}
    pop_set = set(pop)
    m_pop = m[m["ticker"].isin(pop_set)]
    ind_map = {t: v for t, v in ind_of.items() if v is not None}
    ind_idx = (ri.build_industry_index(m_pop, ind_map, min_members=5)
               if len(m_pop) and ind_map else pd.DataFrame(columns=["industry", "month"]))
    m_by_t = {t: g.set_index("month")["revenue"].sort_index() for t, g in m.groupby("ticker")}
    m_rows_by_t = {t: g for t, g in m_pop.groupby("ticker")}

    # 橫斷面原始值
    raw: dict[str, dict[str, float]] = {}
    for t in pop:
        try:
            qt = by_t[t]
            raw[t] = {"amp": cl.oroa_amplitude(cl.oroa_series(qt)), **cl.asset_intensity(qt)}
        except Exception as e:  # noqa: BLE001
            raw[t] = {"amp": np.nan, "ta_rev": np.nan, "capex_rev": np.nan}
            skipped[t] = f"橫斷面原始值失敗：{type(e).__name__}"
    pct = {k: cl.cross_section_pct(pd.Series({t: raw[t][k] for t in pop}, dtype=float))
           for k in ("amp", "ta_rev", "capex_rev")}

    want = pop if tickers is None else [t for t in (_t(x) for x in tickers) if t in pop_set]
    if tickers is not None:
        for t in (_t(x) for x in tickers):
            if t not in pop_set:
                skipped.setdefault(t, "不在母體（universe 或季度面板無此檔）")
    out: dict[str, cl.ClassInputs] = {}
    for t in want:
        try:
            ms = m_by_t.get(t, pd.Series(dtype=float))
            stock_yoy = ri.stock_ttm_yoy(ms) if len(ms) else pd.Series(dtype=float)
            ind = ind_of.get(t)
            if ind is not None and len(ind_idx) and t in m_rows_by_t:
                ind_yoy = ri.industry_index_excluding_self(ind_idx, m_rows_by_t[t], t, ind)
            else:
                ind_yoy = pd.Series(dtype=float)
            g3 = float("nan")
            if len(ms):
                gm = rm.momentum_metrics(ms)["g3"]
                g3 = float(gm.iloc[-1]) if len(gm) else float("nan")
            grp = qp.industry_group(uni.loc[t, "industry"]) if "industry" in uni.columns else qp.GROUP_OTHER
            out[t] = cl.ClassInputs(
                ticker=t, industry_group=grp, quarters=by_t[t],
                oroa_amp_pct=float(pct["amp"].get(t, np.nan)),
                asset_ta_rev_pct=float(pct["ta_rev"].get(t, np.nan)),
                asset_capex_rev_pct=float(pct["capex_rev"].get(t, np.nan)),
                rev_beta=ri.revenue_beta(stock_yoy, market),
                ind_sync=ri.industry_sync(stock_yoy, ind_yoy),
                industry_name=qp.normalize_industry(uni.loc[t, "industry"]) if "industry" in uni.columns else "",
                stock_rev_ttm_yoy=stock_yoy, market_rev_ttm_yoy=market,
                industry_rev_ttm_yoy=ind_yoy, g3=g3, eps_nc=None, eps_f4=None)
        except Exception as e:  # noqa: BLE001
            skipped[t] = f"組輸入失敗：{type(e).__name__}: {e}"
    return out


MIN_COVERAGE = 0.95   # 新季財報涵蓋 universe 的比例門檻；未達 → 還在公布期，不分型（避免用殘缺的橫斷面分位）

# 季末月 → 該季的換股日（月, 日, 年位移）。必須與 build_lists.REBALANCE_MD（3/31、5/15、8/14、11/14）一致；
# tests 有一致性檢查。分型季更跟價值／定存的季換股同一天上線（使用者 2026-11-01 指定）。
REBALANCE_FOR_QUARTER = {3: (5, 15, 0), 6: (8, 14, 0), 9: (11, 14, 0), 12: (3, 31, 1)}


def rebalance_date_for(period_end) -> pd.Timestamp:
    """某季季末對應的換股日（財報法定期限）。"""
    pe = pd.Timestamp(period_end)
    m, d, dy = REBALANCE_FOR_QUARTER[pe.month]
    return pd.Timestamp(year=pe.year + dy, month=m, day=d)


def new_quarter_ready(quarterly: pd.DataFrame, universe: pd.DataFrame, current_asof,
                      today=None, min_coverage: float = MIN_COVERAGE) -> tuple[bool, str, pd.Timestamp | None]:
    """季更閘門（純函式）：回傳 (要不要重算, 原因, 最新季末)。

    三條都成立才 True：
      1. 最新季末 > 目前快照的 asof（current_asof 為 None＝沒有快照，視為成立）；
      2. today ≥ 該季換股日（today 為 None 則不檢查此條，測試／手動用）；
      3. 該季已有財報的 universe 檔數 ≥ min_coverage × universe 檔數。
    任一不成立 → False 並給原因（下次 rebuild 再看）。換股日已過但涵蓋率不足時原因會明講，
    此時卡片會一直顯示「分類過期」，要人工看是哪些公司沒公布。
    """
    q = quarterly.copy()
    q["ticker"] = q["ticker"].map(_t)
    q["period_end"] = pd.to_datetime(q["period_end"])
    if q.empty:
        return False, "季度面板為空", None
    latest = q["period_end"].max()
    if current_asof is not None and latest <= pd.Timestamp(current_asof):
        return False, f"快照已是最新季（{pd.Timestamp(current_asof):%Y-%m-%d}）", latest
    rb = rebalance_date_for(latest)
    if today is not None and pd.Timestamp(today).normalize() < rb:
        return False, f"{latest:%Y-%m-%d} 季未到換股日 {rb:%Y-%m-%d}，等價值／定存一起換", latest
    uni = {_t(x) for x in universe["ticker"]}
    have = set(q.loc[q["period_end"] == latest, "ticker"]) & uni
    cov = len(have) / max(len(uni), 1)
    if cov < min_coverage:
        return False, f"{latest:%Y-%m-%d} 季財報涵蓋 {cov:.1%} < {min_coverage:.0%}，不分型", latest
    return True, f"{latest:%Y-%m-%d} 季財報涵蓋 {cov:.1%}，換股日 {rb:%Y-%m-%d}", latest


def _empty_history() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in cl.HISTORY_COLS})


def _load_history(path: Path) -> pd.DataFrame:
    if not path.exists():
        return _empty_history()
    h = pd.read_parquet(path)
    if any(c not in h.columns for c in cl.HISTORY_COLS):
        return _empty_history()
    h = h[list(cl.HISTORY_COLS)].copy()
    h["decided_at"] = pd.to_datetime(h["decided_at"])
    return h


def main(argv: list[str] | None = None) -> int:
    import argparse
    import datetime as _dt
    import time

    ap = argparse.ArgumentParser(description="產 data/derived/stock_class.json 與 class_history.parquet")
    ap.add_argument("--tickers", default=None, help="只輸出這些代號（逗號分隔）；橫斷面仍用全體")
    ap.add_argument("--out", default=None, help="JSON 輸出路徑（預設 data/derived/stock_class.json）")
    ap.add_argument("--no-history", action="store_true", help="不讀不寫 class_history.parquet（遲滯視為首次）")
    ap.add_argument("--asof", default=None, help="分類基準季末（預設＝資料內最新季）")
    ap.add_argument("--if-new-quarter", action="store_true",
                    help="季更模式（CI 用）：只有「出現比快照更新的季、已到該季換股日、且財報涵蓋率 ≥ 95%%」才重算，否則直接 exit 0 不動檔")
    args = ap.parse_args(argv)

    t0 = time.time()
    out_path = Path(args.out) if args.out else OUT_JSON
    hist_path = OUT_HISTORY if not args.out else out_path.with_name("class_history.parquet")
    tickers = [x.strip() for x in args.tickers.split(",") if x.strip()] if args.tickers else None
    if tickers and not args.out:
        print("警告：--tickers 且未指定 --out，會用部分名單覆寫預設 stock_class.json", file=sys.stderr)

    if not UNIVERSE.exists() or not REVENUE.exists():
        print("錯誤：找不到 universe.parquet 或 revenue.parquet，中止且不覆寫。", file=sys.stderr)
        return 1
    from reference.loader import load_quarterly
    quarterly = load_quarterly()
    monthly = pd.read_parquet(REVENUE)
    universe = pd.read_parquet(UNIVERSE)
    if args.if_new_quarter:
        cur = None
        if out_path.exists():
            try:
                cur = pd.Timestamp(json.loads(out_path.read_text(encoding="utf-8")).get("asof"))
            except Exception:  # noqa: BLE001 — 快照壞了就當沒有，涵蓋率夠就重建
                cur = None
        from zoneinfo import ZoneInfo
        today = _dt.datetime.now(ZoneInfo("Asia/Taipei")).date()
        ok, why, _ = new_quarter_ready(quarterly, universe, cur, today=today)
        print(("季更：重算 — " if ok else "季更：略過 — ") + why)
        if not ok:
            return 0
    asof = pd.Timestamp(args.asof) if args.asof else pd.Timestamp(quarterly["period_end"].max())

    skipped: dict[str, str] = {}
    inputs = assemble_inputs(quarterly, monthly, universe, tickers=tickers, asof=asof, skipped=skipped)
    names = {_t(r["ticker"]): r for r in universe.to_dict("records")}
    t_assemble = time.time() - t0

    history = _empty_history() if args.no_history else _load_history(hist_path)
    results: list[tuple[str, cl.Classification, cl.Classification]] = []
    for t, inp in inputs.items():
        try:
            raw = cl.classify(inp)
            h = history[(history["ticker"] == t) & (history["decided_at"] < pd.Timestamp(raw.metrics["asof"]))]
            h = h.sort_values("decided_at")
            final = cl.apply_hysteresis(raw, h)
            results.append((t, raw, final))
        except Exception as e:  # noqa: BLE001
            skipped[t] = f"分類失敗：{type(e).__name__}: {e}"

    if not results:
        print("錯誤：整批 0 檔分類成功，不寫檔。", file=sys.stderr)
        for t, why in list(skipped.items())[:5]:
            print(f"  略過 {t}：{why}", file=sys.stderr)
        return 1

    stocks, new_rows = [], []
    for t, raw, final in results:
        info = names.get(t, {})
        decided = pd.Timestamp(final.metrics["asof"])
        stocks.append(_json_safe({
            "ticker": t, "name": info.get("stock_name"), "industry": info.get("industry"),
            "industry_group": inputs[t].industry_group, "type": final.type,
            "display_type": cl.display_type(final), "state": final.state, "subtags": final.subtags,
            "why": final.why, "reasons_degrade": final.reasons_degrade, "metrics": final.metrics,
            "rule_version": final.rule_version, "decided_at": decided,
        }))
        new_rows.append({
            "ticker": t, "decided_at": decided,
            "candidate_type": final.metrics["candidate_type"], "final_type": final.type,
            "switched": bool(final.metrics["switched"]),
            "candidate_states": cl.STATE_SEP.join(raw.state),
            "final_states": cl.STATE_SEP.join(final.state)})

    payload = {"asof": asof.date().isoformat(), "rule_version": cl.RULE_VERSION,
               "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
               "count": len(stocks), "stocks": stocks}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")

    if not args.no_history:
        done = {(r["ticker"], r["decided_at"]) for r in new_rows}
        keep = history[[(a, b) not in done for a, b in zip(history["ticker"], history["decided_at"])]]
        hist_new = pd.concat([keep, pd.DataFrame(new_rows)], ignore_index=True)
        hist_new = hist_new.sort_values(["ticker", "decided_at"]).reset_index(drop=True)
        hist_new["switched"] = hist_new["switched"].astype(bool)
        hist_path.parent.mkdir(parents=True, exist_ok=True)
        hist_new[list(cl.HISTORY_COLS)].to_parquet(hist_path, index=False)

    # 摘要
    print(f"asof={asof.date()}  處理 {len(results)} 檔，略過 {len(skipped)} 檔  "
          f"（組輸入 {t_assemble:.1f}s，總 {time.time() - t0:.1f}s）")
    stale = sum(1 for _, _, f in results if pd.Timestamp(f.metrics["asof"]) < asof)
    if stale:
        print(f"其中 {stale} 檔最新季早於 asof（以自身最新季判定）")
    for t, why in list(skipped.items())[:5]:
        print(f"  略過 {t}：{why}")
    fin = [f for _, _, f in results]
    print("類型：", dict(Counter(cl.TYPE_ZH[f.type] for f in fin)))
    print("顯示類型：", dict(Counter(cl.display_type(f) for f in fin)))
    print("狀態：", dict(Counter(s for f in fin for s in f.state)))
    print("副標：", dict(Counter(s for f in fin for s in f.subtags)))
    if tickers:
        for t, _, f in results:
            info = names.get(t, {})
            print(f"{t} {info.get('stock_name', '')} → {cl.display_type(f)}（{cl.TYPE_ZH[f.type]}）"
                  f"/ {'、'.join(f.state) or '無狀態'} / {'、'.join(f.subtags) or '無副標'}")
            for w in f.why:
                print(f"    - {w}")
            for d in f.reasons_degrade:
                print(f"    ! 降級：{d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
