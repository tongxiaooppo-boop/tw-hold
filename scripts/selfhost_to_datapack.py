"""自建上游 → `data_pack.zip` 格式轉接層（備援用；使用者 2026-10-06 要求）。

平時仍用現有上游（tw-stock-scanner 的 data_pack）；這支只是「上游掛了時」的後路：
把 `data/selfhost/*.parquet` 轉成 tw-swing 現行匯入吃的 zip（`scripts/import_data_pack.py`、`import_chips.py`），
**下游（tw-swing 匯入、bundle、tw-hold）完全不用改**。

輸出的 zip 結構（對照 tw-swing `docs/DATA_INVENTORY.md`）：
    data/{code}.TW.csv | data/{code}.TWO.csv      Date,Open,High,Low,Close,Volume   ← adj_prices（官方未還原價 × 官方因子）
    data/institutional/{code}_inst.csv            date, 外陸資買賣超股數(不含外資自營商), fi_prop_net, it_net, 自營商買賣超股數, total_net
    data/margin/{code}_margin.csv                 date, margin_*/short_*/offset（單位：張）＋ margin_prev, short_prev, note
    data/stock_list.csv                           ticker, code, name, market(上市/上櫃), sector

口徑差（已知、已接受）：
  - 還原價用官方因子，上游 data_pack 用 Yahoo 還原；兩者在接縫與官方參考價捨入處有差（見 docs/data-fix.md C6、C9）
  - 日線沒有成交金額（data_pack 本來就沒有）
  - 融資融券限額（margin_quota／short_quota）自建沒有，不輸出該欄（tw-swing 匯入也不讀）
  - 不輸出集保（data_pack 的集保已停更；tw-swing 自己有集保週快照）

⚠️ tw-swing 匯入後仍要緊接 `apply_chips_baseline.py`（FinMind 修好的籌碼歷史底稿疊回），順序不變。

名稱與產業別：自建沒有，用 `--stock-list`（tw-swing 的 `data/store/stock_list.csv|parquet`，欄位 ticker/code/name/market/sector）
或 `--universe`（bundle 的 `data/upstream/fundamentals/universe.parquet`）補；都沒有就留空（匯入不會失敗，只是產業別為空）。

用法：
    python scripts/selfhost_to_datapack.py --out data/selfhost/data_pack_selfhost.zip --stock-list ../tw-swing/data/store/stock_list.parquet
    python scripts/selfhost_to_datapack.py --out /tmp/x.zip --tickers 2330,2317 --since 2024-01-01   # 小量試跑
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "data" / "selfhost"

FOREIGN_COL = "外陸資買賣超股數(不含外資自營商)"
DEALER_COL = "自營商買賣超股數"
MARGIN_COLS = ["margin_buy", "margin_sell", "margin_redeem", "margin_balance",
               "short_buy", "short_sell", "short_redeem", "short_balance", "offset"]
MARKET_ZH = {"TW": "上市", "TWO": "上櫃"}
MARKET_SUFFIX = {"TW": "TW", "TWO": "TWO"}


def latest_market(raw: pd.DataFrame) -> dict[str, str]:
    """每檔「現在在哪個市場」：以實價最後一列為準（轉板的檔以最近的市場為準，與 data_pack 一檔一檔案一致）。"""
    r = raw.sort_values("date").drop_duplicates("ticker", keep="last")
    return dict(zip(r["ticker"], r["market"]))


def price_csv(g: pd.DataFrame) -> str:
    out = pd.DataFrame({
        "Date": pd.to_datetime(g["date"]).dt.strftime("%Y-%m-%d"),
        "Open": g["open"], "High": g["high"], "Low": g["low"], "Close": g["close"],
        "Volume": g["volume"].fillna(0).astype("int64"),
    })
    return out.to_csv(index=False)


def inst_csv(g: pd.DataFrame, ticker_name: str) -> str:
    out = pd.DataFrame({
        "ticker": ticker_name,
        "date": pd.to_datetime(g["date"]).dt.strftime("%Y-%m-%d"),
        FOREIGN_COL: g["foreign_net"], "fi_prop_net": g["fi_prop_net"], "it_net": g["trust_net"],
        DEALER_COL: g["dealer_net"], "total_net": g["total_net"],
    })
    return out.to_csv(index=False)


def margin_csv(g: pd.DataFrame, ticker_name: str) -> str:
    out = pd.DataFrame({"ticker": ticker_name, "date": pd.to_datetime(g["date"]).dt.strftime("%Y-%m-%d")})
    for c in MARGIN_COLS:
        out[c] = g[c] if c in g.columns else pd.NA
    for c in ("margin_prev", "short_prev", "note"):          # 自建多存的欄位，附上不影響匯入（匯入只讀上面那些欄）
        if c in g.columns:
            out[c] = g[c]
    return out.to_csv(index=False)


def stock_list_frame(codes_market: dict[str, str], stock_list: pd.DataFrame | None, universe: pd.DataFrame | None) -> pd.DataFrame:
    """ticker／code／name／market／sector。市場別一律以自建實價為準；名稱與產業別有來源才補。"""
    names: dict[str, tuple[str, str]] = {}
    if stock_list is not None and len(stock_list):
        sl = stock_list.copy()
        sl["code"] = sl["code"].astype(str).str.strip()
        names.update({r.code: (str(r.name), str(getattr(r, "sector", "") or "")) for r in sl.itertuples()})
    if universe is not None and len(universe):
        for r in universe.itertuples():
            names.setdefault(str(r.ticker).split(".")[0],
                             (str(getattr(r, "stock_name", "") or ""), str(getattr(r, "industry", "") or "")))
    rows = []
    for code, mk in sorted(codes_market.items()):
        nm, sec = names.get(code, ("", ""))
        rows.append({"ticker": f"{code}.{MARKET_SUFFIX[mk]}", "code": code, "name": nm, "market": MARKET_ZH[mk], "sector": sec})
    return pd.DataFrame(rows, columns=["ticker", "code", "name", "market", "sector"])


def build(out_zip: Path, adj: pd.DataFrame, raw: pd.DataFrame, inst: pd.DataFrame | None, margin: pd.DataFrame | None,
          stock_list: pd.DataFrame | None = None, universe: pd.DataFrame | None = None,
          tickers: set[str] | None = None, since: str | None = None, four_digit_only: bool = True) -> dict:
    """組 zip。回傳統計 dict。tickers／since 只給小量試跑用。"""
    mk = latest_market(raw)
    if four_digit_only:
        mk = {t: m for t, m in mk.items() if len(t) == 4 and t.isdigit()}
    if tickers:
        mk = {t: m for t, m in mk.items() if t in tickers}
    adj = adj[adj["ticker"].isin(mk)]
    if since:
        adj = adj[adj["date"] >= pd.Timestamp(since)]
    stats = {"price_files": 0, "inst_files": 0, "margin_files": 0, "tickers": len(mk)}
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_zip.with_suffix(out_zip.suffix + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        have_price = set()
        for t, g in adj.sort_values(["ticker", "date"]).groupby("ticker", sort=False):
            z.writestr(f"data/{t}.{MARKET_SUFFIX[mk[t]]}.csv", price_csv(g))
            have_price.add(t)
            stats["price_files"] += 1
        for name, df, fn, folder, suffix in (("inst", inst, inst_csv, "institutional", "inst"),
                                             ("margin", margin, margin_csv, "margin", "margin")):
            if df is None or df.empty:
                continue
            d = df[df["ticker"].isin(have_price)]
            if since:
                d = d[d["date"] >= pd.Timestamp(since)]
            for t, g in d.sort_values(["ticker", "date"]).groupby("ticker", sort=False):
                z.writestr(f"data/{folder}/{t}_{suffix}.csv", fn(g, f"{t}.{MARKET_SUFFIX[mk[t]]}"))
                stats[f"{name}_files"] += 1
        sl = stock_list_frame({t: mk[t] for t in have_price}, stock_list, universe)
        z.writestr("data/stock_list.csv", sl.to_csv(index=False))
        stats["stock_list_rows"] = len(sl)
        stats["stock_list_named"] = int((sl["name"] != "").sum())
    tmp.replace(out_zip)          # 完整寫完才換名（不留半截 zip）
    return stats


def _read_any(p: Path | None) -> pd.DataFrame | None:
    if p is None:
        return None
    if not p.exists():
        print(f"::warning::找不到 {p}，略過", file=sys.stderr)
        return None
    return pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p, dtype={"code": str})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--stock-list", help="tw-swing 的 stock_list（csv 或 parquet，欄位 ticker/code/name/market/sector）")
    ap.add_argument("--universe", default=str(ROOT / "data" / "upstream" / "fundamentals" / "universe.parquet"))
    ap.add_argument("--tickers", help="逗號分隔，只轉這幾檔（試跑用）")
    ap.add_argument("--since", help="YYYY-MM-DD，只轉這天之後（試跑用）")
    ap.add_argument("--all-codes", action="store_true", help="不限 4 碼（預設只轉 4 碼，與自建收集範圍一致）")
    ap.add_argument("--in-dir", help="讀這個目錄的 adj_prices／raw_prices／inst／margin（每日併入版用 data/selfhost/merged）；預設 data/selfhost")
    a = ap.parse_args(argv)
    d = Path(a.in_dir) if a.in_dir else SH
    adj = pd.read_parquet(d / "adj_prices.parquet")
    adj["date"] = pd.to_datetime(adj["date"])
    raw = pd.read_parquet(d / "raw_prices.parquet", columns=["ticker", "market", "date"])
    inst = pd.read_parquet(d / "inst.parquet")
    margin = pd.read_parquet(d / "margin.parquet")
    stats = build(Path(a.out), adj, raw, inst, margin,
                  _read_any(Path(a.stock_list) if a.stock_list else None), _read_any(Path(a.universe)),
                  set(a.tickers.split(",")) if a.tickers else None, a.since, not a.all_codes)
    print("[datapack]", stats)
    if stats["price_files"] == 0:
        print("::error::沒有轉出任何日線檔", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
