"""自建上游：第二、第三來源（FinMind、Yahoo）的平行回補，只做**交叉驗證與缺口備援**，不覆蓋官方資料。

## 為什麼
官方（TWSE/TPEx）是主來源，但「單一來源」＝無法證明對。FinMind 與 Yahoo 是不同主機、不同口徑的獨立來源，可以和官方**同時**各跑各的
（限流是依主機／帳號分開的；互相不搶額度，唯一共用的是 FinMind 帳號每小時 600 次，由本檔自己節流在 550）。
信任度：官方 ＞ FinMind（未還原價與官方同源轉載，但有缺值／延遲）＞ Yahoo（還原價在現增／權息事件上自己的因子會錯）。
→ 這裡的資料**永遠存在 `data/selfhost/xsrc/`，不併入官方檔**；用途是 ①逐日對帳（官方 vs FinMind 價量／法人／融資券，Yahoo 還原與股利／分割事件）
②官方某日缺料時的備援（使用時必須標來源）。

## 通道
- `--lane finmind`：依序 price（TaiwanStockPrice 未還原）→ margin → inst，逐檔、續跑、每小時 ≤550 次；402 等待重試
- `--lane yahoo`：`yf.Ticker(t).history(period="max", auto_adjust=False, actions=True)`：Close（僅拆股調整）、Adj Close（含息還原）、Dividends、Stock Splits

## 輸出（`data/selfhost/xsrc/`）
`fm_price.parquet`、`fm_margin.parquet`、`fm_inst.parquet`（長表：date,ticker,name,buy,sell）、`yahoo.parquet`；`*_state.json`＝{ticker: 最後查詢日}

用法：
    python scripts/selfhost_xsrc.py --lane finmind [--datasets price,margin,inst] [--limit N]
    python scripts/selfhost_xsrc.py --lane yahoo [--limit N]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "data" / "selfhost"
XS = SH / "xsrc"
FM_API = "https://api.finmindtrade.com/api/v4/data"
FM_HOURLY = 550
START = "2015-01-01"
FM_DATASETS = {
    "price": ("TaiwanStockPrice", "fm_price"),
    "margin": ("TaiwanStockMarginPurchaseShortSale", "fm_margin"),
    "inst": ("TaiwanStockInstitutionalInvestorsBuySell", "fm_inst"),
}


def universe() -> list[str]:
    """查詢清單＝官方實價出現過的代號（含已下市）∪ 事件表代號（4 碼）。不讀 tw-swing 磁碟。"""
    tick: set[str] = set()
    for p, col in ((SH / "raw_prices.parquet", "ticker"), (SH / "corp_actions.parquet", "ticker")):
        if p.exists():
            tick |= set(pd.read_parquet(p, columns=[col])[col].astype(str))
    return sorted(t for t in tick if t.isdigit() and len(t) == 4)


def _token() -> str | None:
    t = os.environ.get("FINMIND_TOKEN")
    if t:
        return t
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("FINMIND_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"')
    return None


def _load_state(name: str) -> dict[str, str]:
    p = XS / f"{name}_state.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _save(name: str, rows: list[pd.DataFrame], state: dict[str, str]) -> None:
    XS.mkdir(parents=True, exist_ok=True)
    out = XS / f"{name}.parquet"
    if rows:
        new = pd.concat(rows, ignore_index=True)
        old = pd.read_parquet(out) if out.exists() else pd.DataFrame()
        allp = pd.concat([old, new], ignore_index=True)
        key = [c for c in ("date", "ticker", "name") if c in allp.columns]
        allp.drop_duplicates(key, keep="last").to_parquet(out, index=False, compression="zstd")
    (XS / f"{name}_state.json").write_text(json.dumps(dict(sorted(state.items()))))


# ───────────────────────── FinMind ─────────────────────────
def _fm_get(dataset: str, ticker: str) -> list[dict]:
    p = {"dataset": dataset, "data_id": ticker, "start_date": START}
    t = _token()
    if t:
        p["token"] = t
    r = requests.get(FM_API, params=p, timeout=60)
    if r.status_code in (402, 403):
        raise PermissionError(r.status_code)
    r.raise_for_status()
    j = r.json()
    if j.get("status") != 200:
        raise RuntimeError(f"FinMind {dataset} {j.get('status')} {str(j.get('msg'))[:80]}")
    return j.get("data") or []


def _fm_norm(kind: str, data: list[dict], ticker: str) -> pd.DataFrame:
    if not data:
        return pd.DataFrame()
    d = pd.DataFrame(data)
    d["date"] = pd.to_datetime(d["date"])
    d["ticker"] = ticker
    d = d.drop(columns=[c for c in ("stock_id",) if c in d.columns])
    if kind == "price":
        d = d.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume", "Trading_money": "value"})
        d = d[[c for c in ("date", "ticker", "open", "high", "low", "close", "volume", "value") if c in d.columns]]
        d = d[d["close"] > 0]                 # FinMind 停牌／缺漏列收盤為 0
    return d


def lane_finmind(datasets: list[str], limit: int | None) -> None:
    tick = universe()
    stamps: list[float] = []
    for ds in datasets:
        dataset, name = FM_DATASETS[ds]
        state = _load_state(name)
        todo = sorted(tick, key=lambda t: (t in state, state.get(t, "")))
        if limit:
            todo = todo[:limit]
        print(f"[finmind/{ds}] 全體 {len(tick)} 檔、本輪查 {len(todo)} 檔（從未查過 {sum(t not in state for t in tick)}）", flush=True)
        rows: list[pd.DataFrame] = []
        n = 0
        for t in todo:
            now = time.time()
            stamps = [s for s in stamps if now - s < 3600]
            if len(stamps) >= FM_HOURLY:
                wait = 3600 - (now - stamps[0]) + 5
                print(f"  已達每小時上限，等 {int(wait)} 秒", flush=True)
                time.sleep(wait)
            for attempt in range(6):
                stamps.append(time.time())
                try:
                    data = _fm_get(dataset, t)
                    break
                except PermissionError:
                    if attempt == 5:
                        print("::warning::FinMind 持續 402／403，停止本輪（已存進度）", file=sys.stderr)
                        _save(name, rows, state)
                        return
                    print(f"  {t} 402／403（超額），等 10 分鐘（第 {attempt + 1} 次）", flush=True)
                    _save(name, rows, state)
                    rows = []
                    time.sleep(600)
                except Exception as e:
                    print(f"::warning::{t} {e}", file=sys.stderr)
                    data = None
                    break
            if data is None:
                continue
            d = _fm_norm(ds, data, t)
            if len(d):
                rows.append(d)
            state[t] = date.today().isoformat()
            n += 1
            if n % 50 == 0:
                _save(name, rows, state)
                rows = []
                print(f"  [{ds}] 已查 {n} 檔", flush=True)
            time.sleep(0.3)
        _save(name, rows, state)
        print(f"[finmind/{ds}] 完成本輪：累計已查 {len(state)} 檔", flush=True)


# ───────────────────────── Yahoo ─────────────────────────
def _suffix_map() -> dict[str, str]:
    """代號→.TW/.TWO：以官方實價與事件表的 market 欄；未知者兩種都試。"""
    m: dict[str, str] = {}
    for p in (SH / "raw_prices.parquet", SH / "corp_actions.parquet"):
        if p.exists():
            d = pd.read_parquet(p, columns=["ticker", "market"]).dropna().drop_duplicates("ticker")
            m.update({t: ("TWO" if mk == "TWO" else "TW") for t, mk in zip(d["ticker"], d["market"])})
    return m


def lane_yahoo(limit: int | None) -> None:
    import yfinance as yf
    tick = universe()
    sfx = _suffix_map()
    state = _load_state("yahoo")
    todo = sorted(tick, key=lambda t: (t in state, state.get(t, "")))
    if limit:
        todo = todo[:limit]
    print(f"[yahoo] 全體 {len(tick)} 檔、本輪查 {len(todo)} 檔", flush=True)
    rows: list[pd.DataFrame] = []
    n = 0
    for t in todo:
        got = None
        for s in ([sfx[t]] if t in sfx else ["TW", "TWO"]):
            try:
                h = yf.Ticker(f"{t}.{s}").history(period="max", auto_adjust=False, actions=True)
            except Exception as e:
                print(f"::warning::{t}.{s} {str(e)[:80]}", file=sys.stderr)
                continue
            if h is not None and len(h):
                got = (s, h)
                break
        if got is not None:
            s, h = got
            h = h.reset_index()
            h["date"] = pd.to_datetime(h["Date"]).dt.tz_localize(None).dt.normalize()
            d = pd.DataFrame({"date": h["date"], "ticker": t, "suffix": s, "open": h["Open"], "high": h["High"], "low": h["Low"],
                              "close": h["Close"], "adj_close": h.get("Adj Close"), "volume": h["Volume"],
                              "dividends": h.get("Dividends", 0.0), "splits": h.get("Stock Splits", 0.0)})
            rows.append(d[d["date"] >= START])
        state[t] = date.today().isoformat()          # 查過（含查無，如已下市 Yahoo 無資料）都記，避免每輪重打
        n += 1
        if n % 50 == 0:
            _save("yahoo", rows, state)
            rows = []
            print(f"  [yahoo] 已查 {n} 檔", flush=True)
        time.sleep(0.6)
    _save("yahoo", rows, state)
    print(f"[yahoo] 完成本輪：累計已查 {len(state)} 檔", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", choices=["finmind", "yahoo"], required=True)
    ap.add_argument("--datasets", default="price,margin,inst")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    if a.lane == "finmind":
        lane_finmind([d for d in a.datasets.split(",") if d in FM_DATASETS], a.limit)
    else:
        lane_yahoo(a.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
