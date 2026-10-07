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
上市融資：OpenAPI 的 MI_MARGN 沒有日期欄，不用；改打**網站端點** `rwd/zh/marginTrading/MI_MARGN?date=`（帶日期、回應會回傳自己的日期，
由 `selfhost_chips.margin_twse` 斷言相符，沒資料回「沒有符合條件」＝尚未公布）。每次嘗試前一個平日；「今天」要台北 22:00 之後才試（融資約 22:00 公布）；已存的日子若最後抓取早於隔日 00:00（台北）會再打一次、內容有差才整天替換（官方隔日調帳），之後不再打；src 標 `web_mi_margn`。

## 規矩
- 回應內每列 `Date`（民國 7 碼）必須全部相同、且不是未來；否則丟棄並警告，絕不存。**太舊不算錯**（春節等長假官方日期會停在封關日，
  超過 7 天只印註記；同一資料日重複抓到會因 Last-Modified 沒變而略過）。
- 解析後列數低於下限（上市日線 500、上櫃日線 400、上櫃融資 300、上市融資 300）→ 視為失敗不存（官方改欄名／回殘缺資料時不能悄悄寫入空表）。
- 同一資料日被「較新的 Last-Modified」覆蓋時，新列數若不到舊列數的 90% → 不覆蓋、發警告（`shrunk`），避免半成品換掉完整的一天。
- 每列記 `last_modified`（HTTP 標頭，官方最後一次重新產生檔案的時間）與 `fetched_at`；每次請求另記一行 `openapi_fetch_log.jsonl`
  （端點、HTTP 狀態、資料日、Last-Modified、列數），累積「官方每天什麼時候更新」的實測分布。
- 同一 (資料集, 資料日) 若 Last-Modified 比已存的新 → 整天覆蓋（官方事後更正）；一樣或較舊 → 略過，重跑冪等。
  例外：src 等級較高者（上櫃 openapi_dc 對舊端點存下的 openapi）無視 Last-Modified 覆蓋；反方向略過；縮水保護不分來源。
  舊端點量額偏低的原因見 docs/data-fix.md B4 第 3 點（6488 實測：舊端點不含零股、盤後、鉅額，daily_close_quotes 含鉅額）。
- 每次結尾對交易日曆檢查近 14 天有沒有缺的交易日，有洞就發 `::warning::`（不失敗；網站端點補得回來）。
- 單一端點失敗不影響其他端點；三個 OpenAPI 端點全失敗才非零退出（上市融資是網站端點，不計入，失敗只發警告）。

## 預告表（2026-10-07 加）
上市 `TWT48U_ALL`、上櫃 `tpex_exright_prepost` 兩份除權除息預告表，每次執行抓一次（同市場至少間隔 3 小時），存 `openapi_forecast.jsonl`；
內容與上一份相同只記抓取時間（same_as）。預告表只有未來事件、沒有歷史，用來事後比對「預告值 vs 官方結果表」，並備好當天事件的還原因子。

輸出（`data/selfhost/`）：`openapi_prices.parquet`、`openapi_margin.parquet`、`openapi_inst.parquet`（三大法人，網站端點帶日期，台北 18:00 起）、`openapi_forecast.jsonl`、`openapi_fetch_log.jsonl`。
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
FORECAST = SH / "openapi_forecast.jsonl"
INST = SH / "openapi_inst.parquet"
UA = {"User-Agent": "Mozilla/5.0"}
TWSE_DAY = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_DAY = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TPEX_MARGIN = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"
TWSE_FORECAST = "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"      # 上市除權除息預告表（只有未來事件）
TPEX_FORECAST = "https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost"           # 上櫃除權除息預告表
FORECAST_MIN_GAP_HOURS = 3     # 同一市場兩次抓取至少間隔這麼久（官方請求要節制）
TZ = ZoneInfo("Asia/Taipei")
MAX_AGE_DAYS = 7           # 超過只印註記
MIN_ROWS = {"twse_day": 500, "tpex_day": 400, "tpex_margin": 300, "twse_margin": 300, "twse_inst": 500, "tpex_inst": 300}
SHRINK_RATIO = 0.9
SRC_TPEX_DC = "openapi_dc"   # 上櫃改用 daily_close_quotes 後的標記；舊端點（src=openapi）存下的同一天量額偏低，要能被它覆蓋
SRC_WEB_MARGN = "web_mi_margn"
MARGN_TODAY_AFTER_HOUR = 22     # 上市融資約台北 21:00～22:00 才公布：白天到 22:00 前整段不打（今天、前一天都不打）；實測輪詢後再調
INST_FROM_HOUR = 18            # 三大法人約台北 16:15～17:00 才齊（使用者設定 18:00 起）；之前不請求
INST_QUIET_FROM_HOUR = 8        # 隔日清晨班（04:00）補前一晚漏的；08:00～18:00 不請求
INST_MAX_MISMATCH = 0.02        # 法人合計恆等式（外資＋外資自營＋投信＋自營＝合計）不符比例超過這個就不存（多半是欄位錯位）
MARGN_QUIET_FROM_HOUR = 8       # 隔日清晨班（04:00）仍收，用來補前一晚漏的與官方隔日調帳；08:00～22:00 之間一律不打
SRC_RANK = {"openapi": 0, SRC_TPEX_DC: 1}   # 只准單向升級：等級高的可無視 Last-Modified 覆蓋等級低的，反方向一律略過
GAP_WINDOW_DAYS = 14

PRICE_COLS = ["ticker", "market", "date", "open", "high", "low", "close", "volume", "value", "chg", "next_ref", "next_limit_up", "next_limit_down",
              "src", "last_modified", "fetched_at"]   # next_*：上櫃 daily_close_quotes 的官方次日參考價／漲跌停（上市沒有＝NaN）；除權息前一晚可直接拿到官方因子
INST_OA_COLS = ["date", "ticker", "market", "foreign_net", "fi_prop_net", "trust_net", "dealer_net", "total_net", "src", "fetched_at"]
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
            nxt = (None, None, None)
        else:
            code, o, h, l, c = r.get("SecuritiesCompanyCode"), r.get("Open"), r.get("High"), r.get("Low"), r.get("Close")
            vol, val, chg = r.get("TradingShares"), r.get("TransactionAmount"), r.get("Change")
            nxt = (r.get("NextReferencePrice"), r.get("NextLimitUp"), r.get("NextLimitDown"))
        code = str(code or "").strip()
        close = _num(c)
        if not (code.isdigit() and len(code) == 4) or close is None or close <= 0:     # 與 raw_prices 同規則：4 碼、有成交價
            continue
        out.append({"ticker": code, "market": market, "date": pd.Timestamp(d),
                    "open": _num(o) or close, "high": _num(h) or close, "low": _num(l) or close, "close": close,
                    "volume": _num(vol) or 0.0, "value": _num(val) or 0.0, "chg": _num(chg),
                    "next_ref": _num(nxt[0]), "next_limit_up": _num(nxt[1]), "next_limit_down": _num(nxt[2]),
                    "src": "openapi" if market == "TW" else SRC_TPEX_DC, "last_modified": lm, "fetched_at": fetched})
    df = pd.DataFrame(out, columns=PRICE_COLS)
    return df.astype({"next_ref": float, "next_limit_up": float, "next_limit_down": float})   # 全是 None 時也要 float，否則 parquet 會存成 null 型別


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


def _atomic_text(p: Path, text: str) -> None:
    """同 _atomic_parquet：先寫暫存檔再換名，被取消時不留下寫到一半的檔。"""
    tmp = p.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
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


def margin_candidates(today: date, hour: int = 24) -> list[date]:
    """上市融資要試的日期：前一個平日（已公布）＋今天（台北 MARGN_TODAY_AFTER_HOUR 點之後才試）。週末不試；國定假日會回「沒有符合條件」，不算錯。"""
    out = [today] if today.weekday() < 5 and hour >= MARGN_TODAY_AFTER_HOUR else []
    d = today - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return out + [d]


def web_margin_to_openapi_schema(df: pd.DataFrame, fetched) -> pd.DataFrame:
    """selfhost_chips.margin_twse 的輸出 → 本檔 openapi_margin 欄位（多 src／last_modified／fetched_at）。"""
    out = df.copy()
    out["src"] = SRC_WEB_MARGN
    out["last_modified"] = pd.NaT
    out["fetched_at"] = fetched
    return out[MARGIN_COLS]


def _stale_fetch(table_rows: pd.DataFrame, d: date) -> bool:
    """該日最後一次抓取早於 D+1 台北 00:00（＝D 16:00 UTC）→ 還沒過「官方隔日調帳」窗口，值得再打一次。"""
    fa = table_rows["fetched_at"].max()
    return pd.isna(fa) or pd.Timestamp(fa) < pd.Timestamp(d) + pd.Timedelta(hours=16)


def _same_content(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    num = [c for c in MARGIN_COLS if c not in ("ticker", "market", "date", "note", "src", "last_modified", "fetched_at")]
    x = a.sort_values("ticker").reset_index(drop=True)[["ticker", *num]]
    y = b.sort_values("ticker").reset_index(drop=True)[["ticker", *num]]
    return x.shape == y.shape and x.equals(y)


def collect_twse_margin(today: date, fetched, table: pd.DataFrame, hour: int = 24) -> tuple[pd.DataFrame, bool]:
    """回 (新表, 是否有變更)。沒資料＝尚未公布，只記 log；回應日期不符或欄位改版→ margin_twse 回 None → 警告。
    已存的 (TW, 日)：若最後抓取早於隔日 00:00（台北）就再打一次，內容有差才整天替換（官方隔日調帳／首次公布不完整），
    縮水（<90%）不覆蓋；過了該窗口就不再打。web 來源沒有 Last-Modified，所以不走 merge_day 的時間判斷。"""
    if MARGN_QUIET_FROM_HOUR <= hour < MARGN_TODAY_AFTER_HOUR:
        return table, False                      # 官方還沒公布的時段：不請求、不記 log
    if str(Path(__file__).parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).parent))
    import selfhost_chips as sc  # noqa: PLC0415
    changed = False
    for d in margin_candidates(today, hour):
        entry = {"fetched_at": str(fetched), "endpoint": "twse_margin", "data_date": str(d)}
        mask = (table["market"] == "TW") & (table["date"] == pd.Timestamp(d)) if len(table) else pd.Series([], dtype=bool)
        stored = bool(mask.any())
        if stored and not _stale_fetch(table.loc[mask], d):
            continue
        df = sc.margin_twse(d)
        if df is None:
            entry["result"] = "失敗（連線／日期不符／欄位改版）"
            print(f"::warning::上市融資 MI_MARGN {d} 失敗（連線、回應日期不符或欄位改版），不存", file=sys.stderr)
        elif df.empty:
            entry["result"] = "尚未公布（沒有符合條件）"
            print(f"[openapi] twse_margin：{d} 尚未公布或休市")
        elif len(df) < MIN_ROWS["twse_margin"]:
            entry["result"] = f"失敗：只有 {len(df)} 列（下限 {MIN_ROWS['twse_margin']}），不存"
            print(f"::warning::上市融資 MI_MARGN {d} 只有 {len(df)} 列（下限 {MIN_ROWS['twse_margin']}）——殘缺？不存", file=sys.stderr)
        elif stored and len(df) < SHRINK_RATIO * int(mask.sum()):
            entry["result"] = f"shrunk {len(df)} 列"
            print(f"::warning::上市融資 MI_MARGN {d} 重打只有 {len(df)} 列（已存 {int(mask.sum())}），不覆蓋", file=sys.stderr)
        elif stored and _same_content(table.loc[mask], df):
            table.loc[mask, "fetched_at"] = fetched                  # 內容沒變：只更新抓取時間，窗口過後就不再重打
            changed = True
            entry["rows"], entry["result"] = len(df), "unchanged（更新抓取時間）"
            print(f"[openapi] twse_margin：資料日 {d}、{len(df)} 列、內容沒變")
        else:
            new = web_margin_to_openapi_schema(df, fetched)
            table = pd.concat([table.loc[~mask], new], ignore_index=True).sort_values(["date", "market", "ticker"]).reset_index(drop=True)[MARGIN_COLS]
            changed = True
            action = "replaced" if stored else "added"
            entry["rows"], entry["result"] = len(df), f"{action} {len(df)} 列"
            print(f"[openapi] twse_margin：資料日 {d}、{len(df)} 列、{action}")
        _log(entry)
    return table, changed


def _roc7_iso(x: str) -> str:
    x = str(x).strip()
    return date(int(x[:-4]) + 1911, int(x[-4:-2]), int(x[-2:])).isoformat()


def normalize_forecast(rows: list[dict], market: str) -> list[dict]:
    """預告表 → 同一種 rows：code、name、ex（除權除息日 ISO）、kind、stock_ratio、sub_ratio、sub_price、cash，
    另存 cash_raw／sub_price_raw 原字串（上市 '' 可能是「不適用」也可能是「待公告」，上櫃「尚未公告」＝待公告、0.00000000＝不適用，
    轉成數字後分不出來）。壞掉的列跳過並計數（整份回應全壞才拋例外）；結果依 (ex, code) 排序，內容比對不受官方排列順序影響。
    官方預告表**沒有參考價**，要用「前收 − 現金股利」等公式自己算（上市截斷到分、上櫃四捨五入到分，2026-10-07 實測各 100% 吻合結果表）。"""
    out, bad = [], 0
    for r in rows:
        try:
            if market == "TW":
                g = {"code": r["Code"], "name": r.get("Name", ""), "ex": _roc7_iso(r["Date"]), "kind": r.get("Exdividend", ""),
                     "stock_ratio": r.get("StockDividendRatio"), "sub_ratio": r.get("SubscriptionRatio"),
                     "sub_price": r.get("SubscriptionPricePerShare"), "cash": r.get("CashDividend")}
            else:
                g = {"code": r["SecuritiesCompanyCode"], "name": r.get("CompanyName", ""), "ex": _roc7_iso(r["ExRrightsExDividendDate"]),
                     "kind": r.get("ExRrightsExDividend", ""), "stock_ratio": r.get("StockDividendRatio"),
                     "sub_ratio": r.get("SubscriptionRatioToNewSharesIssued"), "sub_price": r.get("SubscriptionPricePerShare"),
                     "cash": r.get("CashDividend")}
            g["cash_raw"], g["sub_price_raw"] = str(g["cash"] or "").strip(), str(g["sub_price"] or "").strip()
            for k in ("stock_ratio", "sub_ratio", "sub_price", "cash"):
                g[k] = _num(g[k])
        except (KeyError, ValueError, TypeError):
            bad += 1
            continue
        out.append(g)
    if bad:
        print(f"::warning::預告表 {market} 有 {bad} 列解析失敗，已跳過", file=sys.stderr)
    if rows and not out:
        raise ValueError("預告表整份解析失敗（欄名改版？）")
    return sorted(out, key=lambda g: (g["ex"], g["code"]))


def _load_forecast() -> list[dict]:
    if not FORECAST.exists():
        return []
    out = []
    for i, x in enumerate(FORECAST.read_text(encoding="utf-8").splitlines()):
        if not x.strip():
            continue
        try:
            out.append(json.loads(x))
        except json.JSONDecodeError:
            print(f"::warning::openapi_forecast.jsonl 第 {i + 1} 行壞掉（截斷？），已跳過", file=sys.stderr)
    return out


def collect_forecasts(fetched: pd.Timestamp, recs: list[dict]) -> tuple[list[dict], bool]:
    """每日預告表快照（上市＋上櫃）。每次抓取記一筆 {_fetched, market, source, n, rows|None, same_as}：
    內容與同市場上一份相同 → rows 記 None、same_as 指向上一份的 _fetched（檔案不膨脹，但抓取時間全留）。
    同市場兩次抓取至少間隔 FORECAST_MIN_GAP_HOURS；失敗只警告。預告表只有未來事件，漏抓就補不回來。"""
    changed = False
    for market, url in (("TW", TWSE_FORECAST), ("TWO", TPEX_FORECAST)):
        mine = [r for r in recs if r.get("market") == market]
        if mine and fetched - pd.Timestamp(mine[-1]["_fetched"]) < pd.Timedelta(hours=FORECAST_MIN_GAP_HOURS):
            continue
        entry = {"fetched_at": str(fetched), "endpoint": f"forecast_{market}"}
        try:
            r = requests.get(url, headers=UA, timeout=60)
            r.raise_for_status()
            raw = r.json()
            if not isinstance(raw, list):
                raise ValueError("回應不是列表")
            rows = normalize_forecast(raw, market)
        except Exception as e:      # noqa: BLE001
            entry["result"] = f"失敗：{str(e)[:100]}"
            print(f"::warning::預告表 {market} 失敗：{str(e)[:100]}（預告表只有未來事件，漏抓補不回來）", file=sys.stderr)
            _log(entry)
            continue
        prev_full = next((x for x in reversed(mine) if x.get("rows") is not None), None)
        same = prev_full is not None and prev_full["rows"] == rows
        recs.append({"_fetched": str(fetched), "market": market, "source": "openapi", "n": len(rows),
                     "rows": None if same else rows, "same_as": prev_full["_fetched"] if same else None})
        entry["rows"], entry["result"] = len(rows), "同上一份" if same else "有變動"
        print(f"[openapi] forecast_{market}：{len(rows)} 件、{entry['result']}")
        _log(entry)
        changed = True
    return recs, changed


def inst_candidates(today: date, hour: int) -> list[date]:
    """三大法人要試的日期：台北 18:00 之後試今天；隔日清晨班（hour < 8）補前一個平日；08:00～18:00 不請求。週末不試。"""
    if INST_QUIET_FROM_HOUR <= hour < INST_FROM_HOUR:
        return []
    out = []
    if hour >= INST_FROM_HOUR and today.weekday() < 5:
        out.append(today)
    if hour < INST_QUIET_FROM_HOUR:
        d = today - timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        out.append(d)
    return out


def inst_mismatch(df: pd.DataFrame) -> float:
    """法人合計恆等式不符比例：外資＋外資自營＋投信＋自營 ＝ 三大法人合計（2026-10-05 實測上市 1,088／上櫃 795 檔全部吻合）。"""
    x = df.dropna(subset=["total_net"])
    if x.empty:
        return 1.0
    s = x[["foreign_net", "fi_prop_net", "trust_net", "dealer_net"]].fillna(0).sum(axis=1)
    return float(((s - x["total_net"]).abs() >= 1).mean())


def collect_inst(today: date, fetched, table: pd.DataFrame, hour: int = 24) -> tuple[pd.DataFrame, bool]:
    """每日三大法人（上市 T86、上櫃 insti/dailyTrade，都是網站端點、帶日期、回應回傳自己的日期；OpenAPI 沒有可用的）。
    取到就停：已存的 (市場, 日) 不再請求；沒資料＝尚未公布，只記 log；失敗只警告（網站端點補得回來）；
    恆等式不符超過 INST_MAX_MISMATCH 或列數不足 → 不存。重用 selfhost_chips 的解析（欄名辨識、日期斷言）。"""
    cands = inst_candidates(today, hour)
    if not cands:
        return table, False
    if str(Path(__file__).parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).parent))
    import selfhost_chips as sc  # noqa: PLC0415
    changed = False
    have = {(m, x.date()) for m, x in zip(table["market"], table["date"])} if len(table) else set()
    for d in cands:
        for market, fn, name, src in (("TW", sc.inst_twse, "twse_inst", "web_t86"), ("TWO", sc.inst_tpex, "tpex_inst", "web_tpex_insti")):
            if (market, d) in have:
                continue
            entry = {"fetched_at": str(fetched), "endpoint": name, "data_date": str(d)}
            df = fn(d)
            if df is None:
                entry["result"] = "失敗（連線／日期不符／欄位改版）"
                print(f"::warning::三大法人 {name} {d} 失敗（連線、回應日期不符或欄位改版），不存", file=sys.stderr)
            elif df.empty:
                entry["result"] = "尚未公布（沒有資料）"
                print(f"[openapi] {name}：{d} 尚未公布或休市")
            elif len(df) < MIN_ROWS[name]:
                entry["result"] = f"失敗：只有 {len(df)} 列（下限 {MIN_ROWS[name]}），不存"
                print(f"::warning::三大法人 {name} {d} 只有 {len(df)} 列（下限 {MIN_ROWS[name]}）——殘缺？不存", file=sys.stderr)
            elif (mm := inst_mismatch(df)) > INST_MAX_MISMATCH:
                entry["result"] = f"失敗：合計恆等式不符 {mm:.1%}，不存"
                print(f"::warning::三大法人 {name} {d} 合計恆等式不符 {mm:.1%}（欄位錯位？），不存", file=sys.stderr)
            else:
                new = df[["date", "ticker", "market", "foreign_net", "fi_prop_net", "trust_net", "dealer_net", "total_net"]].copy()
                new["src"], new["fetched_at"] = src, fetched
                table = (pd.concat([table, new], ignore_index=True) if len(table) else new).sort_values(["date", "market", "ticker"]).reset_index(drop=True)[INST_OA_COLS]
                changed = True
                entry["rows"], entry["result"] = len(new), f"added {len(new)} 列（恆等式不符 {mm:.2%}）"
                print(f"[openapi] {name}：資料日 {d}、{len(new)} 列、added（恆等式不符 {mm:.2%}）")
            _log(entry)
    return table, changed


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
    try:
        tables[MARGIN], c2 = collect_twse_margin(today, fetched, tables[MARGIN], now.hour)
        changed = changed or c2
    except Exception as e:      # noqa: BLE001  上市融資失敗不拖垮 OpenAPI 三個端點
        print(f"::warning::上市融資 MI_MARGN 收集例外：{str(e)[:120]}", file=sys.stderr)
    inst_changed = False
    inst_t = _read(INST, INST_OA_COLS)
    try:
        if os.environ.get("INST_DISABLED"):
            print("::warning::三大法人收集已停用（Release 缺 openapi_inst.parquet 但 fetch log 有寫入記錄）——其他端點照跑，請人工處理", file=sys.stderr)
        else:
            inst_t, inst_changed = collect_inst(today, fetched, inst_t, now.hour)
        if inst_changed:
            SH.mkdir(parents=True, exist_ok=True)
            _atomic_parquet(inst_t, INST)
    except Exception as e:      # noqa: BLE001  法人失敗不拖垮其他端點（網站端點帶日期，補得回來）
        print(f"::warning::三大法人收集例外：{str(e)[:120]}", file=sys.stderr)
    forecast_changed = False
    try:
        recs, forecast_changed = collect_forecasts(fetched, _load_forecast())
        if forecast_changed:
            SH.mkdir(parents=True, exist_ok=True)
            _atomic_text(FORECAST, "\n".join(json.dumps(x, ensure_ascii=False) for x in recs) + "\n")
    except Exception as e:      # noqa: BLE001  預告表失敗不拖垮其他端點
        print(f"::warning::預告表收集例外：{str(e)[:120]}", file=sys.stderr)
    SH.mkdir(parents=True, exist_ok=True)
    if changed:         # 沒有變更就不寫檔、workflow 也不重傳 parquet（--clobber 是先刪再傳，傳到一半失敗會永久丟歷史）
        for p, t in tables.items():
            if len(t):
                _atomic_parquet(t, p)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
            f.write(f"forecast_changed={'true' if forecast_changed else 'false'}\n")
            f.write(f"inst_changed={'true' if inst_changed else 'false'}\n")
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import last_trading_day_guard as g  # noqa: PLC0415
        closed = g.fetch_closed()
    except Exception:       # noqa: BLE001
        closed = None
    tables[INST] = inst_t
    for name, path, mk in (("上市日線", PRICES, "TW"), ("上櫃日線", PRICES, "TWO"), ("上櫃融資券", MARGIN, "TWO"), ("上市融資券", MARGIN, "TW"),
                           ("上市三大法人", INST, "TW"), ("上櫃三大法人", INST, "TWO")):
        t = tables[path]
        t = t[t["market"] == mk] if len(t) else t
        if not len(t):                      # 累積檔還是空的（首日、端點整個失敗）→ 不查，免得報出假缺口
            continue
        have = {x.date() for x in t["date"].unique()}
        gaps = [d for d in missing_trading_days(have, today, closed) if d >= min(have)]
        if gaps:
            print(f"::warning::OpenAPI {name} 累積檔缺交易日：{', '.join(map(str, gaps))}（網站端點補得回來；上市融資這支不會自動補，需手動）", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
