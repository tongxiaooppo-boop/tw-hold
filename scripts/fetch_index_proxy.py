"""補一個 tw-swing data_pack 沒有的市場代理：006201（元大富櫃50，唯一追蹤櫃買
富櫃50指數的 ETF）。

## 為什麼要另開一支，不是等上游 data_pack 補

`tw-swing`/`tw-hold` 的 ~1969 檔日線universe 來自別人 repo 發布的 data_pack.zip
（見 memory「上游 data_pack 單點依賴」）——006201 不在裡面，且我們不控制那個
universe 的收錄範圍，等他們加是不可控的等待。

006201 是一般 ETF（跟 0050 一樣掛在 TWSE），FinMind `TaiwanStockPrice`
免費層可以直接查到（2026-09-13 實測：匿名、免 token，2011-01-27 起 3800+ 筆）。
一檔股票、一次性歷史 + 之後每次重跑重抓一次全history（資料量小，不用做增量
append 的複雜度），完全不碰 data_pack 那條依賴鏈。

## 用途

只餵 `reference/market_status.py`（總經羅盤的 MA60/MA200 顯示卡），**不是**
`reference/regime.py` 用的大盤代理，兩者判斷邏輯本來就已經脫鉤。

## 排程

沒有獨立 cron——搭 tw-hold 既有的 `rebuild.yml`（由 tw-swing 台股 bundle 發佈
觸發），反正 006201 也是台股（上櫃）交易時段，跟現有觸發時間點天然對齊，不像
美股那樣要另外排時區。

用法：
    python scripts/fetch_index_proxy.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from reference.finmind_client import Client, read_token

TICKER = "006201"
START_DATE = "2011-01-01"  # 006201 掛牌 2011-01-27，往前多留一點沒差
OUT = Path(__file__).resolve().parents[1] / "data" / "reference" / "index_006201.parquet"


def fetch() -> pd.DataFrame:
    client = Client(token=read_token())
    rows = client.get("TaiwanStockPrice", data_id=TICKER, start_date=START_DATE)
    if not rows:
        raise RuntimeError(f"FinMind 對 {TICKER} 回傳空資料——ticker 打錯或 API 有異動？")
    df = pd.DataFrame(rows)[["date", "close"]]
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def main() -> None:
    df = fetch()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    print(f"寫入 {OUT}：{len(df)} 筆，{df['date'].min().date()} ~ {df['date'].max().date()}")


if __name__ == "__main__":
    main()
