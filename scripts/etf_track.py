"""ETF 白名單的原始日線與事件收集 → data/etf/{prices,events}.parquet。

框架 2026-11-27（Opus 定，實作者不得改函式簽名、欄名、子指令；有問題停下回報）。
獨立一軌：不寫 data/selfhost、不進 data_pack（給 tw-swing 的資料包維持只收 4 碼個股）。

子指令
  backfill --tsd <TSD repo 的 data 目錄>   本機一次性：TSD 日線（2004～）＋ TSD 除權息（≤2014）
                                           ＋ 官方除權息 TWT49U（2015-01～本月，按月）＋ 分割表 → 覆寫兩個 parquet
  daily [--days 10]                        CI 每日：官方 MI_INDEX 近 N 個日曆日的平日 ＋ 官方除權息近 30 天 ＋ 分割表 → upsert
  verify --tsd <dir> --dates d1,d2,...      對帳：那幾天官方 MI_INDEX 與 TSD 的白名單收盤，差 > 0.005 的列出；
                                           有差異、官方抓取失敗、或某檔只有一邊有資料（列出）→ exit 1
路徑一律用 ROOT 相對；寫檔前建 ETF_DIR。
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reference.etf_universe import ETF_SPLITS, ETF_UNIVERSE  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ETF_DIR = ROOT / "data" / "etf"
PRICES = ETF_DIR / "prices.parquet"
EVENTS = ETF_DIR / "events.parquet"
PRICE_COLS = ["ticker", "date", "open", "high", "low", "close", "volume", "source"]   # source: 'tsd'|'twse'
EVENT_COLS = ["ticker", "date", "type", "cash", "prev_close", "ref_price", "factor", "source"]
# type: 'div'|'split'；source: 'tsd_exright'|'twse_ex'|'manual'
CODES: frozenset[str] = frozenset(ETF_UNIVERSE)


def _fnum(x) -> float | None:
    try:
        v = float(str(x).replace(",", "").strip())
    except ValueError:
        return None
    return v if v == v else None


def _empty(cols: list[str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="datetime64[ns]" if c == "date" else "object") for c in cols})


def load_tsd_prices(tsd_data: Path, codes: frozenset[str] = CODES) -> pd.DataFrame:
    """讀 tsd_data/early/daily/*.csv 與 tsd_data/universe/daily/*.csv（欄：date, stock_id, open, high, low, close, volume…）。
    只留 stock_id ∈ codes 且 close 可轉成 > 0 的數字；數字欄去千分位。同 (ticker, date) 兩邊都有 → universe 優先。
    source='tsd'。用 csv 模組逐檔讀、只挑白名單列（全市場檔很多，不要整檔進 pandas）。"""
    got: dict[tuple[str, str], dict] = {}
    for sub in ("early", "universe"):           # 後讀的 universe 覆蓋 early
        for f in sorted((Path(tsd_data) / sub / "daily").glob("*.csv")):
            with open(f, encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    code = (r.get("stock_id") or "").strip()
                    if code not in codes:
                        continue
                    c = _fnum(r.get("close"))
                    if c is None or c <= 0:
                        continue
                    d = (r.get("date") or "").strip()
                    o, h, lo = _fnum(r.get("open")), _fnum(r.get("high")), _fnum(r.get("low"))
                    got[(code, d)] = {"ticker": code, "date": d, "open": o if o and o > 0 else c,
                                      "high": h if h and h > 0 else c, "low": lo if lo and lo > 0 else c,
                                      "close": c, "volume": _fnum(r.get("volume")) or 0.0, "source": "tsd"}
    if not got:
        return _empty(PRICE_COLS)
    df = pd.DataFrame(list(got.values()), columns=PRICE_COLS)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["ticker", "date"]).reset_index(drop=True)


def load_tsd_events(tsd_data: Path, codes: frozenset[str] = CODES) -> pd.DataFrame:
    """讀 tsd_data/early/exright/*.csv（欄：date, stock_id, pre_close, ref_price, value, kind, …；跳過 _ 開頭的檔）。
    白名單列：kind=='息' → type='div', cash=value, factor=ref/pre, source='tsd_exright'；
    白名單列 kind 不是 '息' → raise ValueError（ETF 不該除權，出現代表口徑要重想）。"""
    out = []
    for f in sorted((Path(tsd_data) / "early" / "exright").glob("*.csv")):
        if f.name.startswith("_"):
            continue
        with open(f, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                code = (r.get("stock_id") or "").strip()
                if code not in codes:
                    continue
                kind = (r.get("kind") or "").strip()
                if kind != "息":
                    raise ValueError(f"TSD 除權息 {f.name} {code} kind={kind!r}，ETF 不該除權")
                pre, ref, cash = _fnum(r.get("pre_close")), _fnum(r.get("ref_price")), _fnum(r.get("value"))
                if not pre or not ref or cash is None:
                    continue
                out.append({"ticker": code, "date": (r.get("date") or "").strip(), "type": "div", "cash": cash,
                            "prev_close": pre, "ref_price": ref, "factor": ref / pre, "source": "tsd_exright"})
    if not out:
        return _empty(EVENT_COLS)
    df = pd.DataFrame(out, columns=EVENT_COLS)
    df["date"] = pd.to_datetime(df["date"])
    return df


def fetch_prices(days: list[date], codes: frozenset[str] = CODES) -> pd.DataFrame:
    """逐日呼叫 selfhost_raw_prices.fetch_twse(d, keep=lambda c: c in codes)（白名單全是上市，不問上櫃）。
    回 None（抓取失敗）→ 印 ::warning:: 跳過那天；空表＝休市。輸出 PRICE_COLS，source='twse'。"""
    import selfhost_raw_prices as rp
    parts = []
    for d in days:
        t = rp.fetch_twse(d, keep=lambda c: c in codes)
        time.sleep(rp.SLEEP)
        if t is None:
            print(f"::warning::ETF 價格 {d} 抓取失敗，跳過", file=sys.stderr)
            continue
        if not t.empty:
            parts.append(t)
    if not parts:
        return _empty(PRICE_COLS)
    df = pd.concat(parts, ignore_index=True)
    df["source"] = "twse"
    df["date"] = pd.to_datetime(df["date"])
    return df[PRICE_COLS].reset_index(drop=True)


def fetch_events(a: date, b: date, codes: frozenset[str] = CODES) -> pd.DataFrame:
    """selfhost_events._ex_rows(pd.Timestamp(a), pd.Timestamp(b)) 的原始列，只留 market=='TW' 且代號 ∈ codes、
    pre／ref 都不是 None。權/息=='息' → type='div', cash=float(detail['value'] 去千分位), factor=ref/pre, source='twse_ex'；
    其他種類 → raise ValueError。backfill 時由 main 按月切段呼叫。"""
    import selfhost_events as se
    out = []
    for mk, code, d, kind, pre, ref, det in se._ex_rows(pd.Timestamp(a), pd.Timestamp(b)):
        if mk != "TW" or code not in codes or pre is None or ref is None:
            continue
        if kind != "息":
            raise ValueError(f"官方除權息 {d:%Y-%m-%d} {code} 權/息={kind!r}，ETF 不該除權")
        cash = _fnum(det.get("value"))
        if cash is None:
            raise ValueError(f"官方除權息 {d:%Y-%m-%d} {code} 權值+息值={det.get('value')!r} 無法解析")
        out.append({"ticker": code, "date": d, "type": "div", "cash": cash, "prev_close": pre,
                    "ref_price": ref, "factor": ref / pre, "source": "twse_ex"})
    if not out:
        return _empty(EVENT_COLS)
    df = pd.DataFrame(out, columns=EVENT_COLS)
    df["date"] = pd.to_datetime(df["date"])
    return df


def split_events() -> pd.DataFrame:
    """ETF_SPLITS → EVENT_COLS：type='split', cash/prev_close/ref_price=NaN, source='manual'。"""
    nan = float("nan")
    return pd.DataFrame([{"ticker": t, "date": pd.Timestamp(d), "type": "split", "cash": nan,
                          "prev_close": nan, "ref_price": nan, "factor": f, "source": "manual"}
                         for t, d, f in ETF_SPLITS], columns=EVENT_COLS)


def upsert(old: pd.DataFrame, new: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """合併，同 keys 以 new 為準，依 keys 排序、重設 index。old 可為空表。"""
    frames = [x for x in (old, new) if x is not None and len(x)]
    if not frames:
        return (new if new is not None else old).iloc[0:0].reset_index(drop=True)
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=keys, keep="last")
    return df.sort_values(keys).reset_index(drop=True)


def _read(path: Path, cols: list[str]) -> pd.DataFrame:
    return pd.read_parquet(path) if path.exists() else _empty(cols)


def _write(prices: pd.DataFrame, events: pd.DataFrame) -> None:
    ETF_DIR.mkdir(parents=True, exist_ok=True)
    for df, path, cols in ((prices, PRICES, PRICE_COLS), (events, EVENTS, EVENT_COLS)):
        df = df[cols].copy()
        df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
        df.to_parquet(path, index=False)


def _weekdays(n_days: int) -> list[date]:
    today = date.today()
    return [d for d in (today - timedelta(days=i) for i in range(n_days, -1, -1)) if d.weekday() < 5]


def _verify(tsd: Path, dates: list[str]) -> int:
    import selfhost_raw_prices as rp
    tsd_px = load_tsd_prices(tsd)
    bad = 0
    for ds in dates:
        d = date.fromisoformat(ds)
        off = rp.fetch_twse(d, keep=lambda c: c in CODES)
        time.sleep(rp.SLEEP)
        if off is None:
            print(f"{ds} 官方抓取失敗")
            bad += 1
            continue
        a = {r.ticker: r.close for r in off.itertuples()}
        b = {r.ticker: r.close for r in tsd_px[tsd_px["date"] == pd.Timestamp(d)].itertuples()}
        for code in sorted(set(a) | set(b)):
            if code not in a or code not in b:
                print(f"{ds} {code} 只有一邊有資料（官方 {a.get(code)} / TSD {b.get(code)}）")
                bad += 1
            elif abs(a[code] - b[code]) > 0.005:
                print(f"{ds} {code} 官方 {a[code]} / TSD {b[code]} 差 {a[code] - b[code]:+.3f}")
                bad += 1
        print(f"{ds} 官方 {len(a)} 檔 / TSD {len(b)} 檔")
    print("verify", "通過" if bad == 0 else f"失敗 {bad} 筆")
    return 0 if bad == 0 else 1


def main(argv: list[str] | None = None) -> int:
    """events 的 upsert keys＝['ticker', 'date', 'type']；prices＝['ticker', 'date']。
    寫檔前 date 一律 datetime64[ns]（無時區）、ETF_DIR 不存在就建。"""
    ap = argparse.ArgumentParser(description="ETF 白名單原始日線與事件收集")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pb = sub.add_parser("backfill")
    pb.add_argument("--tsd", required=True, type=Path)
    pdy = sub.add_parser("daily")
    pdy.add_argument("--days", type=int, default=10)
    pv = sub.add_parser("verify")
    pv.add_argument("--tsd", required=True, type=Path)
    pv.add_argument("--dates", required=True)
    a = ap.parse_args(argv)
    ek = ["ticker", "date", "type"]
    pk = ["ticker", "date"]
    if a.cmd == "verify":
        return _verify(a.tsd, [x.strip() for x in a.dates.split(",") if x.strip()])
    today = date.today()
    if a.cmd == "backfill":
        prices = load_tsd_prices(a.tsd)
        ev = upsert(load_tsd_events(a.tsd), split_events(), ek)
        for p in pd.period_range("2015-01", f"{today:%Y-%m}", freq="M"):
            e = fetch_events(p.start_time.date(), min(p.end_time.date(), today))
            ev = upsert(ev, e, ek)
            print(f"  {p} 事件累計 {len(ev)}", flush=True)
        _write(prices, ev)
        print(f"backfill prices {len(prices)} events {len(ev)}")
        return 0
    prices = upsert(_read(PRICES, PRICE_COLS), fetch_prices(_weekdays(a.days)), pk)
    ev = upsert(_read(EVENTS, EVENT_COLS), fetch_events(today - timedelta(days=30), today), ek)
    ev = upsert(ev, split_events(), ek)
    _write(prices, ev)
    print(f"daily prices {len(prices)} events {len(ev)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
