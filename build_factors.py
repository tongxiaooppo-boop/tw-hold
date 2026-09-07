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

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from factors.factors import (annual_eps, dividend_factors, quarterly_factors)
from reference.loader import BUNDLE_DIR, load_dividends, load_quarterly
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
        return (d.sort_values("date").groupby("ticker", as_index=False).last()
                  [["ticker", "close"]])
    return None


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


def _top500_by_mktcap(qf: pd.DataFrame, prices: pd.DataFrame | None) -> set[str] | None:
    """TODO(U3): 換成讀 universe.parquet（市值前 500 ∪ 成交值前 500）。
    現在只用「capital_stock × 最新收盤」估市值前 500；缺收盤就不篩（回 None）。"""
    if prices is None or "capital_stock" not in qf.columns:
        return None
    latest = (qf.sort_values("period_end").groupby("ticker")
                .tail(1)[["ticker", "capital_stock"]])
    mc = latest.merge(prices, on="ticker")
    mc["market_cap"] = mc["close"] * mc["capital_stock"] / 10.0
    return set(mc.dropna(subset=["market_cap"]).nlargest(500, "market_cap")["ticker"])


def main() -> int:
    print(f"bundle 目錄：{BUNDLE_DIR}", flush=True)
    print("載入財報整併檔…", flush=True)
    q = load_quarterly()
    qf = quarterly_factors(q)
    div = load_dividends()
    divf = dividend_factors(div, annual_eps(qf))

    prices = _read_bundle_prices()
    vol = _weekly_vol(None)  # TODO(M0b): 傳 bundle 日線歷史
    top500 = _top500_by_mktcap(qf, prices)
    print(f"  季度面板 {qf.shape} · {qf.ticker.nunique()} 檔 · 股利 {divf.shape} · "
          f"收盤 {'—' if prices is None else len(prices)} · "
          f"波動 {'—' if vol is None else len(vol)} · "
          f"市值前500 {'未篩' if top500 is None else len(top500)}", flush=True)

    dep = screen_deposit(qf, divf, prices=prices, vol=vol)
    val = screen_value(qf, prices=prices)
    dep["in_top500"] = True if top500 is None else dep["ticker"].isin(top500)
    val["in_top500"] = True if top500 is None else val["ticker"].isin(top500)

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
        "配息來自盈餘 / 負債比 ≤ 0.75。排序 = FCF 殖利率 × 低波動 × ROE × "
        "連續年數 × (−payout) × 景氣循環懲罰。",
        "",
        _fmt(dep, "safety_score",
             ["div_years", "last_cash_dividend", "fcf_yield", "ann_vol", "roe",
              "payout_ratio_ttm", "cyclical_penalty", "debt_ratio"]),
        "",
        "## 價值區（F-Score ≥ 6 + Magic Formula 精神）",
        "",
        "門檻：Piotroski F-Score ≥ 6 / 營收非連 3 季衰退 / 毛利率 5 年未下滑 / "
        "FCF 為正。排序 = rank(品質: F-Score, ROE) + rank(便宜: normalized 盈餘"
        "殖利率, FCF 殖利率, EV/EBIT, 淨現金/市值)。",
        "",
        _fmt(val, "value_score",
             ["f_score", "roe", "norm_pe", "norm_ey", "fcf_yield", "ev_ebit",
              "net_cash_to_mktcap", "gross_margin"]),
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
