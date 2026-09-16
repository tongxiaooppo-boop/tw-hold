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

只餵 `reference/market_status.py`（總經導航的 MA60/MA200 顯示卡），**不是**
`reference/regime.py` 用的大盤代理，兩者判斷邏輯本來就已經脫鉤。

## 驗證（2026-09-16 加）

原本是「抓到就整份覆寫」，零驗證——而 FinMind 實測**真的會吐壞資料**：
落地檔裡 2016-08-24、2017-04-10 兩筆 `close = 0`（日報酬因此是 `inf`）。
今天畫面沒被影響只是因為 `market_status` 只吃尾端 200 筆，同樣的 0 若落在最近
一天，卡片就會顯示 `inf%`——正是使用者說「不可原諒」的那一類。

現在跟 0050 共用 `reference/price_series_guard.py`：先 sanitize（丟掉 0／NaN／
重複日期，這種列每次全量重抓都會再來，設計成「看到就拒絕」會讓資料凍死），
再 validate（筆數縮水／日期倒退／歷史被改寫／最後一筆跳空 → 保留舊檔、exit 1）。
這支是**全量重抓**，縮水風險比 0050 更高，那條檢查對它更重要。

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

from reference import price_series_guard as guard
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


def main() -> int:
    new = guard.sanitize(fetch())
    old = guard.load_clean(OUT)
    reasons = guard.validate(new, old)
    if reasons:
        for r in reasons:
            print(f"[REJECT] {r}")
        print("→ 不覆寫，保留舊檔案（前一日的資料錯誤不可原諒，寧可暫時舊）")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    new.to_parquet(OUT, index=False)
    print(f"[OK] 寫入 {OUT}：{len(new)} 筆，"
          f"{new['date'].min().date()} ~ {new['date'].max().date()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
