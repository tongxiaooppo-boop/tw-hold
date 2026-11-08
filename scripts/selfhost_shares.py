"""自建上游 D04：官方**逐日發行股數**（上市＋上櫃）→ `data/selfhost/shares.parquet`。

框架版本：2026-11-08（Opus 定；實作者只填函式內容，不改簽名、欄位、常數名）。

## 為什麼存在
目前市值／排名用的股數是 ap03 公司基本資料快照（`tw-swing/data/fundamentals/official_shares.parquet`），
只有一天、每次覆蓋。2026-11-08 Opus 實測 ap03 與交易所當日發行股數**有 10% 檔數不同**（1,989 檔中 204 檔；
例 1808 ap03 7.14 億 vs 交易所 8.93 億），DR 更是單位不同（ap03 給原股、交易所給 DR 單位數）。
交易所端的發行股數**可以帶歷史日期查**，所以這個資料集可以真的做成逐日。

## 資料源（2026-11-08 實測，兩者都可帶歷史日期）
- 上市：`www.twse.com.tw/rwd/zh/fund/MI_QFIIS?date=YYYYMMDD&selectType=ALLBUT0999&response=json`
  （外資持股統計表）。頂層 `fields`／`data`（不是 tables）；頂層 `date` 必須等於請求日。
  代號欄＝欄名「結尾是『代號』且不含 ISIN」那欄（表內另有「國際證券編碼」，2018 起欄名一致）；股數欄＝欄名含「發行股數」。
- 上櫃：`www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date=YYYY/MM/DD&response=json`
  （跟 `selfhost_raw_prices.py` 同一端點）。`tables[0]`；頂層 `date` 必須等於請求日。
  欄位數會隨年代變（2018 版 17 欄、2026 版 19 欄）→ **一律用欄名定位**：代號欄＝「代號」、股數欄＝「發行股數」。
- 歷史：tw-stock-data（TSD）本機 `data/universe/daily/YYYY-MM-DD.csv` 的 `shares` 欄（它就是抓上面兩個端點），
  2015-01-05 起。Opus 抽 2018-03-15、2026-11-06 兩天兩市場，重疊部分與官方 **100% 相同**。

## 欄位（`COLS`）
ticker（str，4 碼純數字）、market（"TW"／"TWO"）、date（datetime64，日）、issued_shares（int64，股）、
src（"official"＝我們自己抓；"tw-stock-data"＝TSD 匯入）。主鍵 (ticker, market, date)。

## 規矩（照 selfhost_raw_prices.py）
- 只抓 `raw_prices.parquet` 裡**已有的交易日**（它是我們的交易日曆）→ 交易日卻回 0 檔＝失敗，不是休市。
- 回應日期不符、stat 不是 OK、找不到欄位 → 該市場該日回 None（失敗）；任一市場失敗 → 該日整天不寫。
- 只存 4 碼純數字代號；股數 ≤0、空白、「-」「--」的列丟掉。
- 同主鍵：official 蓋 tw-stock-data；同 src 以新的為準（`merge_rows`）。official 蓋掉**數值不同**的 TSD 列要印 ::warning:: 筆數。
- 重試用 `_retry`（同其他收集腳本）；請求間隔 `SLEEP` 秒。

用法：
    python scripts/selfhost_shares.py                                   # 補 raw_prices 最近 REFRESH_DAYS 天中缺的交易日
    python scripts/selfhost_shares.py --start 2026-10-01 --end 2026-11-06
    python scripts/selfhost_shares.py --import-tsd <TSD根目錄>           # 一次性匯入歷史（只補檔案沒有的主鍵）
    python scripts/selfhost_shares.py --verify-tsd <TSD根目錄> --dates 2015-01-05,2018-03-15
        # 抓官方那幾天、跟 TSD 同日比對；任一天任一市場相符率 < VERIFY_MIN → exit 1
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
import _retry  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "selfhost" / "shares.parquet"
RAW_PRICES = ROOT / "data" / "selfhost" / "raw_prices.parquet"
TWSE = "https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS?date={d}&selectType=ALLBUT0999&response=json"
TPEX = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={d}&response=json"
UA = {"User-Agent": "Mozilla/5.0"}
COLS = ["ticker", "market", "date", "issued_shares", "src"]
SRC_OFFICIAL = "official"
SRC_TSD = "tw-stock-data"
SRC_PRIORITY = {SRC_TSD: 0, SRC_OFFICIAL: 1}     # 數字大的蓋小的
TSD_MARKET = {"twse": "TW", "tpex": "TWO"}       # TSD 的 emerging（興櫃）不收
REFRESH_DAYS = 30
SLEEP = 2.0
VERIFY_MIN = 0.999


def _get(url: str, retries: int = _retry.TRIES) -> dict | None:
    """照 selfhost_raw_prices._get：requests＋UA、timeout 40、失敗走 _retry.wait_after_failure；全失敗回 None。"""
    raise NotImplementedError


def _shares_num(x) -> int | None:
    """'1,234,567' → 1234567；'' '-' '--' None、非數字、≤0 → None。"""
    raise NotImplementedError


def _pick(fields: list[str], rows: list[list], code_col: str, market: str, d: date) -> pd.DataFrame:
    """依欄名取代號與股數兩欄，回 COLS 格式（src=official）。
    `code_col` 是代號欄的判定：'endswith代號' → 欄名 strip 後結尾是「代號」且大寫不含 ISIN；'代號' → 欄名 strip 後等於「代號」。
    找不到任一欄 → raise ValueError（呼叫端轉成 None＝失敗）。代號 strip 後非 4 碼純數字、股數無效的列丟掉。
    同代號重複 → 保留第一筆。"""
    raise NotImplementedError


def parse_twse(j: dict | None, d: date) -> pd.DataFrame | None:
    """MI_QFIIS 回應 → COLS（market=TW）。None＝失敗：j 為 None、stat != 'OK'、頂層 date != YYYYMMDD、欄位找不到、0 列。
    （只對交易日呼叫，所以 0 列一律是失敗。）"""
    raise NotImplementedError


def parse_tpex(j: dict | None, d: date) -> pd.DataFrame | None:
    """dailyQuotes 回應 → COLS（market=TWO）。None＝失敗：j 為 None、頂層 date != YYYYMMDD、無 tables／0 列、欄位找不到。"""
    raise NotImplementedError


def fetch_day(d: date) -> pd.DataFrame | None:
    """抓上市＋上櫃（各一次請求，之間 sleep SLEEP）；任一邊 None → None（整天不寫）。"""
    raise NotImplementedError


def trading_days(raw_prices: Path, start: date, end: date) -> list[date]:
    """raw_prices.parquet 的 date 欄中，落在 [start, end] 的不重複日期（升冪）。檔案不存在 → raise FileNotFoundError。"""
    raise NotImplementedError


def merge_rows(old: pd.DataFrame, new: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """合併兩份 COLS 表。同 (ticker, market, date)：SRC_PRIORITY 高者勝；同優先序 new 勝。
    回 (合併結果依 date, market, ticker 排序並 reset_index, overridden)；
    overridden＝official 蓋掉 tw-stock-data 且 issued_shares 不同的筆數。
    輸出 dtype：ticker str、market str、date datetime64[ns]、issued_shares int64、src str。"""
    raise NotImplementedError


def import_tsd(tsd_root: Path, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """讀 `<tsd_root>/data/universe/daily/YYYY-MM-DD.csv`（只讀 date, stock_id, market, shares 四欄，stock_id 用 str 讀）
    → COLS（src=tw-stock-data）。market 用 TSD_MARKET 對照，其餘市場丟；shares 空／≤0 丟；stock_id 非 4 碼純數字丟。
    檔名日期在 [start, end] 外的檔不讀。目錄不存在 → raise FileNotFoundError。"""
    raise NotImplementedError


def compare(official: pd.DataFrame, tsd: pd.DataFrame) -> pd.DataFrame:
    """同日比對。依 (date, market) 分組回一列：date, market, n_official, n_tsd, n_both, n_equal, ratio（=n_equal/n_both；n_both=0 → 0.0）。
    只比兩邊都有的 (ticker, market, date)。"""
    raise NotImplementedError


def shares_asof(shares: pd.DataFrame, when: date, max_stale_days: int = 10) -> pd.DataFrame:
    """給下游用：每個 (ticker, market) 取 date ≤ when 的最後一筆。
    回 columns=[ticker, market, issued_shares, obs_date]；when − obs_date > max_stale_days 天的不回（停牌太久不拿舊股數）。"""
    raise NotImplementedError


def write(df: pd.DataFrame, out: Path = OUT) -> None:
    """寫 parquet（zstd），寫前檢查：主鍵不重複、issued_shares 全 > 0、market ⊆ {TW, TWO}、src ⊆ SRC_PRIORITY；不符 → raise ValueError 不寫。"""
    raise NotImplementedError


def main(argv=None) -> int:
    """CLI（見檔頭用法）。
    - 預設／--start --end：區間預設 [今天−REFRESH_DAYS, 今天]；只抓 trading_days 中「檔案裡還沒有 src=official 的日子」；
      每抓 10 天 merge＋write 一次；印抓了幾天、失敗哪幾天、overridden 筆數；有失敗日 exit 1（已成功的照寫）。
    - --import-tsd ROOT：import_tsd → merge_rows(現有, tsd) 但**只補現有沒有的主鍵**（TSD 不得蓋任何現有列）→ write；印新增列數。
    - --verify-tsd ROOT --dates d1,d2,...：逐日 fetch_day＋import_tsd(同日) → compare → 印表；不寫檔；
      任一列 ratio < VERIFY_MIN 或任一天 fetch 失敗 → exit 1。"""
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
