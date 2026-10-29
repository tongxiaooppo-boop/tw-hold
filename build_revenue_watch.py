"""產 `data/derived/revenue_watch.json`（「月營收」分頁）。框架 2026-10-29 由 Opus 定。

步驟（Cline 照這個順序實作，不准改步驟與輸出格式）：
1. `bundle_data.ensure_assets()`；讀 `data/upstream/fundamentals/universe.parquet`，
   universe ＝ `in_mktcap500` 為真的 ticker（裸代號）。檔案不在 → 印錯誤、回 1、不覆寫舊 JSON。
2. **一次**把 bundle 的 prices_adj / per / revenue / income / balance / cashflow 讀進記憶體，
   用 `_install_preloaded_reader()` 換掉 `bundle_data._read`，之後照常呼叫
   `bundle_data.prices(code)`、`per_history`、`revenue`、`financials`——正規化沿用原函式，
   但不再每檔重讀 parquet（500 檔 × 6 張表逐檔讀會很慢）。
3. 今天收盤：`scripts/pcf_fetchers.fetch_twse_closes(codes)` 拿上市收盤（上櫃抓不到就算了，
   沿用 bundle 最後收盤）；比 bundle 最後一天新才 append 到 px 尾端再算均線與估值。
4. 對 `revenue_watch.periods_to_show(今天台北日期)` 的每一期：
   - 有 `data/revenue_mops/<month>.parquet` → source="mops"，營收數字、note、
     first_seen_at、revised 都取它；has_first_seen=True。
   - 沒有 → source="bundle"，從 bundle revenue 長表取該月；上月／去年同月從同一張長表找；
     note=""、first_seen_at=None、revised=False；has_first_seen=False。
   - 只處理 universe 內、該月有營收的公司。
   - hist ＝ bundle_data.revenue(code)，若沒有該月就把該月（來自 mops）append 上去；
     再**截到 ≤ 該月**（算上一期時不能看到更新的月份）。
   - 估值：`valuation.estimate(qf, hist, px, per)`，qf＝`factors.factors.quarterly_factors(fin)`；
     任何例外 → 該列 est_ok=False、est_reason="計算失敗：<例外類型>"，**不中斷整批**。
   - 用 `revenue_watch.make_row` 組列。
5. 寫 JSON（ensure_ascii=False、indent=None、浮點不四捨五入）。
   任一期 rows 為 0 不算失敗（例：月初第一晚）。

用法：
    python build_revenue_watch.py              # 寫 data/derived/revenue_watch.json
    python build_revenue_watch.py --limit 20   # 只算前 20 檔（本機試跑）
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "app"))

OUT = REPO / "data" / "derived" / "revenue_watch.json"
MOPS_DIR = REPO / "data" / "revenue_mops"


def _maybe_float(v) -> float | None:
    """任何可轉 float 的值 → float；缺值／NaN → None。"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _rev_at(hist: pd.DataFrame, period: pd.Period) -> float | None:
    """從月營收長表 [month, revenue] 取某月營收；缺 → None。"""
    if hist is None or hist.empty or "month" not in hist.columns or "revenue" not in hist.columns:
        return None
    ts = period.to_timestamp()
    m = hist[hist["month"] == ts]["revenue"]
    if m.empty:
        return None
    return _maybe_float(m.iloc[0])


def _cum(hist: pd.DataFrame, period: pd.Period) -> float | None:
    """該曆年截至 `period` 的累計營收；無任何該年月份 → None。"""
    if hist is None or hist.empty or "month" not in hist.columns or "revenue" not in hist.columns:
        return None
    ts = period.to_timestamp()
    seg = hist[(hist["month"].dt.year == period.year) & (hist["month"] <= ts)]
    if seg.empty:
        return None
    return _maybe_float(seg["revenue"].sum())


def _bundle_last_date() -> str:
    """bundle 現價／均線用的最後收盤日（prices_adj 全表 date 最大）。"""
    p = REPO / "data" / "upstream" / "prices_adj.parquet"
    if not p.exists():
        return ""
    try:
        d = pd.read_parquet(p, columns=["date"])
        return pd.Timestamp(d["date"].max()).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return ""


def _json_safe(v):
    """numpy scalar / Timestamp 轉 Python 原生；NaN／Inf → None。"""
    import numpy as np
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if (pd.isna(f) or f in (float("inf"), float("-inf"))) else f
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    return v


def _install_preloaded_reader() -> None:
    """把 bundle_data._read 換成「第一次整檔讀進記憶體、之後按 ticker 切片」的版本。
    行為（回傳欄位、suffixed 比對 .TW/.TWO/裸代號、缺欄時只回存在的欄）必須與原 _read 相同。"""
    import bundle_data

    cache: dict[str, pd.DataFrame] = {}

    def preloaded(name: str, code: str, suffixed: bool,
                  columns: list[str] | None = None) -> pd.DataFrame:
        p = bundle_data._dest(name)
        if not p.exists():
            return pd.DataFrame(columns=columns or [])
        c = bundle_data._t(code)
        vals = [f"{c}.TW", f"{c}.TWO", c] if suffixed else [c]
        full = cache.get(name)
        if full is None:
            full = pd.read_parquet(p)
            cache[name] = full
        if columns:   # 舊 schema 缺新欄時不炸：只回存在的欄（呼叫端用 .get／有則用）
            have = set(full.columns)
            columns = [col for col in columns if col in have]
        df = full[full["ticker"].isin(vals)]
        if columns is not None:
            df = df[columns]
        return df.reset_index(drop=True)

    bundle_data._read = preloaded


def main(argv: list[str] | None = None) -> int:
    import argparse
    import time

    import bundle_data as bd
    from factors.factors import quarterly_factors
    import valuation as va
    from screener import revenue_watch as rw
    from scripts.pcf_fetchers import fetch_twse_closes

    ap = argparse.ArgumentParser(description="產 data/derived/revenue_watch.json")
    ap.add_argument("--limit", type=int, default=None, help="只算前 N 檔（本機試跑）")
    args = ap.parse_args(argv)

    t_start = time.time()
    bd.ensure_assets()

    uni_path = REPO / "data" / "upstream" / "fundamentals" / "universe.parquet"
    if not uni_path.exists():
        print("錯誤：找不到 universe.parquet，中止且不覆寫舊 JSON。", file=sys.stderr)
        return 1
    uni = pd.read_parquet(uni_path)
    in500 = uni[uni["in_mktcap500"] == True]  # noqa: E712
    codes = [bd._t(str(t)) for t in in500["ticker"]]
    uni_by_code = {bd._t(str(r["ticker"])): r for r in uni.to_dict("records")}
    n_universe = int(len(in500))
    asof = pd.Timestamp(uni["asof_date"].iloc[0]).date().isoformat()

    if args.limit:
        codes = codes[: args.limit]

    _install_preloaded_reader()

    now = _dt.datetime.now(ZoneInfo("Asia/Taipei"))
    today = pd.Timestamp(now)

    # 今天收盤（上市）；上櫃抓不到就算了，沿用 bundle 最後收盤
    closes: dict[str, float] = {}
    closes_day = ""
    try:
        closes, closes_day = fetch_twse_closes(codes)
    except Exception:  # noqa: BLE001
        closes, closes_day = {}, ""

    price_date = closes_day or _bundle_last_date()

    out_periods = []
    for month in rw.periods_to_show(today):
        t0 = time.time()
        month_s = month.strftime("%Y-%m")
        mops_path = MOPS_DIR / f"{month_s}.parquet"
        source = "mops" if mops_path.exists() else "bundle"
        has_first_seen = mops_path.exists()

        mops_by_code: dict[str, float] = {}
        mops_meta: dict[str, dict] = {}
        if has_first_seen:
            for r in pd.read_parquet(mops_path).to_dict("records"):
                c = bd._t(str(r.get("code") or r.get("ticker")))
                rev = _maybe_float(r.get("revenue"))
                if rev is None:
                    continue
                mops_by_code[c] = rev
                mops_meta[c] = r

        cur_ts = pd.Timestamp(month.to_timestamp())
        rows = []
        for code in codes:
            u = uni_by_code.get(code)
            if u is None:
                continue
            hist = bd.revenue(code)
            if hist is None or hist.empty:
                hist = pd.DataFrame({"month": pd.Series(dtype="datetime64[ns]"),
                                     "revenue": pd.Series(dtype="float64")})
            else:
                hist = hist.copy()

            if source == "mops":
                rev = mops_by_code.get(code)
                if rev is None:
                    continue
                m = mops_meta[code]
                prev_rev = _maybe_float(m.get("revenue_prev_month"))
                last_year_rev = _maybe_float(m.get("revenue_last_year"))
                cum = _maybe_float(m.get("revenue_cum"))
                cum_last_year = _maybe_float(m.get("revenue_cum_last_year"))
                note = m.get("note")
                first_seen_at = m.get("first_seen_at")
                revised = bool(m.get("revised", False))
            else:
                rev = _rev_at(hist, month)
                if rev is None:
                    continue
                prev_rev = _rev_at(hist, month - 1)
                last_year_rev = _rev_at(hist, month - 12)
                cum = _cum(hist, month)
                cum_last_year = _cum(hist, month - 12)
                note = None
                first_seen_at = None
                revised = False

            # hist 截到 ≤ 該月；來自 mops 且 bundle 缺該月時 append
            if not (hist["month"] == cur_ts).any():
                hist = pd.concat([hist, pd.DataFrame({"month": [cur_ts], "revenue": [rev]})],
                                 ignore_index=True)
            hist = hist[hist["month"] <= cur_ts].sort_values("month").reset_index(drop=True)

            px = bd.prices(code)
            close = closes.get(code)
            if close is not None and closes_day:
                close_ts = pd.Timestamp(closes_day)
                if px is None or px.empty:
                    px = pd.DataFrame({"date": [close_ts], "close": [float(close)]})
                elif close_ts > pd.Timestamp(px["date"].max()):
                    px = pd.concat([px, pd.DataFrame({"date": [close_ts],
                                                      "close": [float(close)]})],
                                   ignore_index=True).sort_values("date").reset_index(drop=True)
            ma = rw.ma_status(px)

            base = {
                "code": code,
                "name": u.get("stock_name"),
                "industry": u.get("industry"),
                "market_cap": u.get("market_cap"),
                "revenue": rev,
                "revenue_prev_month": prev_rev,
                "revenue_last_year": last_year_rev,
                "revenue_cum": cum,
                "revenue_cum_last_year": cum_last_year,
                "note": note,
                "first_seen_at": first_seen_at,
                "revised": revised,
            }

            try:
                fin = bd.financials(code)
                qf = quarterly_factors(fin)
                per = bd.per_history(code)
                est = va.estimate(qf, hist, px, per)
                val = rw.valuation_fields(est, ma.get("price"))
            except Exception as e:  # noqa: BLE001
                val = rw.valuation_fields({"ok": False, "reason": f"計算失敗：{type(e).__name__}"}, None)

            rows.append(rw.make_row(base, hist, month, ma, val))

        n_ok = sum(1 for r in rows if r.get("est_ok"))
        out_periods.append({
            "month": month_s,
            "pub_month": (month + 1).strftime("%Y-%m"),
            "source": source,
            "has_first_seen": has_first_seen,
            "n_universe": n_universe,
            "n_published": len(rows),
            "rows": rows,
        })
        print(f"[{month_s}] source={source} n_published={len(rows)}/{n_universe} "
              f"est_ok={n_ok} 耗時 {time.time() - t0:.1f}s")

    doc = {
        "built_at": now.replace(microsecond=0).isoformat(),
        "price_date": price_date,
        "universe_note": f"市值前500（universe.parquet in_mktcap500，asof {asof}）",
        "periods": out_periods,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(_json_safe(doc), ensure_ascii=False, indent=None), encoding="utf-8")
    print(f"已寫 {OUT}（總耗時 {time.time() - t_start:.1f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
