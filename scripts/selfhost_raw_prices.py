"""自建上游 P1：官方**未還原**日線（上市 + 上櫃）依日期收集 → `data/selfhost/raw_prices.parquet`。

## 為什麼存在
上游 data_pack 的還原價有「還原接縫」缺陷（見 `tw-swing/docs/analysis/tw-stock-scanner-1005-analysis.md`）：
`updater.py` 只重抓最近 7 天，除息日前 ~8 天以上的歷史留在舊基準。要偵測／訂正，需要官方未還原價當裁判。
`PLAN_OWN_UPSTREAM.md` P1 本來就要做這件事；這支是它的第一個 collector（只收價，法人／融資券之後再加）。

## 資料源（2026-10-05 實測，見 `tw-swing/docs/reference/twse_tpex_pitfalls.md` §G）
- 上市：`www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=YYYYMMDD&type=ALLBUT0999&response=json`
  取 title 含「每日收盤行情」那張表；回應頂層 `date` 必須等於請求日。
- 上櫃：`www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date=YYYY/MM/DD&response=json`
  （⚠️ 不是只回最新日的 openapi 版）；回應頂層 `date` 必須等於請求日；休市日 `totalCount=0`。

## 規矩
- 請求帶日期就斷言回應日期（日期不符 → 丟棄並警告，絕不存）。
- 只存「檔案裡還沒有的平日」→ 重複跑冪等、漏跑自癒；休市日（空表）略過、不重試。
- 單日上市或上櫃任一邊失敗 → 該日**整天不寫**（all-or-nothing），下次再補，不留半邊。
- 代號只留 4 碼純數字（跟上游宇宙規則一致，見 UPSTREAM_PRACTICES_AUDIT P5）。

用法：
    python scripts/selfhost_raw_prices.py                       # 補近 REFRESH_DAYS 天缺的
    python scripts/selfhost_raw_prices.py --start 2026-06-01    # 首次回補
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
import _retry  # noqa: E402

TWSE = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALLBUT0999&response=json"
TPEX = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={d}&response=json"
OUT = Path(__file__).resolve().parents[1] / "data" / "selfhost" / "raw_prices.parquet"
REFRESH_DAYS = 14
RECHECK_DAYS = 3
SLEEP = 2.0
UA = {"User-Agent": "Mozilla/5.0"}
# MI_INDEX 「沒有資料」的 stat（2026-10-08 實測）：休市日（10/4 週日、6/19 端午）回第一句；未來日期（10/9）回第二句。
# 其他 stat 一律當失敗（回 None）——不可把不認得的回應當休市吞掉（tw-stock-data CLAUDE.md §二：靜默失敗都長成 200）。
TWSE_NO_DATA = ("沒有符合條件的資料", "查詢日期大於今日")
# chg：官方當日「漲跌價差」（有正負號；事件日標記為 X／除息 時為空）。close−chg＝官方當日參考價——
# 跟我們「前一筆收盤」不同時（無成交後、事件日），只有它能說明價格跳動是否合乎漲跌幅限制。
COLS = ["ticker", "market", "date", "open", "high", "low", "close", "volume", "value", "chg"]
NT_COLS = ["ticker", "market", "date", "volume", "value", "src"]
# 官方有列、但當天沒有成交價（冷門股無成交、或只有零股成交）：不進 raw_prices（那裡每列都有價），改記在旁表 notrade.parquet。
# 為什麼要留：①「缺日」才分得出是市場事實（無成交）還是漏抓；②有量無價的零股成交仍是真的成交量（算均量要納入、算均線不可）。
# 見 tw-stock-data READ_CONTRACT「close 可能是空字串」。每次 fetch 後由 main() 取走並清空。
NOTRADE: list[dict] = []
# 官方在「參考價被重設」的日子，行情表的漲跌欄不是 +/-數字而是標記：上市 `X`（無比價；除權息、減資、轉板首日、無成交後復交易…），
# 上櫃直接寫「除息／除權／除權息」。這是官方自己標出的事件日——跟我們的事件表互為獨立的對帳基準（事件簿 `refmark_no_event`）。
# 只記非一般漲跌（+／−／數字）的列，旁表 refmark.parquet，量很小（歷史約 2 萬列）。
REFMARK: list[dict] = []
RM_COLS = ["ticker", "market", "date", "mark", "chg", "src"]


def _get(url: str, retries: int = _retry.TRIES) -> dict | None:
    """用 requests（certifi 憑證庫）——TPEx 憑證鏈缺中繼憑證，urllib 的系統憑證庫會驗證失敗。"""
    for i in range(retries):
        try:
            r = requests.get(url, headers=UA, timeout=40)
            r.raise_for_status()
            return r.json()
        except Exception as e:   # 網路／JSON 錯誤 → 退避重試
            print(f"  請求失敗（第 {i + 1} 次）：{str(e)[:80]}", file=sys.stderr)
            _retry.wait_after_failure(i)
    return None


def _num(x) -> float | None:
    s = str(x).replace(",", "").strip()
    if s in ("", "--", "---", "----", "X0.00", "nan"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def _mark(sign_cell, diff_cell=None) -> tuple[str, float | None]:
    """漲跌欄 → (標記, 漲跌價差)。標記為空字串＝一般漲跌。上市：漲跌(+/-) 欄含 HTML（`<p>X</p>`、`<p style=color:red>+</p>`）；
    上櫃：單一「漲跌」欄，一般是 `-0.80 ` 這種數字，事件日是文字（`除息 `）。"""
    import re as _re
    sg = _re.sub(r"<[^>]+>", "", str(sign_cell)).strip()
    if diff_cell is None:                                  # 上櫃：單欄
        if sg in ("", "---", "--"):
            return "", None
        v = _num_signed(sg)
        return ("", v) if v is not None else (sg, None)
    v = _num_signed(diff_cell)                              # 上市：符號欄 + 價差欄
    if sg in ("+", "-", ""):
        return "", (v if sg != "-" or v is None else -abs(v))
    return sg, v


def _num_signed(x) -> float | None:
    s = str(x).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _rows(table: dict, idx: dict[str, str], market: str, d: str) -> pd.DataFrame:
    """`idx`: 標準欄名 → 官方欄名。用欄名（不是固定位置）取欄，耐改版。
    可選鍵 `sign`／`diff`：漲跌欄（見 `_mark`），有的話把非一般漲跌的列記進 REFMARK 旁表。"""
    fields = table["fields"]
    opt = {k: idx[k] for k in ("sign", "diff") if k in idx and idx[k] in fields}
    pos = {k: fields.index(v) for k, v in idx.items() if k not in ("sign", "diff")}
    sign_i = fields.index(opt["sign"]) if "sign" in opt else None
    diff_i = fields.index(opt["diff"]) if "diff" in opt else None
    out = []
    for r in table["data"]:
        code = str(r[0]).strip()
        if not (code.isdigit() and len(code) == 4):
            continue
        close = _num(r[pos["close"]])
        if close is None:         # 當日無成交價 → 記旁表，不進 raw_prices
            NOTRADE.append({"ticker": code, "market": market, "date": pd.Timestamp(d),
                            "volume": _num(r[pos["volume"]]) or 0.0, "value": _num(r[pos["value"]]) or 0.0, "src": "official"})
            continue
        chg = None
        if sign_i is not None:
            mk, chg = _mark(r[sign_i], r[diff_i] if diff_i is not None else None)
            if mk:
                REFMARK.append({"ticker": code, "market": market, "date": pd.Timestamp(d), "mark": mk, "chg": chg, "src": "official"})
                chg = None
        out.append({
            "ticker": code, "market": market, "date": pd.Timestamp(d),
            "open": _num(r[pos["open"]]) or close, "high": _num(r[pos["high"]]) or close,
            "low": _num(r[pos["low"]]) or close, "close": close,
            "volume": _num(r[pos["volume"]]) or 0.0, "value": _num(r[pos["value"]]) or 0.0, "chg": chg,
        })
    return pd.DataFrame(out, columns=COLS)


def fetch_twse(d: date) -> pd.DataFrame | None:
    """None＝抓取失敗；空表＝休市。"""
    ymd = d.strftime("%Y%m%d")
    j = _get(TWSE.format(d=ymd))
    if j is None:
        return None
    if j.get("stat") != "OK":
        if any(s in str(j.get("stat")) for s in TWSE_NO_DATA):
            return pd.DataFrame(columns=COLS)       # 休市／尚未公布／未來日期（非錯誤）
        print(f"::warning::TWSE {ymd} 回應 stat={j.get('stat')!r}，不是已知的「沒有資料」，當失敗處理", file=sys.stderr)
        return None
    if str(j.get("date")) != ymd:
        print(f"::warning::TWSE {ymd} 回應日期 {j.get('date')} 不符，丟棄", file=sys.stderr)
        return None
    for t in j.get("tables", []):
        if t.get("title") and "每日收盤行情" in t["title"] and t.get("data"):
            return _rows(t, {"open": "開盤價", "high": "最高價", "low": "最低價", "close": "收盤價",
                             "volume": "成交股數", "value": "成交金額",
                             "sign": "漲跌(+/-)", "diff": "漲跌價差"}, "TW", ymd)
    return pd.DataFrame(columns=COLS)


def fetch_tpex(d: date) -> pd.DataFrame | None:
    ymd = d.strftime("%Y%m%d")
    j = _get(TPEX.format(d=d.strftime("%Y/%m/%d")))
    if j is None:
        return None
    if str(j.get("date")) != ymd:
        print(f"::warning::TPEx {ymd} 回應日期 {j.get('date')} 不符，丟棄", file=sys.stderr)
        return None
    tabs = j.get("tables") or []
    if not tabs or not tabs[0].get("totalCount") or not tabs[0].get("data"):
        return pd.DataFrame(columns=COLS)           # 休市
    return _rows(tabs[0], {"open": "開盤", "high": "最高", "low": "最低", "close": "收盤",
                           "volume": "成交股數", "value": "成交金額(元)", "sign": "漲跌"}, "TWO", ymd)


def collect_day(d: date, market: str = "both") -> pd.DataFrame | None:
    """上市＋上櫃合併；任一邊失敗 → None（整天不寫）；兩邊都空 → 空表（休市）。
    `market` 為 TW／TWO 時只問該市場（平行回補用：兩個市場是不同主機、限流分開，各跑一條線互不拖累）。"""
    if market == "TW":
        a = fetch_twse(d)
        time.sleep(SLEEP)
        return a
    if market == "TWO":
        b = fetch_tpex(d)
        time.sleep(SLEEP)
        return b
    a = fetch_twse(d)
    time.sleep(SLEEP)
    if d.weekday() == 5 and a is not None and a.empty:
        return pd.DataFrame(columns=COLS)       # 週六：上市空表＝非補班日，不再問上櫃（省請求）
    b = fetch_tpex(d)
    time.sleep(SLEEP)
    if a is None or b is None:
        return None
    if a.empty != b.empty:       # 只有一邊有資料 = 異常（其中一邊壞了），不存
        print(f"::warning::{d} 上市 {len(a)} 檔 / 上櫃 {len(b)} 檔，只有單邊有資料，整天不寫", file=sys.stderr)
        return None
    return pd.concat([a, b], ignore_index=True)


def _flush_notrade() -> None:
    """把 NOTRADE 併進旁表（累積型：只增不減；同鍵以最新一次為準）。檔名跟著 OUT（單市場線寫 notrade_TW／TWO）。"""
    if not NOTRADE:
        return
    path = OUT.with_name(OUT.name.replace("raw_prices", "notrade"))
    new = pd.DataFrame(NOTRADE, columns=NT_COLS)
    NOTRADE.clear()
    old = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=NT_COLS)
    allp = pd.concat([old, new], ignore_index=True).drop_duplicates(["ticker", "market", "date"], keep="last")
    allp.sort_values(["date", "market", "ticker"]).reset_index(drop=True).to_parquet(path, index=False, compression="zstd")


def _flush_refmark() -> None:
    """同 _flush_notrade：累積型、同鍵以最新為準；檔名跟著 OUT。"""
    if not REFMARK:
        return
    path = OUT.with_name(OUT.name.replace("raw_prices", "refmark"))
    new = pd.DataFrame(REFMARK, columns=RM_COLS)
    REFMARK.clear()
    old = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=RM_COLS)
    allp = pd.concat([old, new], ignore_index=True).drop_duplicates(["ticker", "market", "date"], keep="last")
    allp.sort_values(["date", "market", "ticker"]).reset_index(drop=True).to_parquet(path, index=False, compression="zstd")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", help="YYYY-MM-DD；預設今天往前 REFRESH_DAYS 天")
    ap.add_argument("--end", help="YYYY-MM-DD；預設今天")
    ap.add_argument("--market", choices=["both", "TW", "TWO"], default="both",
                    help="平行回補用：只收單一市場，輸出到 raw_prices_<市場>.parquet（之後用 selfhost_merge.py 合併）")
    a = ap.parse_args(argv)
    end = datetime.strptime(a.end, "%Y-%m-%d").date() if a.end else date.today()
    start = datetime.strptime(a.start, "%Y-%m-%d").date() if a.start else end - timedelta(days=REFRESH_DAYS)

    global OUT
    if a.market != "both":
        OUT = OUT.with_name(f"raw_prices_{a.market}.parquet")
    old = pd.read_parquet(OUT) if OUT.exists() else pd.DataFrame(columns=COLS)
    have = set(pd.to_datetime(old["date"]).dt.date) if len(old) else set()
    # 官方成交量收盤後會更正（實測 2026-10-05 有 17 檔事後改過）→ 最近 RECHECK_DAYS 天每次重抓覆蓋
    have = {d for d in have if d <= end - timedelta(days=RECHECK_DAYS)}
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    # 含週六：補行上班日（例：2016-01-30、2017-09-30、2018-03-31、2018-12-22）股市照常交易，上游母表漏了這些日子
    todo = [d for d in days if d.weekday() < 6 and d not in have]
    print(f"範圍 {start}~{end}；檔案已有 {len(have)} 天；待抓平日 {len(todo)} 天")

    new, failed, closed = [], [], 0

    def flush() -> None:
        """寫檔（續跑友善：每 10 天存一次，被中斷也不白跑）。"""
        nonlocal old, new
        if not new:
            return
        OUT.parent.mkdir(parents=True, exist_ok=True)
        allp = pd.concat([old] + new, ignore_index=True)
        allp = allp.drop_duplicates(["ticker", "market", "date"], keep="last")
        allp = allp.sort_values(["date", "market", "ticker"]).reset_index(drop=True)
        allp.to_parquet(OUT, index=False, compression="zstd")
        old, new = allp, []
        print(f"  已寫入 {OUT.name}（{len(allp)} 列，{allp['date'].nunique()} 天）", flush=True)
        _flush_notrade()
        _flush_refmark()

    for i, d in enumerate(todo, 1):
        df = collect_day(d, a.market)
        if df is None:
            failed.append(d)
        elif df.empty:
            closed += 1
        else:
            new.append(df)
            print(f"  {d} 上市 {int((df.market == 'TW').sum())} 檔 / 上櫃 {int((df.market == 'TWO').sum())} 檔", flush=True)
        if i % 10 == 0:
            flush()
    flush()
    print(f"休市 {closed} 天；失敗 {len(failed)} 天 {[str(x) for x in failed]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
