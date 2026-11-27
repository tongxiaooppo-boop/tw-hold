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
import sys
from datetime import date
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


def load_tsd_prices(tsd_data: Path, codes: frozenset[str] = CODES) -> pd.DataFrame:
    """讀 tsd_data/early/daily/*.csv 與 tsd_data/universe/daily/*.csv（欄：date, stock_id, open, high, low, close, volume…）。
    只留 stock_id ∈ codes 且 close 可轉成 > 0 的數字；數字欄去千分位。同 (ticker, date) 兩邊都有 → universe 優先。
    source='tsd'。用 csv 模組逐檔讀、只挑白名單列（全市場檔很多，不要整檔進 pandas）。"""
    raise NotImplementedError


def load_tsd_events(tsd_data: Path, codes: frozenset[str] = CODES) -> pd.DataFrame:
    """讀 tsd_data/early/exright/*.csv（欄：date, stock_id, pre_close, ref_price, value, kind, …；跳過 _ 開頭的檔）。
    白名單列：kind=='息' → type='div', cash=value, factor=ref/pre, source='tsd_exright'；
    白名單列 kind 不是 '息' → raise ValueError（ETF 不該除權，出現代表口徑要重想）。"""
    raise NotImplementedError


def fetch_prices(days: list[date], codes: frozenset[str] = CODES) -> pd.DataFrame:
    """逐日呼叫 selfhost_raw_prices.fetch_twse(d, keep=lambda c: c in codes)（白名單全是上市，不問上櫃）。
    回 None（抓取失敗）→ 印 ::warning:: 跳過那天；空表＝休市。輸出 PRICE_COLS，source='twse'。"""
    raise NotImplementedError


def fetch_events(a: date, b: date, codes: frozenset[str] = CODES) -> pd.DataFrame:
    """selfhost_events._ex_rows(pd.Timestamp(a), pd.Timestamp(b)) 的原始列，只留 market=='TW' 且代號 ∈ codes、
    pre／ref 都不是 None。權/息=='息' → type='div', cash=float(detail['value'] 去千分位), factor=ref/pre, source='twse_ex'；
    其他種類 → raise ValueError。backfill 時由 main 按月切段呼叫。"""
    raise NotImplementedError


def split_events() -> pd.DataFrame:
    """ETF_SPLITS → EVENT_COLS：type='split', cash/prev_close/ref_price=NaN, source='manual'。"""
    raise NotImplementedError


def upsert(old: pd.DataFrame, new: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """合併，同 keys 以 new 為準，依 keys 排序、重設 index。old 可為空表。"""
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    """events 的 upsert keys＝['ticker', 'date', 'type']；prices＝['ticker', 'date']。
    寫檔前 date 一律 datetime64[ns]（無時區）、ETF_DIR 不存在就建。"""
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
