"""重算價值/定存因子表 + 兩張候選清單。

M0.3 從 `tw-swing/scripts/build_value_factors.py` 搬走。與 tw-swing 版差異：
**只讀 tw-hold 拉下來的上游 bundle（`data/upstream/`），不讀 tw-swing 磁碟。**

    財報四表（bundle）           → reference.loader → 季度面板
    + 日線（bundle, 可選）        → factors          → 因子
    + 股利（bundle）              → screener         → 定存/價值兩清單
                                                     → data/derived/*.parquet + markdown

⚠️ **M0.3 現況**：bundle 尚未由 tw-swing 發佈。此腳本已能在「只有財報四表」時
   跑出退化版清單（日線類欄位留 NaN，screener 支援）。以下待 M0.1/M0.5 補齊：
   - `TODO(U3)` universe.parquet（市值前 500 ∪ 成交值前 500）→ 目前用
     capital_stock × 收盤 估市值前 500，缺收盤就不篩
   - `TODO(M0b)` prices_adj / 週波動 從 bundle 日線檔讀

用法：
    python build_factors.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from factors.factors import (annual_eps, dividend_factors, quarterly_factors)
from reference.loader import BUNDLE_DIR, load_dividends, load_quarterly
from screener.candidate_pool import build_candidate_pool
from screener.deposit_pricing import add_deposit_verdict
from screener.gates import GateError, assert_raw_not_adjusted
from screener.pricing import add_value_verdict
from screener.screen import screen_deposit, screen_value

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = Path(__file__).resolve().parent
DERIVED = REPO / "data" / "derived"
REPORT = REPO / "docs" / "reports" / "value_factors_latest.md"
TOP_N_LIST = 20


def _md_table(df: pd.DataFrame) -> str:
    """極簡 markdown 表——不引 tabulate（專案刻意控依賴）。"""
    if df.empty:
        return "_（無）_"
    cols = list(df.columns)
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = []
    for _, r in df.iterrows():
        body.append("| " + " | ".join(
            "" if pd.isna(v) else (f"{v:.3f}" if isinstance(v, float) else str(v))
            for v in r) + " |")
    return "\n".join([head, sep, *body])


def _split_adjust(d: pd.DataFrame, price_cols: list[str]) -> pd.DataFrame:
    """面額變更 / 股票分割：上游 `prices_adj` 沒還原 → 分割日前的價格 ÷ factor
    （見 reference.corporate_actions）。無已知分割的 ticker 原樣返回。"""
    from reference.corporate_actions import adjust_per_share
    return adjust_per_share(d, price_cols)


def _read_bundle_prices() -> pd.DataFrame | None:
    """從 bundle 日線檔取最新收盤 `[ticker, close]`。

    TODO(M0b): U1b 定案後改讀 `prices_adj.parquet`。現在容忍多種檔名，都沒有
    就回 None（screener 退化為只用財報排序）。
    """
    for name in ("prices_adj", "prices_raw_close", "prices_raw"):
        p = BUNDLE_DIR / f"{name}.parquet"
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        cols = {c.lower(): c for c in d.columns}
        tcol = cols.get("ticker") or cols.get("stock_id")
        ccol = cols.get("close") or cols.get("adj_close")
        dcol = cols.get("date")
        if not (tcol and ccol and dcol):
            continue
        d = d[[dcol, tcol, ccol]].rename(columns={dcol: "date", tcol: "ticker", ccol: "close"})
        d["ticker"] = d["ticker"].astype(str).str.split(".").str[0]
        d = _split_adjust(d, ["close"])
        return (d.sort_values("date").groupby("ticker", as_index=False).last()
                  [["ticker", "close"]])
    return None


def _read_bundle_price_history(lookback_weeks: int = 160) -> pd.DataFrame | None:
    """從 bundle `prices_adj.parquet` 取還原日線歷史 `[date, ticker, close]`
    （近 ~3 年，週波動足夠）。缺檔就回 None。"""
    p = BUNDLE_DIR / "prices_adj.parquet"
    if not p.exists():
        return None
    d = pd.read_parquet(p, columns=["date", "ticker", "close"])
    d["date"] = pd.to_datetime(d["date"])
    d["ticker"] = d["ticker"].astype(str).str.split(".").str[0]
    d = _split_adjust(d, ["close"])
    cutoff = d["date"].max() - pd.Timedelta(weeks=lookback_weeks)
    return d[d["date"] >= cutoff].reset_index(drop=True)


def _read_bundle_per_history() -> pd.DataFrame | None:
    """bundle `fundamentals/per.parquet` → `[ticker, date, per, dividend_yield]`
    （每日 PE / 殖利率，估值分位 + §7.3 殖利率門檻用）。"""
    p = BUNDLE_DIR / "fundamentals" / "per.parquet"
    if not p.exists():
        return None
    d = pd.read_parquet(p, columns=["ticker", "date", "per", "dividend_yield"])
    d["date"] = pd.to_datetime(d["date"])
    return d


def detect_unhandled_splits(lookback_days: int = 400) -> list[str]:
    """掃 `prices_adj` 近期有沒有「非除息日的 ~Nx 單日跳空」——上游沒還原的面額變更
    / 股票分割的症狀。已在 reference.corporate_actions.SPLITS 的不算。

    回傳警示字串（每檔一條）。build_lists 會印出來（rebuild.yml log 看得到）
    + 塞進清單 warning。這是「提醒去 TWSE 查基準日+比例、加進 SPLITS」的觸發器，
    不自動還原（啟發式會誤傷）。"""
    from reference.corporate_actions import SPLITS
    p = BUNDLE_DIR / "prices_adj.parquet"
    if not p.exists():
        return []
    d = pd.read_parquet(p, columns=["date", "ticker", "close"])
    d["date"] = pd.to_datetime(d["date"])
    d["ticker"] = d["ticker"].astype(str).str.split(".").str[0]
    d = d[(d["date"] >= d["date"].max() - pd.Timedelta(days=lookback_days))
          & (d["close"] > 0)].sort_values(["ticker", "date"])
    known = set(SPLITS)
    out = []
    for tk, g in d.groupby("ticker", sort=False):
        if tk in known or len(g) < 12:
            continue
        c = g["close"].to_numpy()
        dt = g["date"].to_numpy()
        r = c[1:] / c[:-1]
        idx = [i for i in np.where((r < 0.55) | (r > 1.8))[0]
               if 5 <= i <= len(c) - 6]
        # 前 5 日 vs 後 5 日中位數也差一個量級才算「站得住」（濾單日壞值）
        idx = [i for i in idx
               if not 0.6 < np.median(c[i + 1:i + 6]) / np.median(c[i - 4:i + 1]) < 1.7]
        # 同檔 25 日內有反向跳空 = 一段壞資料來回，不是分割 → 整檔略過
        if any((r[i] - 1) * (r[j] - 1) < 0 and abs(i - j) <= 17
               for a, i in enumerate(idx) for j in idx[a + 1:]):
            continue
        for i in idx:
            out.append(f"{tk} {pd.Timestamp(dt[i + 1]).date()} 還原收盤 ×{r[i]:.2f}"
                       f"——疑似未還原的面額變更/分割，去 TWSE 查基準日+比例加進 "
                       f"reference.corporate_actions.SPLITS")
    return out


def _read_bundle_ohlc() -> pd.DataFrame | None:
    """bundle `prices_adj.parquet` 全欄（date/ticker/OHLC/volume）——候選池趨勢模板 + ATR 用。"""
    p = BUNDLE_DIR / "prices_adj.parquet"
    if not p.exists():
        return None
    d = pd.read_parquet(p)
    d["date"] = pd.to_datetime(d["date"])
    return _split_adjust(d, [c for c in ("open", "high", "low", "close") if c in d.columns])


def _read_bundle_simple(name: str) -> pd.DataFrame | None:
    p = BUNDLE_DIR / f"{name}.parquet"
    return pd.read_parquet(p) if p.exists() else None


def _read_bundle_raw_close_history() -> pd.DataFrame | None:
    """bundle `prices_raw_close.parquet` → `[date, ticker, close]`（未還原收盤，填息率用）。"""
    p = BUNDLE_DIR / "prices_raw_close.parquet"
    if not p.exists():
        return None
    d = pd.read_parquet(p, columns=["date", "ticker", "close"])
    d["date"] = pd.to_datetime(d["date"])
    return d


def _weekly_vol(prices_hist: pd.DataFrame | None) -> pd.DataFrame | None:
    """年化週報酬標準差——低波動是定存區的核心因子。缺日線歷史就回 None。"""
    if prices_hist is None or {"date", "ticker", "close"} - set(prices_hist.columns):
        return None
    d = prices_hist.sort_values(["ticker", "date"])
    wk = (d.set_index("date").groupby("ticker")["close"]
            .resample("W").last().reset_index())
    wk["ret"] = wk.groupby("ticker")["close"].pct_change()
    vol = (wk.groupby("ticker")["ret"].std() * np.sqrt(52)).rename("ann_vol")
    return vol.reset_index()


def _universe_top500() -> tuple[set[str] | None, str]:
    """U3：讀 bundle 的 universe.parquet 取 `in_universe`（市值前500 ∪ 成交值前500）。
    沒有這個檔（M0a 只有 U1a）→ (None, 理由)。"""
    p = BUNDLE_DIR / "fundamentals" / "universe.parquet"
    if not p.exists():
        return None, "universe.parquet 不在 bundle（U1b 未發佈）→ 清單不做市值前500 過濾"
    u = pd.read_parquet(p)
    col = "in_universe" if "in_universe" in u.columns else None
    if col is None:
        return None, "universe.parquet 缺 in_universe 欄"
    return set(u.loc[u[col], "ticker"].astype(str)), f"universe.parquet：{int(u[col].sum())} 檔"


def _universe_maps() -> tuple[dict[str, str], dict[str, str]]:
    """(ticker→產業別, ticker→股名)，都來自 bundle `universe.parquet`。缺檔 → 空 dict。"""
    p = BUNDLE_DIR / "fundamentals" / "universe.parquet"
    if not p.exists():
        return {}, {}
    cols = set(pd.read_parquet(p, columns=None).columns)
    want = ["ticker"] + [c for c in ("industry", "stock_name") if c in cols]
    u = pd.read_parquet(p, columns=want)
    tk = u["ticker"].astype(str)
    ind = dict(zip(tk, u["industry"].fillna("未分類"))) if "industry" in u else {}
    nm = dict(zip(tk, u["stock_name"].fillna(""))) if "stock_name" in u else {}
    return ind, nm


#: 金融軌適用的 universe 產業別（FinMind `industry_category`）。金控/銀行/保險
#: 的損益表用不同 XBRL（YTD 累計、無 EPS type）、資產負債表無 capital_stock。
_FIN_INDUSTRIES = {"金融保險", "金融業"}


def _universe_financials() -> tuple[set[str], dict[str, float], pd.Series, pd.Series]:
    """(金融股 ticker 集合, ticker→股數, ticker→市值, ticker→產業別)。
    股數 = universe.market_cap ÷ close（金融股資產負債表沒有 capital_stock，只能這樣推）。
    缺 universe.parquet → 全空。"""
    p = BUNDLE_DIR / "fundamentals" / "universe.parquet"
    if not p.exists():
        return set(), {}, pd.Series(dtype=float), pd.Series(dtype=str)
    cols = set(pd.read_parquet(p, columns=None).columns)
    want = ["ticker"] + [c for c in ("industry", "close", "market_cap") if c in cols]
    u = pd.read_parquet(p, columns=want)
    u["ticker"] = u["ticker"].astype(str)
    u = u.drop_duplicates("ticker").set_index("ticker")
    ind = u["industry"] if "industry" in u else pd.Series(dtype=str)
    fin = set(ind[ind.isin(_FIN_INDUSTRIES)].index) if not ind.empty else set()
    mc = u["market_cap"] if "market_cap" in u else pd.Series(dtype=float)
    if "market_cap" in u and "close" in u:
        shares = (u["market_cap"] / u["close"]).replace([float("inf"), -float("inf")], pd.NA)
        shares = {t: float(v) for t, v in shares.dropna().items()}
    else:
        shares = {}
    return fin, shares, mc, ind


def _top500_by_mktcap(qf: pd.DataFrame, prices: pd.DataFrame | None) -> set[str] | None:
    """退化估法：universe.parquet 不在時，用「capital_stock × 最新收盤」估市值前 500；
    缺收盤就不篩（回 None）。"""
    if prices is None or "capital_stock" not in qf.columns:
        return None
    latest = (qf.sort_values("period_end").groupby("ticker")
                .tail(1)[["ticker", "capital_stock"]])
    mc = latest.merge(prices, on="ticker")
    mc["market_cap"] = mc["close"] * mc["capital_stock"] / 10.0
    return set(mc.dropna(subset=["market_cap"]).nlargest(500, "market_cap")["ticker"])


def screen_all() -> dict:
    """跑價值 / 定存篩選，回傳 `{deposit, value, context}`。
    `build_factors.main()`（parquet + md）與 `build_lists.main()`（JSON）共用。"""
    q = load_quarterly()
    fin_tickers, fin_shares, fin_mktcap, uni_industry = _universe_financials()
    qf = quarterly_factors(q, fin_tickers=fin_tickers, shares=fin_shares)
    div = load_dividends()
    divf = dividend_factors(div, annual_eps(qf))

    prices = _read_bundle_prices()
    price_hist = _read_bundle_price_history()
    raw_close_hist = _read_bundle_raw_close_history()
    per_hist = _read_bundle_per_history()
    vol = _weekly_vol(price_hist)

    # G2：未還原 / 還原搞混會讓填息率恆等 100% 且不報錯（PRD §10.2）
    g2_note = None
    if raw_close_hist is not None:
        g2_note = assert_raw_not_adjusted(raw_close_hist, price_hist, div)
    top500, uni_note = _universe_top500()
    if top500 is None:
        est = _top500_by_mktcap(qf, prices)
        if est is not None:
            top500, uni_note = est, uni_note + "；改用 capital_stock×收盤 估市值前500"

    dep = screen_deposit(qf, divf, prices=prices, vol=vol,
                         industry=uni_industry if not uni_industry.empty else None,
                         market_cap=fin_mktcap if not fin_mktcap.empty else None)
    val = screen_value(qf, prices=prices)
    dep["in_top500"] = True if top500 is None else dep["ticker"].isin(top500)
    val["in_top500"] = True if top500 is None else val["ticker"].isin(top500)

    # M2 §6.2/§6.3：價值買價 + verdict
    val = add_value_verdict(val, per_hist, price_hist)
    # M2 §7.1/§7.3/§7.4：定存兩道新硬門檻 + 殖利率法買價 + verdict
    dep = add_deposit_verdict(dep, raw_close_hist, price_hist, per_hist, div)

    ind, names = _universe_maps()
    for df in (val, dep):
        df["industry"] = df["ticker"].astype(str).map(ind)
        df["name"] = df["ticker"].astype(str).map(names)

    # M1 §5：主動選股候選池（狀態型，無 verdict / 無總分 / 無排名）
    pool, pool_note = [], "候選池未算"
    ohlc = _read_bundle_ohlc()
    idx0050 = _read_bundle_simple("index_0050")
    chips = _read_bundle_simple("chips")
    rev = _read_bundle_simple("revenue")
    if all(x is not None for x in (ohlc, idx0050, chips, rev)):
        uni = top500 if isinstance(top500, set) else None
        pool = build_candidate_pool(qf, ohlc, idx0050, chips, rev, uni)
        for rec in pool:
            rec["name"] = names.get(rec["ticker"], "")
            rec["industry"] = ind.get(rec["ticker"], "")
        pool_note = f"候選池 {len(pool)} 檔（CANSLIM ∩ 月營收 ∩ 法人 ∩ 趨勢模板 8/8）"
    else:
        pool_note = "候選池缺料（需 prices_adj / index_0050 / chips / revenue）"

    meta_p = BUNDLE_DIR / "_meta.json"
    bundle_meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    return {
        "deposit": dep, "value": val, "pool": pool,
        "context": {
            "pool_note": pool_note,
            "quarters": list(qf.shape), "tickers": int(qf.ticker.nunique()),
            "has_prices": prices is not None, "has_vol": vol is not None,
            "has_pe_bands": per_hist is not None,
            "has_fill_rate": raw_close_hist is not None,
            "has_industry": bool(ind),
            "g2_note": g2_note,
            "universe_filtered": top500 is not None, "universe_note": uni_note,
            "trading_date": bundle_meta.get("trading_date"),
            "bundle_schema": bundle_meta.get("schema_version"),
        },
    }


def main() -> int:
    print(f"bundle 目錄：{BUNDLE_DIR}", flush=True)
    print("載入財報整併檔…", flush=True)
    r = screen_all()
    dep, val, ctx = r["deposit"], r["value"], r["context"]
    print(f"  季度面板 {ctx['quarters']} · {ctx['tickers']} 檔 · "
          f"收盤 {'有' if ctx['has_prices'] else '—'} · 波動 {'有' if ctx['has_vol'] else '—'} · "
          f"{ctx['universe_note']}", flush=True)

    DERIVED.mkdir(parents=True, exist_ok=True)
    dep.to_parquet(DERIVED / "factors_deposit.parquet", index=False)
    val.to_parquet(DERIVED / "factors_value.parquet", index=False)
    print(f"  → {DERIVED/'factors_deposit.parquet'} / factors_value.parquet", flush=True)

    _write_report(dep, val)
    print(f"  → {REPORT}", flush=True)
    return 0


def _fmt(df: pd.DataFrame, score: str, cols: list[str]) -> str:
    sub = df[df["passes"] & df["in_top500"]].head(TOP_N_LIST)
    if sub.empty:
        return "_（沒有標的通過門檻）_\n"
    show = ["ticker", score] + [c for c in cols if c in sub.columns]
    t = sub[show].copy()
    for c in show[1:]:
        if not pd.api.types.is_numeric_dtype(t[c]) or pd.api.types.is_bool_dtype(t[c]):
            continue                       # verdict 等文字欄不轉數字
        t[c] = pd.to_numeric(t[c], errors="coerce").round(3)
    return _md_table(t)


def _write_report(dep: pd.DataFrame, val: pd.DataFrame) -> None:
    asof = pd.Timestamp.now().strftime("%Y-%m-%d")
    n_dep = int((dep["passes"] & dep["in_top500"]).sum())
    n_val = int((val["passes"] & val["in_top500"]).sum())
    md = [
        f"# 價值/定存因子表 · {asof}",
        "",
        "> `build_factors.py` 自動產生。**這是候選 + 為什麼，不是建議。**",
        "> 買入價、產業敘事、要不要買 → tw-hold + 人 + AI。",
        f"> 市值前 500 內：定存過門檻 {n_dep} 檔、價值過門檻 {n_val} 檔。",
        "",
        "## 定存區（存股安全分）",
        "",
        "門檻：近 4 季 EPS 全正 / 連續配息 ≥ 5 年無減配 / FCF 覆蓋股利 / "
        "配息來自盈餘 / 負債比 ≤ 0.75（金融業改用產業中位數）/ "
        "近 5 年填息率 ≥ 60% / 近 3 年含息報酬 ≥ 0。"
        "排序 = FCF 殖利率 × 低波動 × ROE × 連續年數 × (−payout) × 景氣循環懲罰。"
        "買價（§7.3）= 近 3 年均現金股利 ÷ max(近 5 年均殖利率, 5%)。",
        f"> verdict（§7.4）："
        + "、".join(f"{k} {v}" for k, v in
                   dep[dep["passes"] & dep["in_top500"]]["verdict"]
                   .str.replace(r"（.*", "", regex=True).value_counts().items()),
        "",
        _fmt(dep, "safety_score",
             ["verdict", "close", "cur_yield", "yield_floor", "est_buy_price",
              "buy_low", "buy_high", "fill_rate", "ret3y_incl", "ann_vol",
              "div_years"]),
        "",
        "## 價值區（F-Score ≥ 6 + Magic Formula 精神）",
        "",
        "門檻：Piotroski F-Score ≥ 6 / 營收非連 3 季衰退 / 毛利率 5 年未下滑 / "
        "FCF 為正。排序 = rank(品質: F-Score, ROE) + rank(便宜: normalized 盈餘"
        "殖利率, FCF 殖利率, EV/EBIT, 淨現金/市值)。",
        f"> verdict（§6.3，只由便宜門檻驅動）："
        + "、".join(f"{k} {v}" for k, v in
                   val[val["passes"] & val["in_top500"]]["verdict"]
                   .value_counts().items()),
        "",
        _fmt(val, "value_score",
             ["verdict", "close", "cheap_threshold", "buy_low", "buy_high",
              "f_score", "roe", "norm_pe", "fcf_yield", "upside_pct"]),
        "",
        "## 被剔除的（前 15，看門檻有沒有卡錯）",
        "",
        _md_table(pd.concat([
            dep[dep["in_top500"] & ~dep["passes"]][["ticker", "reject_reason"]].head(8).assign(區="定存"),
            val[val["in_top500"] & ~val["passes"]][["ticker", "reject_reason"]].head(8).assign(區="價值"),
        ])),
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
