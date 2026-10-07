"""自建上游 P2 地基：公司行為事件表 → `data/selfhost/corp_actions.parquet`。

每一檔、每一次影響股價連續性的事件（除息／除權／權息／面額變更／分割／反分割／減資）一列，
**記來源與原始欄位**，之後任何還原價的接縫都能追到「哪個事件、哪個來源、因子多少」。

## 來源（2026-10-05 逐一實測）
| source | 內容 | 範圍 | 取法 |
| :-- | :-- | :-- | :-- |
| `twse_ex` | TWSE `exRight/TWT49U` 除權息計算結果（前收、參考價） | 上市，≥ 2015 | 月切段、免金鑰 |
| `tpex_ex` | TPEx `bulletin/exDailyQ` 除權息計算結果（含現金增資欄） | 上櫃，≥ 2015 | 月切段、免金鑰 |
| `twse_red` | TWSE `reducation/TWTAUU`（⚠️ 官方拼字如此）減資恢復買賣參考價（含「除權參考價」＝減資併現金增資時當天實際適用的價） | 上市，≥ 2011（實測 2015 有資料） | 年切段、免金鑰、**免逐檔** |
| `tpex_red` | TPEx `bulletin/revivt` 減資（日期為民國 7 碼） | 上櫃，≥ ~2013 | 年切段、免金鑰 |
| `twse_par` | TWSE `change/TWTB8U` 面額變更恢復買賣參考價 | 上市，實質 ≥ 2020-08 | 年切段、免金鑰 |
| `fm_split` | FinMind `TaiwanStockSplitPrice`（面額變更／分割／反分割，含 ETF） | 全市場一次拿完 | 免費層可用 |
| `fm_par` | FinMind `TaiwanStockParValueChange`（面額變更；與 fm_split 重疊，當交叉驗證） | 全市場 | 免費層可用 |
| `fm_reduction` | FinMind `TaiwanStockCapitalReductionReferencePrice`（減資：最後交易日收盤 → 恢復買賣參考價） | **必須逐檔查**（全市場查是付費層） | 600 次/小時，續跑 |

## 因子定義
`factor` ＝ 事件前後「價格水位連續性」係數 ＝ 恢復／除權息參考價 ÷ 事件前最後收盤。
還原：事件日**之前**的歷史價 × factor（現金減資、反分割 factor > 1 → 歷史被往上調）。
事件日的定義：除權息日／面額變更恢復買賣日／減資恢復買賣日（各來源的 `date` 欄）。

## 用法
    python scripts/selfhost_events.py --official 2015-01-01          # 官方除權息（月切段，約 10 分鐘）
    python scripts/selfhost_events.py --official-act 2011-01-01      # 官方減資／面額變更（年切段，約 1 分鐘）
    python scripts/selfhost_events.py --finmind-split                # 分割／面額變更（兩次請求）
    python scripts/selfhost_events.py --finmind-reduction            # 減資，逐檔、續跑（約 3.5 小時）
    python scripts/selfhost_events.py --build                        # 合併成 corp_actions.parquet
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
import _retry  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "data" / "selfhost"
OFFICIAL = SH / "ev_official.parquet"
OFFICIAL_ACT = SH / "ev_official_actions.parquet"      # 官方減資／面額變更（TWTAUU、revivt、TWTB8U）
FM_SPLIT = SH / "ev_fm_split.parquet"
FM_RED = SH / "ev_fm_reduction.parquet"
FM_RED_DONE = SH / "ev_fm_reduction_done.json"
OUT = SH / "corp_actions.parquet"
META = SH / "ev_official_meta.jsonl"                    # 官方回應的 notes／hints／title／total／params 原文（只增不減）
UA = {"User-Agent": "Mozilla/5.0"}
FM_API = "https://api.finmindtrade.com/api/v4/data"
FM_HOURLY = 560          # 免費註冊層 600/hr，留餘裕
COLS = ["ticker", "market", "date", "type", "prev_close", "ref_price", "factor", "source", "detail"]


def _http_json(url: str, retries: int = _retry.TRIES) -> dict:
    """用 requests（certifi）——TPEx 憑證鏈缺中繼憑證，urllib 驗證會失敗。400／402 不重試。"""
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            if r.status_code in (400, 402):
                raise HTTPError(r.status_code, r.text[:120])
            r.raise_for_status()
            return r.json()
        except HTTPError:
            raise
        except Exception as e:
            last = e
        _retry.wait_after_failure(i)
    raise RuntimeError(f"請求失敗：{url[:90]} {last}")


class HTTPError(Exception):
    def __init__(self, code: int, body: str = ""):
        super().__init__(f"HTTP {code} {body}")
        self.code = code


def _roc(s: str) -> pd.Timestamp:
    s = str(s).strip().replace("年", "/").replace("月", "/").replace("日", "")
    if "/" not in s and len(s) == 7 and s.isdigit():        # 民國 7 碼緊湊格式（TPEx revivt：1140113）
        s = f"{s[:3]}/{s[3:5]}/{s[5:]}"
    y, m, d = s.split("/")
    return pd.Timestamp(int(y) + 1911, int(m), int(d))


def _f(x) -> float | None:
    try:
        v = float(str(x).replace(",", "").strip())
    except ValueError:
        return None
    return v if v > 0 else None


# 官方事件表在「參考價」之外還給：開盤競價基準（TPEx 叫開始交易基準價）、減除股利參考價、漲停價、跌停價。
# 這些是官方認定「下一交易日開盤基準」的原值，不是我們推的；收進 detail，build 時展成欄位（見 enrich）。
_EXTRA = {"open_base": ("開盤競價基準", "開始交易基準價"), "div_ref": ("減除股利參考價",),
          "limit_up": ("漲停價格", "漲停價"), "limit_down": ("跌停價格", "跌停價")}


def _meta_row(source: str, a: str, b: str, j: dict) -> dict:
    """官方回應除了資料列以外的東西（notes、hints、title、total、params…）原文留存，不解析。
    官方會在這裡寫口徑（例：TWTAUU 的 notes 夾「除息併案減資」的現金股利）；notes 也會變，所以每次請求都記一列。
    TPEx 的表頭資訊在 tables[0]、上市在頂層，兩邊都收。"""
    top = {k: v for k, v in j.items() if k not in ("data", "fields", "tables")} if isinstance(j, dict) else {}
    tb = (j.get("tables") or [{}])[0] if isinstance(j, dict) and j.get("tables") else {}
    tab = {k: v for k, v in tb.items() if k not in ("data", "fields")}
    n = len(tb.get("data", [])) if tb else (len(j.get("data", [])) if isinstance(j, dict) else 0)
    return {"fetched_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), "source": source, "start": a, "end": b,
            "n_rows": n, "top": top, "table": tab}


def _record_meta(source: str, a: str, b: str, j: dict) -> None:
    try:
        SH.mkdir(parents=True, exist_ok=True)
        with open(META, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(_meta_row(source, a, b, j), ensure_ascii=False, default=str) + chr(10))
    except OSError as e:                                    # 存檔失敗不可擋住事件抓取
        print(f"::warning::官方 notes 存檔失敗：{e}", file=sys.stderr)


def _official_extra(fields: list[str], r: list) -> dict:
    out = {}
    for k, names in _EXTRA.items():
        i = next((fields.index(n) for n in names if n in fields), None)
        v = _f(r[i]) if i is not None else None
        if v is not None:
            out[k] = v
    return out


# ───────────────────────── 官方除權息 ─────────────────────────
def fetch_official(start: str, end: str) -> pd.DataFrame:
    rows = []
    for p in pd.period_range(start, end, freq="M"):
        a, b = p.start_time, p.end_time.normalize()
        time.sleep(1.5)
        j = _http_json("https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate={}&endDate={}&response=json"
                       .format(a.strftime("%Y%m%d"), b.strftime("%Y%m%d")))
        _record_meta("twse_ex", a.strftime("%Y%m%d"), b.strftime("%Y%m%d"), j)
        f = j.get("fields") or []
        for r in j.get("data", []) if j.get("stat") == "OK" else []:
            try:
                rows.append(("TW", str(r[1]).strip(), _roc(r[0]), str(r[f.index("權/息")]).strip(),
                             _f(r[f.index("除權息前收盤價")]), _f(r[f.index("除權息參考價")]),
                             {"value": r[f.index("權值+息值")], "src": "twse_ex", **_official_extra(f, r)}))
            except (ValueError, IndexError):
                continue
        time.sleep(1.5)
        j = _http_json("https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ?startDate={}&endDate={}&response=json"
                       .format(a.strftime("%Y/%m/%d"), b.strftime("%Y/%m/%d")))
        _record_meta("tpex_ex", a.strftime("%Y/%m/%d"), b.strftime("%Y/%m/%d"), j)
        t = (j.get("tables") or [{}])[0]
        f = t.get("fields") or []
        for r in t.get("data", []):
            try:
                rows.append(("TWO", str(r[1]).strip(), _roc(r[0]), str(r[f.index("權/息")]).strip(),
                             _f(r[f.index("除權息前收盤價")]), _f(r[f.index("除權息參考價")]),
                             {"value": r[f.index("權值+息值")], "cash_div": r[f.index("現金股利")],
                              "stock_div_per_1000": r[f.index("每仟股無償配股")],
                              "cash_increase_shares": r[f.index("現金增資股數")],
                              "cash_increase_price": r[f.index("現金增資認購價")], "src": "tpex_ex", **_official_extra(f, r)}))
            except (ValueError, IndexError):
                continue
        print(f"  {p} 累計 {len(rows)} 件", flush=True)
    kind = {"息": "ex_div", "權": "ex_rights", "權息": "ex_both", "除息": "ex_div", "除權": "ex_rights", "除權息": "ex_both"}
    out = []
    for mk, code, d, k, pre, ref, det in rows:
        if not (code.isdigit() and len(code) == 4) or pre is None or ref is None:
            continue
        out.append({"ticker": code, "market": mk, "date": d, "type": kind.get(k, "ex_other:" + k),
                    "prev_close": pre, "ref_price": ref, "factor": ref / pre,
                    "source": det.pop("src"), "detail": json.dumps(det, ensure_ascii=False)})
    return pd.DataFrame(out, columns=COLS)


# ───────────────────────── 官方減資／面額變更 ─────────────────────────
_ACT_SOURCES = [
    # (source, url 模板, 日期格式, 事件類型, 市場, 取價欄名（優先序）)
    ("twse_red", "https://www.twse.com.tw/rwd/zh/reducation/TWTAUU?startDate={a}&endDate={b}&response=json",
     "%Y%m%d", "cap_reduction", "TW", ("除權參考價", "恢復買賣參考價")),
    ("tpex_red", "https://www.tpex.org.tw/www/zh-tw/bulletin/revivt?startDate={a}&endDate={b}&response=json",
     "%Y/%m/%d", "cap_reduction", "TWO", ("除權參考價", "減資恢復買賣開始日參考價格")),
    ("twse_par", "https://www.twse.com.tw/rwd/zh/change/TWTB8U?startDate={a}&endDate={b}&response=json",
     "%Y%m%d", "par_change", "TW", ("恢復買賣參考價",)),
    # 上櫃變更面額（公告區，跟 revivt／exDailyQ 同一族；期間參數有效：回應 date 回顯 20150101~…）。tw-stock-data 2026-09-15 找到
    ("tpex_par", "https://www.tpex.org.tw/www/zh-tw/bulletin/pvChgRslt?startDate={a}&endDate={b}&response=json",
     "%Y/%m/%d", "par_change", "TWO", ("恢復買賣開始參考價",)),
]
_TPEX_BULLETIN = ("tpex_red", "tpex_par")


def _parse_action_table(t: dict, source: str, typ: str, market: str, price_cols: tuple[str, ...]) -> list[dict]:
    """把官方減資／面額變更表轉成事件列。前收＝『停止買賣前收盤價格』或『最後交易日之收盤價格』；
    參考價取 price_cols 第一個「有數字且 >0」的欄（減資併現金增資時『除權參考價』才是恢復買賣當天實際適用的價，
    其餘為 `--`／`0.00`）。欄名找不到 → 整張表丟棄並警告（改版時明確失敗，不靜默錯位）。"""
    f = t.get("fields") or []
    try:
        i_date = f.index("恢復買賣日期")
        i_code = next(i for i, n in enumerate(f) if n in ("股票代號", "證券代號"))     # revivt 叫股票代號、pvChgRslt 叫證券代號
        i_pre = next(i for i, n in enumerate(f) if n in ("停止買賣前收盤價格", "最後交易日之收盤價格"))
    except (ValueError, StopIteration):
        print(f"::warning::{source} 欄名對不上：{f}", file=sys.stderr)
        return []
    i_prices = [f.index(c) for c in price_cols if c in f]
    if not i_prices:
        print(f"::warning::{source} 找不到參考價欄 {price_cols}：{f}", file=sys.stderr)
        return []
    i_reason = f.index("減資原因") if "減資原因" in f else None
    out = []
    for r in t.get("data", []):
        code = str(r[i_code]).strip()
        pre = _f(r[i_pre])
        ref = next((v for v in (_f(r[i]) for i in i_prices) if v), None)
        if not (code.isdigit() and len(code) == 4) or pre is None or ref is None:
            continue
        out.append({"ticker": code, "market": market, "date": _roc(r[i_date]), "type": typ, "prev_close": pre,
                    "ref_price": ref, "factor": ref / pre, "source": source,
                    "detail": json.dumps({"reason": r[i_reason] if i_reason is not None else None,
                                          "price_col": next(f[i] for i in i_prices if _f(r[i])),
                                          "row": [str(x)[:60] for x in r[:10]], **_official_extra(f, r)}, ensure_ascii=False)})
    return out


def fetch_official_actions(start: str, end: str) -> pd.DataFrame:
    """官方減資／面額變更。年切段（單次區間過長的行為未驗，故保守）。"""
    rows: list[dict] = []
    for yr in range(int(start[:4]), int(end[:4]) + 1):
        a, b = pd.Timestamp(yr, 1, 1), pd.Timestamp(yr, 12, 31)
        for source, url, fmt, typ, market, price_cols in _ACT_SOURCES:
            time.sleep(1.5)
            try:
                j = _http_json(url.format(a=a.strftime(fmt), b=b.strftime(fmt)))
            except (HTTPError, RuntimeError) as e:
                print(f"::warning::{source} {yr} 抓取失敗：{e}", file=sys.stderr)
                continue
            _record_meta(source, a.strftime(fmt), b.strftime(fmt), j)
            t = (j.get("tables") or [j])[0] if source in _TPEX_BULLETIN else j
            if source not in _TPEX_BULLETIN and j.get("stat") != "OK":
                continue                                    # 該年無資料（非錯誤）
            rows += _parse_action_table(t, source, typ, market, price_cols)
        print(f"  {yr} 累計 {len(rows)} 件", flush=True)
    df = pd.DataFrame(rows, columns=COLS)
    return df.drop_duplicates(["ticker", "date", "type", "source"], keep="last") if len(df) else df


# ───────────────────────── FinMind ─────────────────────────
def _token() -> str | None:
    t = (os.environ.get("FINMIND_TOKEN") or "").strip()      # secret 貼上時常帶結尾換行 → FinMind 回 400「Token is illegal」（2026-10-06 實際發生）
    if t:
        return t
    for p in (ROOT / ".env",):       # tw-hold 自己的 .env；本機也可直接設環境變數 FINMIND_TOKEN
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.startswith("FINMIND_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"')
    return None


def _fm(dataset: str, **kw) -> list[dict]:
    p = {"dataset": dataset, **kw}
    t = _token()
    if t:
        p["token"] = t
    j = _http_json(FM_API + "?" + urllib.parse.urlencode(p))
    if j.get("status") != 200:
        raise RuntimeError(f"FinMind {dataset} {j.get('status')} {str(j.get('msg'))[:80]}")
    return j.get("data") or []


def fetch_fm_split() -> pd.DataFrame:
    kindmap = {"面額變更": "par_change", "分割": "split", "反分割": "reverse_split", "": "par_change"}
    out = []
    for ds, src in (("TaiwanStockSplitPrice", "fm_split"), ("TaiwanStockParValueChange", "fm_par")):
        for r in _fm(ds, start_date="2015-01-01", end_date=date.today().isoformat()):
            before = r.get("before_price", r.get("before_close"))
            after = r.get("after_price", r.get("after_ref_close"))
            if not before or not after:
                continue
            out.append({"ticker": str(r["stock_id"]), "market": None, "date": pd.Timestamp(r["date"]),
                        "type": kindmap.get(r.get("type", "面額變更"), "par_change"),
                        "prev_close": float(before), "ref_price": float(after), "factor": float(after) / float(before),
                        "source": src, "detail": json.dumps(r, ensure_ascii=False)})
        time.sleep(1.2)
    return pd.DataFrame(out, columns=COLS)


def _load_done() -> dict[str, str]:
    """ticker → 最後一次查詢日（ISO）。舊格式（list）視為 2026-10-05 查過。"""
    if not FM_RED_DONE.exists():
        return {}
    d = json.loads(FM_RED_DONE.read_text())
    return {t: "2026-10-05" for t in d} if isinstance(d, list) else d


def reduction_universe() -> list[str]:
    """要查減資的代號＝實價出現過的所有代號（含已下市）∪ 事件表出現過的代號。不讀 tw-swing 磁碟。"""
    tick: set[str] = set()
    rp = SH / "raw_prices.parquet"
    if rp.exists():
        tick |= set(pd.read_parquet(rp, columns=["ticker"])["ticker"].astype(str))
    if OUT.exists():
        tick |= set(pd.read_parquet(OUT, columns=["ticker"])["ticker"].astype(str))
    return sorted(t for t in tick if t.isdigit() and len(t) == 4)


def fetch_fm_reduction(tickers: list[str], max_calls: int | None = None, wait_on_402: bool = True) -> None:
    """逐檔查減資事件。**輪詢**：從未查過的先查、其次最久沒查的先查，一輪最多 max_calls 檔；
    狀態 done＝{ticker: 最後查詢日}，所以每週跑一小批就能在數週內輪完全市場，新減資不會永遠漏掉。
    每小時不超過 FM_HOURLY 次（含失敗的請求）。"""
    done = _load_done()
    rows = pd.read_parquet(FM_RED).to_dict("records") if FM_RED.exists() else []
    # 重查某檔時，先丟掉該檔舊的減資列（以最新查詢為準）
    order = sorted(tickers, key=lambda t: (t in done, done.get(t, "")))
    todo = order[:max_calls] if max_calls else order
    print(f"減資事件：全體 {len(tickers)} 檔、本輪查 {len(todo)} 檔（從未查過 {sum(t not in done for t in tickers)}）", flush=True)
    stamps: list[float] = []
    calls = 0
    today = date.today().isoformat()
    for t in todo:
        now = time.time()
        stamps = [x for x in stamps if now - x < 3600]
        if len(stamps) >= FM_HOURLY:
            wait = 3600 - (now - stamps[0]) + 5
            print(f"  已達每小時上限，等 {int(wait)} 秒", flush=True)
            time.sleep(wait)
        stamps.append(time.time())               # 先記數：失敗的請求同樣占額度
        data = None
        for attempt in range(6):
            try:
                if attempt:
                    stamps.append(time.time())        # 重試也占額度
                data = _fm("TaiwanStockCapitalReductionReferencePrice", data_id=t, start_date="2015-01-01")
                break
            except HTTPError as e:
                if e.code == 402 and wait_on_402 and attempt < 5:   # 超額：重置機制文件沒寫，保守等 10 分鐘再試（CI 用 --no-wait 直接存檔結束）
                    print(f"  {t} HTTP 402（超額），等 10 分鐘後重試（第 {attempt + 1} 次）", flush=True)
                    _save_red(rows, done)
                    time.sleep(600)
                    continue
                print(f"::warning::{t} HTTP {e.code}，停止本輪（已存進度）", file=sys.stderr)
                _save_red(rows, done)
                return
            except RuntimeError as e:
                print(f"::warning::{t} {e}", file=sys.stderr)
                break
        if data is None:
            continue
        calls += 1
        rows = [r for r in rows if r["ticker"] != t]
        for r in data:
            # 減資併現金增資時，恢復買賣當天實際適用的是 ExrightReferencePrice（與官方「除權參考價」同值）；
            # 純減資時該欄為 -1，退回 PostReductionReferencePrice。
            pre = r.get("ClosingPriceonTheLastTradingDay")
            ref = r.get("ExrightReferencePrice")
            if not ref or ref <= 0:
                ref = r.get("PostReductionReferencePrice")
            if pre and ref and pre > 0 and ref > 0:
                rows.append({"ticker": t, "market": None, "date": pd.Timestamp(r["date"]), "type": "cap_reduction",
                             "prev_close": float(pre), "ref_price": float(ref), "factor": float(ref) / float(pre),
                             "source": "fm_reduction", "detail": json.dumps(r, ensure_ascii=False)})
        done[t] = today
        if calls % 50 == 0:
            _save_red(rows, done)
            print(f"  已查 {calls} 檔，事件 {len(rows)} 件", flush=True)
        time.sleep(0.4)
    _save_red(rows, done)
    print(f"完成本輪：累計已查 {len(done)} 檔，減資事件 {len(rows)} 件")


def _save_red(rows: list[dict], done: dict[str, str]) -> None:
    SH.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=COLS).to_parquet(FM_RED, index=False)
    FM_RED_DONE.write_text(json.dumps(dict(sorted(done.items()))))


# ───────────────────────── 合併 ─────────────────────────
_EVENT_NAME = {"ex_div": "除息", "ex_rights": "除權", "ex_both": "除權息", "cap_reduction": "減資",
               "par_change": "變更股票面額", "split": "分割", "reverse_split": "反分割"}
# 事件名稱用官方原詞：TWSE 除權除息表的「權/息」欄寫 息／權／權息、TPEx 寫 除息／除權／除權息（統一成後者）；
# 減資＝TWTAUU／revivt（原因：退還股款、彌補虧損；上櫃另有「現金減資」）；變更股票面額＝TWTB8U／pvChgRslt。
# 官方**沒有**獨立的「現金增資」事件——現增是「除權」裡的現金增資欄位（TPEx exDailyQ 的現金增資股數／認購價）。
# 「分割」是 FinMind 的用語（ETF 分割，官方名稱待查）。`type` 欄是舊的內部代碼（與 event 一一對應），保留只為相容。


def enrich(ev: pd.DataFrame) -> pd.DataFrame:
    """加欄：event（官方事件名稱）、reason（官方減資原因／FinMind 原文）、open_base（開盤競價基準）、div_ref（減除股利參考價）、
    limit_up／limit_down（官方漲跌停價）。來源欄位名不同（FinMind 用 OpeningReferencePrice 等），這裡只做搬欄位，不改值。"""
    ev = ev.copy()
    ev["event"] = ev["type"].map(_EVENT_NAME)
    det = ev["detail"].map(lambda x: json.loads(x) if isinstance(x, str) and x.startswith("{") else {})
    ev["reason"] = [d.get("reason") or d.get("ReasonforCapitalReduction") for d in det]
    pick = lambda d, *ks: next((float(d[k]) for k in ks if d.get(k) not in (None, "", -1, -1.0)), None)   # noqa: E731
    ev["open_base"] = [pick(d, "open_base", "OpeningReferencePrice", "open_price", "after_ref_open") for d in det]
    ev["div_ref"] = [pick(d, "div_ref") for d in det]
    ev["limit_up"] = [pick(d, "limit_up", "LimitUp", "max_price", "after_ref_max") for d in det]
    ev["limit_down"] = [pick(d, "limit_down", "LimitDown", "min_price", "after_ref_min") for d in det]
    return ev


def build() -> pd.DataFrame:
    """合併成 corp_actions.parquet。**以既有 corp_actions 為底、聯集各來源檔、同鍵取最新**——
    CI 只有近兩個月的官方除權息與 FinMind 分割，沒有歷史來源檔，若不以舊檔為底就會把事件表重建成殘缺版本。"""
    srcs = [p for p in (OFFICIAL, OFFICIAL_ACT, FM_SPLIT) if p.exists()]      # FM_RED 不在這裡：下面「以最新查詢為準」才併入，避免重複
    parts = ([pd.read_parquet(OUT)] if OUT.exists() else []) + [pd.read_parquet(p) for p in srcs]
    if not parts and not FM_RED.exists():
        raise SystemExit("沒有任何來源檔，先跑 --official / --finmind-split / --finmind-reduction")
    ev = pd.concat([p[COLS] for p in parts] or [pd.DataFrame(columns=COLS)], ignore_index=True)
    ev["date"] = pd.to_datetime(ev["date"])
    ev = ev.drop_duplicates(["ticker", "date", "type", "source"], keep="last")     # 後面的來源較新
    # 補 market：官方有、FinMind 沒有的，由同代號的官方列推
    mk = ev.dropna(subset=["market"]).groupby("ticker")["market"].agg(lambda s: s.mode().iat[0])
    ev["market"] = ev["market"].fillna(ev["ticker"].map(mk))
    ev = ev[ev["ticker"].str.fullmatch(r"\d{4}")]       # 與上游宇宙規則一致
    # 某檔的減資列以「最新查詢」為準（重查後消失的事件不應殘留）：fm_reduction 只信 FM_RED 檔涵蓋到的代號
    if FM_RED.exists():
        red = pd.read_parquet(FM_RED)
        queried = set(_load_done())
        ev = ev[~((ev["source"] == "fm_reduction") & ev["ticker"].isin(queried))]
        ev = pd.concat([ev, red[COLS].assign(date=pd.to_datetime(red["date"]))], ignore_index=True)
    ev = enrich(ev.sort_values(["ticker", "date", "type", "source"]).reset_index(drop=True))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ev.to_parquet(OUT, index=False, compression="zstd")        # 不寫 built_at：內容不變時檔案位元組也不變
    print(f"corp_actions：{len(ev)} 件 / {ev['ticker'].nunique()} 檔；來源 {ev['source'].value_counts().to_dict()}")
    return ev


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--official", metavar="START", help="官方除權息回補起日 YYYY-MM-DD（到今天）")
    ap.add_argument("--official-act", metavar="START", help="官方減資／面額變更回補起日 YYYY-MM-DD（到今天）")
    ap.add_argument("--finmind-split", action="store_true")
    ap.add_argument("--finmind-reduction", action="store_true")
    ap.add_argument("--max-calls", type=int)
    ap.add_argument("--no-wait", action="store_true", help="FinMind 402 超額時不等待、存檔後結束（CI 用）")
    ap.add_argument("--build", action="store_true")
    a = ap.parse_args(argv)
    SH.mkdir(parents=True, exist_ok=True)
    if a.official:
        new = fetch_official(a.official, date.today().strftime("%Y-%m-%d"))
        old = pd.read_parquet(OFFICIAL) if OFFICIAL.exists() else pd.DataFrame(columns=COLS)
        pd.concat([old, new]).drop_duplicates(["ticker", "date", "type", "source"], keep="last") \
            .to_parquet(OFFICIAL, index=False)
        print(f"官方除權息：{len(new)} 件已存 {OFFICIAL.name}")
    if a.official_act:
        new = fetch_official_actions(a.official_act, date.today().strftime("%Y-%m-%d"))
        old = pd.read_parquet(OFFICIAL_ACT) if OFFICIAL_ACT.exists() else pd.DataFrame(columns=COLS)
        pd.concat([old, new]).drop_duplicates(["ticker", "date", "type", "source"], keep="last")             .to_parquet(OFFICIAL_ACT, index=False)
        print(f"官方減資／面額：{len(new)} 件已存 {OFFICIAL_ACT.name}")
    if a.finmind_split:
        df = fetch_fm_split()
        df.to_parquet(FM_SPLIT, index=False)
        print(f"FinMind 分割／面額變更：{len(df)} 件")
    if a.finmind_reduction:
        fetch_fm_reduction(reduction_universe(), a.max_calls, wait_on_402=not a.no_wait)
    if a.build:
        build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
