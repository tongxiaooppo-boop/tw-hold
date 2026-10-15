"""自建上游 → `data_pack.zip` 格式轉接層（備援用；使用者 2026-10-06 要求）。

平時仍用現有上游（tw-stock-scanner 的 data_pack）；這支只是「上游掛了時」的後路：
把 `data/selfhost/*.parquet` 轉成 tw-swing 現行匯入吃的 zip（`scripts/import_data_pack.py`、`import_chips.py`），
**下游（tw-swing 匯入、bundle、tw-hold）完全不用改**。

輸出的 zip 結構（對照 tw-swing `docs/DATA_INVENTORY.md`）：
    data/{code}.TW.csv | data/{code}.TWO.csv      Date,Open,High,Low,Close,Volume   ← adj_prices（官方未還原價 × 官方因子）
    data/institutional/{code}_inst.csv            date, 外陸資買賣超股數(不含外資自營商), fi_prop_net, it_net, 自營商買賣超股數, total_net
    data/margin/{code}_margin.csv                 date, margin_*/short_*/offset（單位：張）＋ margin_prev, short_prev, note
    data/stock_list.csv                           ticker, code, name, market(上市/上櫃), sector

無成交日（2026-10-13 起）：官方行情表「有列、但收盤欄是 ---」的日子（冷門股當天沒成交，只有零股或完全沒量）不在 `raw_prices`，
改記在旁表 `notrade`。輸出 zip 時這些日子**沿用前一個還原收盤**（O=H=L=C，量用官方零股量），與官方「無成交 → 次日參考價沿用前收」同義，也與
上游（Yahoo）延續舊價的行為一致，tw-swing 的日線就不會少列。沿用的是「前一筆**還原**收盤」，所以跨減資／除權息事件也自然接上（等於事件參考價）。
**停牌不補**：官方當天根本沒有列（停止買賣、減資換股停牌、終止上市）→ 不在旁表 → 不補；原因看事件簿（`ledger` 的 gap／halt／event）。

口徑差（已知、已接受）：
  - **成交量**：自建＝官方成交股數，含零股、盤後定價、鉅額；上游（Yahoo）只算一般盤整股。全市場中位數高約 1.2～1.4%，台積電約 +14%，
    少數股票有大單時差數十倍到上千倍（例 3709 10/8 官方 6,263,225 股／198 筆 vs Yahoo 259,100；2024 2025-10-07 官方 31,055,267 vs Yahoo 8,001）。
    用量比、爆量、20 日均成交值門檻的規則會被少數大單灌爆，**不是資料錯**；tw-swing 端要不要扣鉅額／標註「疑似鉅額」尚未決定。
  - 還原價用官方因子，上游 data_pack 用 Yahoo 還原；兩者在接縫與官方參考價捨入處有差（見 docs/data-fix.md C6、C9）
  - 日線沒有成交金額（data_pack 本來就沒有）
  - 融資融券限額（margin_quota／short_quota）自建沒有，不輸出該欄（tw-swing 匯入也不讀）
  - 不輸出集保（data_pack 的集保已停更；tw-swing 自己有集保週快照）

⚠️ 籌碼歷史底稿：tw-swing 的 selfhost 模式**刻意略過** `apply_chips_baseline.py`（官方資料不可被 FinMind 底稿蓋掉，見 updatePRD-opus §2.6）；
   上游模式才要緊接 apply_chips_baseline。

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


def stock_list_frame(codes_market: dict[str, str], stock_list: pd.DataFrame | None, universe: pd.DataFrame | None,
                     carry: pd.DataFrame | None = None) -> pd.DataFrame:
    """ticker／code／name／market／sector。市場別一律以自建實價為準；名稱與產業別有來源才補。

    名稱／產業別的優先序（高→低）：`stock_list`（明確指定）→ `universe`（tw-swing bundle，最新）→
    `carry`（上一包已發佈的 stock_list）。**carry 是為了打斷閉環**：產業別本來只有 tw-swing 的
    universe 有，bundle 下載（PAT 到期、網路）一失敗，整包 sector 會變空，tw-swing 端 `sector.notna()`
    判個股 → 全宇宙零候選，而且換好 PAT 後還是空的（來源就是上一包的空值）。有 carry 時，bundle 拿不到
    只是名稱／產業別不更新，不會變空。名稱、產業別各自獨立補（一個空不影響另一個）。"""
    names: dict[str, list[str]] = {}

    def _fill(code: str, nm, sec) -> None:
        cur = names.setdefault(code, ["", ""])
        for i, v in enumerate((nm, sec)):
            v = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()
            if v and v.lower() != "nan" and not cur[i]:
                cur[i] = v

    if stock_list is not None and len(stock_list):
        for r in stock_list.itertuples():
            _fill(str(r.code).strip(), r.name, getattr(r, "sector", ""))
    if universe is not None and len(universe):
        for r in universe.itertuples():
            _fill(str(r.ticker).split(".")[0], getattr(r, "stock_name", ""), getattr(r, "industry", ""))
    if carry is not None and len(carry):
        for r in carry.itertuples():
            _fill(str(r.code).strip(), r.name, getattr(r, "sector", ""))
    rows = []
    for code, mk in sorted(codes_market.items()):
        nm, sec = names.get(code, ["", ""])
        rows.append({"ticker": f"{code}.{MARKET_SUFFIX[mk]}", "code": code, "name": nm, "market": MARKET_ZH[mk], "sector": sec})
    return pd.DataFrame(rows, columns=["ticker", "code", "name", "market", "sector"])


UNCLASSIFIED = "未分類（新上市）"
MAX_UNCLASSIFIED = 50                 # 正常約 16 檔；超過代表來源（universe＋carry）都斷了，閘門會擋
ACTIVE_WITHIN_DAYS = 7
NON_EQUITY_PREFIX = ("00", "91")      # ETF、存託憑證——沒有產業別是正常的，不是漏


def classify_new_listings(sl: pd.DataFrame, adj: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """近期仍在交易、4 碼、非 ETF／DR，卻沒有任何來源給產業別的個股（多半是這幾個月才上市）→ 補
    `UNCLASSIFIED`。tw-swing 以「sector 非空」判個股，沒補會讓這些股票永久進不了宇宙（2026-06 後上市的
    16 檔，含 7856 近 20 日成交值中位數約 20 億），而且上游 stock_list 本來也沒有它們。
    已下市／久未交易的舊代號不補（它們留在 zip 只是為了歷史），否則會混進每日掃描的個股集合。
    回 (新 sl, 補了幾檔)。產業別目前只用在研究用的 env filter，live 規則不吃，所以用固定標籤即可。"""
    if sl.empty or adj.empty:
        return sl, 0
    last = adj.groupby("ticker")["date"].max()
    cutoff = pd.to_datetime(adj["date"]).max() - pd.Timedelta(days=ACTIVE_WITHIN_DAYS)
    active = set(last[pd.to_datetime(last) >= cutoff].index.astype(str))
    need = ((sl["sector"] == "") & sl["code"].isin(active) & (sl["code"].str.len() == 4)
            & ~sl["code"].str.startswith(NON_EQUITY_PREFIX))
    sl = sl.copy()
    sl.loc[need, "sector"] = UNCLASSIFIED
    return sl, int(need.sum())


def fill_no_trade(adj: pd.DataFrame, notrade: pd.DataFrame | None) -> tuple[pd.DataFrame, int]:
    """把「官方有列、無成交價」的日子補進還原日線：O=H=L=C＝該檔前一筆**還原**收盤，量＝官方零股量。
    回 (新的 adj, 補了幾列)。補不了的（旁表那天已有實價、該檔之前沒有任何實價）直接略過。"""
    if notrade is None or notrade.empty:
        return adj, 0
    nt = notrade[["ticker", "date", "volume"]].copy()
    nt["ticker"] = nt["ticker"].astype(str)
    nt["date"] = pd.to_datetime(nt["date"]).astype("datetime64[us]")       # merge_asof 兩邊精度不同（ns／us）會直接 MergeError
    have = set(zip(adj["ticker"].astype(str), pd.to_datetime(adj["date"]).astype("datetime64[us]")))
    nt = nt[[(t, d) not in have for t, d in zip(nt["ticker"], nt["date"])]].drop_duplicates(["ticker", "date"])
    if nt.empty:
        return adj, 0
    prev = adj[["ticker", "date", "close", "raw_close"]].copy()
    prev["ticker"] = prev["ticker"].astype(str)
    prev["date"] = pd.to_datetime(prev["date"]).astype("datetime64[us]")
    prev = prev.rename(columns={"close": "_pc", "raw_close": "_prc"}).sort_values("date")
    m = pd.merge_asof(nt.sort_values("date"), prev, on="date", by="ticker", direction="backward", allow_exact_matches=False)
    m = m.dropna(subset=["_pc"])
    if m.empty:
        return adj, 0
    add = pd.DataFrame({"ticker": m["ticker"], "date": m["date"], "open": m["_pc"], "high": m["_pc"], "low": m["_pc"],
                        "close": m["_pc"], "volume": m["volume"].fillna(0.0), "raw_close": m["_prc"]})
    return pd.concat([adj, add.astype(adj.dtypes.to_dict(), errors="ignore")], ignore_index=True), len(add)


def build(out_zip: Path, adj: pd.DataFrame, raw: pd.DataFrame, inst: pd.DataFrame | None, margin: pd.DataFrame | None,
          stock_list: pd.DataFrame | None = None, universe: pd.DataFrame | None = None,
          tickers: set[str] | None = None, since: str | None = None, four_digit_only: bool = True,
          notrade: pd.DataFrame | None = None, carry: pd.DataFrame | None = None) -> dict:
    """組 zip。回傳統計 dict。tickers／since 只給小量試跑用。"""
    mk = latest_market(raw)
    if four_digit_only:
        mk = {t: m for t, m in mk.items() if len(t) == 4 and t.isdigit()}
    if tickers:
        mk = {t: m for t, m in mk.items() if t in tickers}
    adj = adj[adj["ticker"].isin(mk)]
    adj, n_filled = fill_no_trade(adj, notrade)
    adj = adj[adj["ticker"].isin(mk)]
    if since:
        adj = adj[adj["date"] >= pd.Timestamp(since)]
    stats = {"price_files": 0, "inst_files": 0, "margin_files": 0, "tickers": len(mk), "no_trade_filled": n_filled}
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
        sl = stock_list_frame({t: mk[t] for t in have_price}, stock_list, universe, carry)
        sl, n_unclassified = classify_new_listings(sl, adj)
        stats["stock_list_unclassified"] = n_unclassified
        if n_unclassified > MAX_UNCLASSIFIED:
            print(f"::warning::{n_unclassified} 檔個股補成「{UNCLASSIFIED}」（正常約 16 檔）——名稱／產業別來源可能整批斷了", file=sys.stderr)
        z.writestr("data/stock_list.csv", sl.to_csv(index=False))
        stats["stock_list_rows"] = len(sl)
        stats["stock_list_named"] = int((sl["name"] != "").sum())
        # 真正有產業別的才算：UNCLASSIFIED 是補位標籤，不能讓閘門以為產業別沒斷
        stats["stock_list_sector"] = int(((sl["sector"] != "") & (sl["sector"] != UNCLASSIFIED)).sum())
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
    ap.add_argument("--carry", help="上一包已發佈的 stock_list（csv，欄位同上）；universe 拿不到時沿用名稱／產業別，打斷閉環")
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
    notrade = pd.read_parquet(d / "notrade.parquet") if (d / "notrade.parquet").exists() else None   # 沒有就不補（舊流程相容）
    stats = build(Path(a.out), adj, raw, inst, margin,
                  _read_any(Path(a.stock_list) if a.stock_list else None), _read_any(Path(a.universe)),
                  set(a.tickers.split(",")) if a.tickers else None, a.since, not a.all_codes, notrade,
                  _read_any(Path(a.carry) if a.carry else None))
    print("[datapack]", stats)
    if stats["price_files"] == 0:
        print("::error::沒有轉出任何日線檔", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
