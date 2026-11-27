"""ETF 分頁衍生資料：data/etf/{prices,events}.parquet → data/derived/etf.json。

框架 2026-11-27（Opus 定，實作者不得改函式簽名、欄名、JSON schema；有問題停下回報）。
決策文件：d:/g/claude/etf_display_2026-11-27/DECISION.md

輸入（scripts/etf_track.py 產出）
- prices：ticker, date(datetime64), open, high, low, close, volume, source   —— 原始未還原價
- events：ticker, date, type('div'|'split'), cash(每股現金，該事件當時的股數口徑；split 為 NaN),
          prev_close, ref_price, factor(div＝ref/prev；split＝新價÷舊價), source

還原（向後還原，最後一天＝原始價）
- tr_*（總報酬還原）：t 日價 × Π{事件 e：e.date > t} e.factor（div 與 split 都乘）
- sp_*（只還原分割）：t 日價 × Π{split e：e.date > t} e.factor
- 事件「當天」不乘自己（除息日當天的價已是除息後）。
- 只用該檔「最後一筆價格日（含）以前」的事件；更晚的事件（例如分割表裡還沒到的日子）忽略，保證最後一天＝原始價。
- 總報酬還原＝除息日按參考價把配息買回（近似，跟實際隔天開盤買回有小差距；EXPLAIN／DCA_NOTE 已註明）。

日曆：每檔用自己的價格日期當交易日曆。單檔計算（ma、ret_1y、yield、yearly、dca）一律以「該檔 last_date」當 asof；
停牌沒有最新價的檔不補價。頂層 asof 只是顯示用。

輸出 data/derived/etf.json（schema 固定）
{
  "asof": "YYYY-MM-DD",                 # 所有白名單 ETF 最新一筆日期的最大值
  "generated_at": "YYYY-MM-DDTHH:MM:SSZ",
  "rows": [                             # 依 GROUPS 順序、組內依代號
    {"code": str, "name": str, "group": "cap"|"div"|"lev", "close": float, "last_date": "YYYY-MM-DD",
     "first_date": "YYYY-MM-DD",
     "ma": {"60": float|null, "120": float|null, "240": float|null},   # 收盤相對均線位置（0.031＝+3.1%）
     "ret_1y": float|null,              # 近一年總報酬（tr_close）
     "yield_1y": float|null, "yield_1y_n": int|null}                  # 只有 div 組有值，其他組 null
  ],
  "missing": [str],                     # 白名單裡沒有任何價格的代號
  "yearly": {code: {"YYYY": {"rate": float, "partial": bool}}},       # 只有 div 組
  "dca": {code: {"reinvest": DCA|null, "cash": DCA|null,
                 "bench_reinvest": DCA|null, "bench_cash": DCA|null}}  # bench＝同扣款月份的 0050；0050 自己為 null
}
DCA = {"start": "YYYY-MM-DD"(第一次買進日), "end": "YYYY-MM-DD"(傳入的 asof＝該檔 last_date), "buys": int,
       "invested": float, "value": float, "irr": float|null, "worst": float}
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from reference.etf_universe import (BENCH, DCA_AMOUNT, DCA_MIN_BUYS, ETF_UNIVERSE, GROUPS, JUMP_LIMIT,
                                    MA_WINDOWS, YEARLY_YIELD_YEARS)

ROOT = Path(__file__).resolve().parent
ETF_DIR = ROOT / "data" / "etf"
OUT = ROOT / "data" / "derived" / "etf.json"


def load_inputs(etf_dir: Path = ETF_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """讀 prices.parquet、events.parquet；date 轉 datetime64、依 (ticker, date) 排序。"""
    raise NotImplementedError


def adjust(prices: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """回傳 prices 加四欄 tr_open, tr_close, sp_open, sp_close（定義見模組說明）。不改原欄。"""
    raise NotImplementedError


def check_jumps(adj: pd.DataFrame) -> list[str]:
    """每檔相鄰兩筆 tr_close 比值超出 JUMP_LIMIT（含邊界外）→ 一條訊息 f"{ticker} {date:%Y-%m-%d} {ratio:.3f}"。"""
    raise NotImplementedError


def ma_position(tr_close: pd.Series, n: int) -> float | None:
    """最後一筆 ÷ 最後 n 筆平均 − 1；不足 n 筆 → None。"""
    raise NotImplementedError


def ret_1y(tr_close: pd.Series, asof: pd.Timestamp) -> float | None:
    """tr_close（index＝date）在 asof 的值 ÷ 「asof−365 天當天或之前最後一筆」的值 − 1。
    第一筆日期 > asof−365 天 → None。"""
    raise NotImplementedError


def cash_in_current_units(events: pd.DataFrame) -> pd.Series:
    """單一檔的 div 事件，每筆 cash × Π{該事件日期之後的 split factor}，index＝除息日。
    （一拆四後，舊的 1 元現金＝每新股 0.25 元）"""
    raise NotImplementedError


def trailing_yield(events: pd.DataFrame, close: float, asof: pd.Timestamp,
                   first_date: pd.Timestamp) -> tuple[float | None, int | None]:
    """近一年配息率：除息日落在 (asof−365 天, asof] 的 cash_in_current_units 合計 ÷ close，與筆數。
    照日期區間算，13 次就算 13 次。first_date > asof−365 天 → (None, None)。區間內 0 筆 → (0.0, 0)。"""
    raise NotImplementedError


def yearly_yields(sp_close: pd.Series, events: pd.DataFrame, asof: pd.Timestamp,
                  years: int = YEARLY_YIELD_YEARS) -> dict[str, dict]:
    """最近 `years` 個曆年（含 asof 那年），每年 {"rate", "partial"}：
    rate＝該年除息的 cash_in_current_units 合計 ÷ 該年第一筆 sp_close（上市當年＝上市後第一筆）。
    partial＝上市當年 或 asof 那年。該年沒有任何價格 → 不放這年。"""
    raise NotImplementedError


def xirr(flows: list[tuple[pd.Timestamp, float]]) -> float | None:
    """年化資金加權報酬：Σ amount × (1+r)^(−天數/365) = 0；二分法 r∈[−0.99, 10]，誤差 1e-7。解不出 → None。"""
    raise NotImplementedError


def dca(adj: pd.DataFrame, events: pd.DataFrame, asof: pd.Timestamp, reinvest: bool,
        amount: float = DCA_AMOUNT, start_month: str | None = None) -> dict | None:
    """單一檔定期定額（adj 只含該檔、已依日期排序；events 只含該檔）。
    - 扣款日＝每個月第一個交易日；買進＝扣款日的「下一個」交易日開盤；只算買進日 ≤ asof 的。
    - 起始月：start_month（'YYYY-MM'）給了就用；否則＝第一筆價格所在月的「下個月」。
    - reinvest=True：units += amount / tr_open[買進日]；市值_t＝units_t × tr_close_t。
    - reinvest=False：units += amount / sp_open[買進日]；每個 div 事件日 e，
      現金 += （買進日 < e.date 的累計 units）× cash_in_current_units[e]；市值_t＝units_t × sp_close_t ＋ 現金_t。
    - worst＝第一次買進日起每個交易日 min(市值_t ÷ 累計投入_t − 1)（買進日當天收盤已計入當天的投入）。
    - irr＝xirr（每次買進 −amount、asof 那天 +期末市值）。
    - 買進次數 < DCA_MIN_BUYS → None。
    回傳 DCA dict（見模組說明）。"""
    raise NotImplementedError


def build(prices: pd.DataFrame, events: pd.DataFrame, now: datetime | None = None) -> dict:
    """組 etf.json。只處理 ETF_UNIVERSE 內的代號；先 check_jumps，有任何訊息 → raise ValueError（整串訊息）。
    bench_*：用 dca(0050, asof＝該檔 last_date, start_month＝該檔 reinvest 結果 start 的月份) 算；
    該檔 reinvest 為 None → bench 都 None。"""
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    """讀 → build → 寫 OUT（先建父目錄；ensure_ascii=False, indent=1）。ValueError → 印到 stderr、回 1、不寫檔。
    路徑一律用 ROOT 相對（CI 的工作目錄不一定是 repo 根）。"""
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
