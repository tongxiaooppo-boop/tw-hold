"""自建上游 P2 地基：公司行為事件表 → `data/selfhost/corp_actions.parquet`。

每一檔、每一次影響股價連續性的事件（除息／除權／權息／面額變更／分割／反分割／減資）一列，
**記來源與原始欄位**，之後任何還原價的接縫都能追到「哪個事件、哪個來源、因子多少」。

## 來源（2026-10-05 逐一實測）
| source | 內容 | 範圍 | 取法 |
| :-- | :-- | :-- | :-- |
| `twse_ex` | TWSE `exRight/TWT49U` 除權息計算結果（前收、參考價） | 上市，≥ 2015 | 月切段、免金鑰 |
| `tpex_ex` | TPEx `bulletin/exDailyQ` 除權息計算結果（含現金增資欄） | 上櫃，≥ 2015 | 月切段、免金鑰 |
| `fm_split` | FinMind `TaiwanStockSplitPrice`（面額變更／分割／反分割，含 ETF） | 全市場一次拿完 | 免費層可用 |
| `fm_par` | FinMind `TaiwanStockParValueChange`（面額變更；與 fm_split 重疊，當交叉驗證） | 全市場 | 免費層可用 |
| `fm_reduction` | FinMind `TaiwanStockCapitalReductionReferencePrice`（減資：最後交易日收盤 → 恢復買賣參考價） | **必須逐檔查**（全市場查是付費層） | 600 次/小時，續跑 |

## 因子定義
`factor` ＝ 事件前後「價格水位連續性」係數 ＝ 恢復／除權息參考價 ÷ 事件前最後收盤。
還原：事件日**之前**的歷史價 × factor（現金減資、反分割 factor > 1 → 歷史被往上調）。
事件日的定義：除權息日／面額變更恢復買賣日／減資恢復買賣日（各來源的 `date` 欄）。

## 用法
    python scripts/selfhost_events.py --official 2015-01-01          # 官方除權息（月切段，約 10 分鐘）
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

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "data" / "selfhost"
OFFICIAL = SH / "ev_official.parquet"
FM_SPLIT = SH / "ev_fm_split.parquet"
FM_RED = SH / "ev_fm_reduction.parquet"
FM_RED_DONE = SH / "ev_fm_reduction_done.json"
OUT = SH / "corp_actions.parquet"
UA = {"User-Agent": "Mozilla/5.0"}
FM_API = "https://api.finmindtrade.com/api/v4/data"
FM_HOURLY = 560          # 免費註冊層 600/hr，留餘裕
COLS = ["ticker", "market", "date", "type", "prev_close", "ref_price", "factor", "source", "detail"]


def _http_json(url: str, retries: int = 3) -> dict:
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
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"請求失敗：{url[:90]} {last}")


class HTTPError(Exception):
    def __init__(self, code: int, body: str = ""):
        super().__init__(f"HTTP {code} {body}")
        self.code = code


def _roc(s: str) -> pd.Timestamp:
    s = str(s).strip().replace("年", "/").replace("月", "/").replace("日", "")
    y, m, d = s.split("/")
    return pd.Timestamp(int(y) + 1911, int(m), int(d))


def _f(x) -> float | None:
    try:
        v = float(str(x).replace(",", "").strip())
    except ValueError:
        return None
    return v if v > 0 else None


# ───────────────────────── 官方除權息 ─────────────────────────
def fetch_official(start: str, end: str) -> pd.DataFrame:
    rows = []
    for p in pd.period_range(start, end, freq="M"):
        a, b = p.start_time, p.end_time.normalize()
        time.sleep(1.5)
        j = _http_json("https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate={}&endDate={}&response=json"
                       .format(a.strftime("%Y%m%d"), b.strftime("%Y%m%d")))
        f = j.get("fields") or []
        for r in j.get("data", []) if j.get("stat") == "OK" else []:
            try:
                rows.append(("TW", str(r[1]).strip(), _roc(r[0]), str(r[f.index("權/息")]).strip(),
                             _f(r[f.index("除權息前收盤價")]), _f(r[f.index("除權息參考價")]),
                             {"value": r[f.index("權值+息值")], "src": "twse_ex"}))
            except (ValueError, IndexError):
                continue
        time.sleep(1.5)
        j = _http_json("https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ?startDate={}&endDate={}&response=json"
                       .format(a.strftime("%Y/%m/%d"), b.strftime("%Y/%m/%d")))
        t = (j.get("tables") or [{}])[0]
        f = t.get("fields") or []
        for r in t.get("data", []):
            try:
                rows.append(("TWO", str(r[1]).strip(), _roc(r[0]), str(r[f.index("權/息")]).strip(),
                             _f(r[f.index("除權息前收盤價")]), _f(r[f.index("除權息參考價")]),
                             {"value": r[f.index("權值+息值")], "cash_div": r[f.index("現金股利")],
                              "stock_div_per_1000": r[f.index("每仟股無償配股")],
                              "cash_increase_shares": r[f.index("現金增資股數")],
                              "cash_increase_price": r[f.index("現金增資認購價")], "src": "tpex_ex"}))
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


# ───────────────────────── FinMind ─────────────────────────
def _token() -> str | None:
    t = os.environ.get("FINMIND_TOKEN")
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
            pre, ref = r.get("ClosingPriceonTheLastTradingDay"), r.get("PostReductionReferencePrice")
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
def build() -> pd.DataFrame:
    """合併成 corp_actions.parquet。**以既有 corp_actions 為底、聯集各來源檔、同鍵取最新**——
    CI 只有近兩個月的官方除權息與 FinMind 分割，沒有歷史來源檔，若不以舊檔為底就會把事件表重建成殘缺版本。"""
    srcs = [p for p in (OFFICIAL, FM_SPLIT) if p.exists()]      # FM_RED 不在這裡：下面「以最新查詢為準」才併入，避免重複
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
    ev = ev.sort_values(["ticker", "date", "type", "source"]).reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ev.to_parquet(OUT, index=False, compression="zstd")        # 不寫 built_at：內容不變時檔案位元組也不變
    print(f"corp_actions：{len(ev)} 件 / {ev['ticker'].nunique()} 檔；來源 {ev['source'].value_counts().to_dict()}")
    return ev


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--official", metavar="START", help="官方除權息回補起日 YYYY-MM-DD（到今天）")
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
