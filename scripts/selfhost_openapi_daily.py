"""自建上游：官方 OpenAPI 每日收集（只存不使用，不進閘門、不接任何下游）。

## 為什麼存在
2026-10-06 決定（docs/HANDOFF_2026-10-06_night.md §1.6）：每天的尾巴用官方 OpenAPI 日線，解掉 Yahoo 在除權息前一晚就乘因子的問題；
備援順序 OpenAPI → 網站端點（有日期參數）→ 上游。OpenAPI **沒有日期參數、只回最新一天**，漏一天就補不回來，所以每天要跑、要多班。
這支先只做「存」並累積實測，讓之後能回答：OpenAPI 到底缺什麼、官方什麼時候更新。

## 抓什麼（2026-10-07 實測，見 docs/data-dl.md §11）
| 資料集 | 端點 | 備註 |
| :-- | :-- | :-- |
| 上市日線 | openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL | 與網站端點 MI_INDEX 7 欄完全相同 |
| 上櫃日線 | www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes | 與網站 dailyQuotes 889 檔四碼股量額價**全部相同**（2026-10-07 實測）。⚠️ 舊端點 `tpex_mainboard_quotes` 量額有 860／889 檔偏低（總量少 2.2%），不要用 |
| 上櫃融資券 | www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance | 11 個數值欄與網站完全相同 |
上市融資 `MI_MARGN` 沒有日期欄，無法斷言資料日 → **本版不收**（待用「前日餘額＝昨日最終餘額」自證後再加）。

## 規矩
- 回應內每列 `Date`（民國 7 碼）必須全部相同、且不是未來；否則丟棄並警告，絕不存。**太舊不算錯**（春節等長假官方日期會停在封關日，
  超過 7 天只印註記；同一資料日重複抓到會因 Last-Modified 沒變而略過）。
- 解析後列數低於下限（上市日線 500、上櫃日線 400、上櫃融資 300）→ 視為失敗不存（官方改欄名／回殘缺資料時不能悄悄寫入空表）。
- 同一資料日被「較新的 Last-Modified」覆蓋時，新列數若不到舊列數的 90% → 不覆蓋、發警告（`shrunk`），避免半成品換掉完整的一天。
- 每列記 `last_modified`（HTTP 標頭，官方最後一次重新產生檔案的時間）與 `fetched_at`；每次請求另記一行 `openapi_fetch_log.jsonl`
  （端點、HTTP 狀態、資料日、Last-Modified、列數），累積「官方每天什麼時候更新」的實測分布。
- 同一 (資料集, 資料日) 若 Last-Modified 比已存的新 → 整天覆蓋（官方事後更正）；一樣或較舊 → 略過，重跑冪等。
  例外：src 等級較高者（上櫃 openapi_dc 對舊端點存下的 openapi）無視 Last-Modified 覆蓋；反方向略過；縮水保護不分來源。
  舊端點量額偏低的原因見 docs/data-fix.md B4 第 3 點（6488 實測：舊端點不含零股、盤後、鉅額，daily_close_quotes 含鉅額）。
- 每次結尾對交易日曆檢查近 14 天有沒有缺的交易日，有洞就發 `::warning::`（不失敗；網站端點補得回來）。
- 單一端點失敗不影響其他端點；全部失敗才非零退出。

輸出（`data/selfhost/`）：`openapi_prices.parquet`、`openapi_margin.parquet`、`openapi_fetch_log.jsonl`。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

SH = Path(__file__).resolve().parents[1] / "data" / "selfhost"
PRICES = SH / "openapi_prices.parquet"
MARGIN = SH / "openapi_margin.parquet"
LOG = SH / "openapi_fetch_log.jsonl"
UA = {"User-Agent": "Mozilla/5.0"}
TWSE_DAY = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_DAY = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TPEX_MARGIN = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"
TZ = ZoneInfo("Asia/Taipei")
MAX_AGE_DAYS = 7           # 超過只印註記
MIN_ROWS = {"twse_day": 500, "tpex_day": 400, "tpex_margin": 300}
SHRINK_RATIO = 0.9
SRC_TPEX_DC = "openapi_dc"   # 上櫃改用 daily_close_quotes 後的標記；舊端點（src=openapi）存下的同一天量額偏低，要能被它覆蓋
SRC_RANK = {"openapi": 0, SRC_TPEX_DC: 1}   # 只准單向升級：等級高的可無視 Last-Modified 覆蓋等級低的，反方向一律略過
GAP_WINDOW_DAYS = 14

PRICE_COLS = ["ticker", "market", "date", "open", "high", "low", "close", "volume", "value", "chg", "src", "last_modified", "fetched_at"]
MARGIN_COLS = ["ticker", "market", "date", "margin_prev", "margin_buy", "margin_sell", "margin_redeem", "margin_balance",
               "short_prev", "short_buy", "short_sell", "short_redeem", "short_balance", "offset", "note",
               "src", "last_modified", "fetched_at"]
# 自建 margin.parquet 欄名 ← OpenAPI 欄名（2026-10-06 上櫃 802 檔逐欄比對全相同）
MARGIN_MAP = {"margin_prev": "MarginPurchaseBalancePreviousDay", "margin_buy": "MarginPurchase", "margin_sell": "MarginSales",
              "margin_redeem": "CashRedemption", "margin_balance": "MarginPurchaseBalance",
              "short_prev": "ShortSaleBalancePreviousDay", "short_buy": "ShortConvering", "short_sell": "ShortSale",
              "short_redeem": "StockRedemption", "short_balance": "ShortSaleBalance", "offset": "Offsetting"}


def _num(x) -> float | None:
    s = str(x).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def roc_to_date(s: str) -> date:
    s = str(s).strip()
    return date(int(s[:-4]) + 1911, int(s[-4:-2]), int(s[-2:]))


def parse_last_modified(v: str | None) -> pd.Timestamp | None:
    if not v:
        return None
    try:
        return pd.Timestamp(parsedate_to_datetime(v)).tz_convert("UTC").tz_localize(None)
    except (TypeError, ValueError):
        return None


def assert_one_date(rows: list[dict], today: date) -> date | None:
    """回應內每列 Date 必須全部相同、且不是未來；否則回 None（呼叫端丟棄）。太舊只是註記，不丟。"""
    try:
        ds = {roc_to_date(r["Date"]) for r in rows}
    except (KeyError, ValueError):
        return None
    if len(ds) != 1:
        return None
    d = next(iter(ds))
    return d if d <= today else None


def parse_prices(rows: list[dict], market: str, d: date, lm, fetched) -> pd.DataFrame:
    out = []
    for r in rows:
        if market == "TW":
            code, o, h, l, c = r.get("Code"), r.get("OpeningPrice"), r.get("HighestPrice"), r.get("LowestPrice"), r.get("ClosingPrice")
            vol, val, chg = r.get("TradeVolume"), r.get("TradeValue"), r.get("Change")
        else:
            code, o, h, l, c = r.get("SecuritiesCompanyCode"), r.get("Open"), r.get("High"), r.get("Low"), r.get("Close")
            vol, val, chg = r.get("TradingShares"), r.get("TransactionAmount"), r.get("Change")
        code = str(code or "").strip()
        close = _num(c)
        if not (code.isdigit() and len(code) == 4) or close is None or close <= 0:     # 與 raw_prices 同規則：4 碼、有成交價
            continue
        out.append({"ticker": code, "market": market, "date": pd.Timestamp(d),
                    "open": _num(o) or close, "high": _num(h) or close, "low": _num(l) or close, "close": close,
                    "volume": _num(vol) or 0.0, "value": _num(val) or 0.0, "chg": _num(chg),
                    "src": "openapi" if market == "TW" else SRC_TPEX_DC, "last_modified": lm, "fetched_at": fetched})
    return pd.DataFrame(out, columns=PRICE_COLS)


def parse_margin(rows: list[dict], market: str, d: date, lm, fetched) -> pd.DataFrame:
    out = []
    for r in rows:
        code = str(r.get("SecuritiesCompanyCode", "")).strip()
        if not (code.isdigit() and len(code) == 4):
            continue
        rec = {"ticker": code, "market": market, "date": pd.Timestamp(d), "note": str(r.get("Note", "") or "").strip(),
               "src": "openapi", "last_modified": lm, "fetched_at": fetched}
        rec.update({k: _num(r.get(v)) for k, v in MARGIN_MAP.items()})
        out.append(rec)
    return pd.DataFrame(out, columns=MARGIN_COLS)


def merge_day(old: pd.DataFrame, new: pd.DataFrame, cols: list[str]) -> tuple[pd.DataFrame, str]:
    """把一個 (市場, 資料日) 併進舊表。回 (新表, 動作)：added／replaced／skipped（Last-Modified 沒比較新）／shrunk（較新但列數縮水，不覆蓋）。"""
    if new.empty:
        return old, "empty"
    mk, d = new["market"].iloc[0], new["date"].iloc[0]
    mask = (old["market"] == mk) & (old["date"] == d) if len(old) else pd.Series([], dtype=bool)
    if len(old) and mask.any():
        old_lm = old.loc[mask, "last_modified"].max()
        new_lm = new["last_modified"].iloc[0]
        old_rank = int(old.loc[mask, "src"].map(SRC_RANK).fillna(0).max()) if "src" in old.columns else 0
        new_rank = SRC_RANK.get(new["src"].iloc[0], 0)
        if new_rank < old_rank:
            return old, "skipped"                                   # 舊端點不能蓋掉新端點的資料（不論 Last-Modified）
        if new_rank == old_rank and (pd.isna(new_lm) or (pd.notna(old_lm) and new_lm <= old_lm)):
            return old, "skipped"                                   # 同來源：Last-Modified 沒比較新就略過；只有單向升級才無視它
        if len(new) < SHRINK_RATIO * int(mask.sum()):
            return old, "shrunk"                                    # 縮水保護不分來源
        merged = pd.concat([old.loc[~mask], new], ignore_index=True)
        action = "replaced"
    else:
        merged = pd.concat([old, new], ignore_index=True) if len(old) else new.copy()
        action = "added"
    return merged.sort_values(["date", "market", "ticker"]).reset_index(drop=True)[cols], action


def missing_trading_days(have: set[date], today: date, closed: set[date] | None) -> list[date]:
    """近 GAP_WINDOW_DAYS 天（不含今天與昨天，還沒公布）裡，交易日卻沒有資料的日子。休市表抓不到 → 只排除週末。"""
    out = []
    for i in range(2, GAP_WINDOW_DAYS + 1):          # 昨天不查：官方可能隔天清晨才更新（上市 Last-Modified 是隔天 05:20）
        d = today - timedelta(days=i)
        if d.weekday() >= 5 or (closed and d in closed):
            continue
        if d not in have:
            out.append(d)
    return sorted(out)


def _atomic_parquet(df: pd.DataFrame, p: Path) -> None:
    """先寫暫存檔再換名：被取消／逾時時不會留下寫到一半的 parquet。"""
    tmp = p.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, p)


def _log(entry: dict) -> None:
    SH.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def fetch(url: str):
    """回 (rows|None, last_modified_header|None, http_status|None, 錯誤字串)。"""
    try:
        r = requests.get(url, headers=UA, timeout=60)
        lm = r.headers.get("Last-Modified")
        r.raise_for_status()
        j = r.json()
        if not isinstance(j, list) or not j:
            return None, lm, r.status_code, "回應不是非空列表"
        return j, lm, r.status_code, ""
    except Exception as e:      # noqa: BLE001
        return None, None, getattr(getattr(e, "response", None), "status_code", None), str(e)[:120]


def _read(p: Path, cols: list[str]) -> pd.DataFrame:
    return pd.read_parquet(p) if p.exists() else pd.DataFrame(columns=cols).astype({"date": "datetime64[ns]"})


def main() -> int:
    now = datetime.now(TZ)
    today, fetched = now.date(), pd.Timestamp(now.astimezone(ZoneInfo("UTC")).replace(tzinfo=None))
    jobs = [("twse_day", TWSE_DAY, "TW", parse_prices, PRICES, PRICE_COLS),
            ("tpex_day", TPEX_DAY, "TWO", parse_prices, PRICES, PRICE_COLS),
            ("tpex_margin", TPEX_MARGIN, "TWO", parse_margin, MARGIN, MARGIN_COLS)]
    tables = {PRICES: _read(PRICES, PRICE_COLS), MARGIN: _read(MARGIN, MARGIN_COLS)}
    ok = 0
    changed = False
    for name, url, mk, parser, path, cols in jobs:
        rows, lm_hdr, status, err = fetch(url)
        entry = {"fetched_at": str(fetched), "endpoint": name, "http": status, "last_modified": lm_hdr, "rows": len(rows) if rows else 0}
        if rows is None:
            entry["result"] = f"失敗：{err}"
            print(f"::warning::OpenAPI {name} 失敗：{err}", file=sys.stderr)
            _log(entry)
            continue
        d = assert_one_date(rows, today)
        entry["data_date"] = str(d) if d else None
        if d is None:
            entry["result"] = "日期斷言不過，丟棄"
            print(f"::warning::OpenAPI {name} 回應日期不一致或是未來日期，丟棄", file=sys.stderr)
            _log(entry)
            continue
        if (today - d).days > MAX_AGE_DAYS:
            print(f"[openapi] {name}：資料日 {d} 距今超過 {MAX_AGE_DAYS} 天（長假或官方停更？），照常處理")
        df = parser(rows, mk, d, parse_last_modified(lm_hdr), fetched)
        if len(df) < MIN_ROWS[name]:
            entry["result"] = f"失敗：解析後只有 {len(df)} 列（下限 {MIN_ROWS[name]}），不存"
            print(f"::warning::OpenAPI {name} 解析後只有 {len(df)} 列（下限 {MIN_ROWS[name]}）——官方改欄名或回殘缺資料？不存", file=sys.stderr)
            _log(entry)
            continue
        tables[path], action = merge_day(tables[path], df, cols)
        if action in ("added", "replaced"):
            changed = True
        if action == "shrunk":
            print(f"::warning::OpenAPI {name} 資料日 {d}：較新的檔案列數縮水（{len(df)} 列），不覆蓋已存的完整版", file=sys.stderr)
        entry["result"] = f"{action} {len(df)} 列"
        print(f"[openapi] {name}：資料日 {d}、{len(df)} 列、{action}（Last-Modified {lm_hdr}）")
        _log(entry)
        ok += 1
    SH.mkdir(parents=True, exist_ok=True)
    if changed:         # 沒有變更就不寫檔、workflow 也不重傳 parquet（--clobber 是先刪再傳，傳到一半失敗會永久丟歷史）
        for p, t in tables.items():
            if len(t):
                _atomic_parquet(t, p)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import last_trading_day_guard as g  # noqa: PLC0415
        closed = g.fetch_closed()
    except Exception:       # noqa: BLE001
        closed = None
    for name, path, mk in (("上市日線", PRICES, "TW"), ("上櫃日線", PRICES, "TWO"), ("上櫃融資券", MARGIN, "TWO")):
        t = tables[path]
        t = t[t["market"] == mk] if len(t) else t
        if not len(t):                      # 累積檔還是空的（首日、端點整個失敗）→ 不查，免得報出假缺口
            continue
        have = {x.date() for x in t["date"].unique()}
        gaps = [d for d in missing_trading_days(have, today, closed) if d >= min(have)]
        if gaps:
            print(f"::warning::OpenAPI {name} 累積檔缺交易日：{', '.join(map(str, gaps))}（網站端點補得回來）", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
