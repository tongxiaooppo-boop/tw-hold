"""把 tw-swing bundle 裡本來就有發佈的小檔 `index_0050.parquet`（tw-swing 稱 U1b，
遠比整包 `prices_adj.parquet` 小）從 CI 暫存的 `data/upstream/` 驗證後複製進
`data/reference/`（committed，app 執行期讀，不用再拖一整包 bundle）——2026-09-16 加，
理由見 `reference/index_proxy.load_0050` 檔頭。

跟 `scripts/fetch_index_proxy.py`（006201，獨立向 FinMind 抓）不同：0050 不用再打
一次 API，tw-swing 每天 publish 時就已經附了這份小檔，這裡只是「驗證後搬過去」。

## 驗證邏輯（使用者原話：「前一日的資料錯誤不可原諒」——寧可保留舊資料，不要
覆蓋成錯的）

  1. 檔案要存在、非空、有 date/close 兩欄
  2. 新檔最新日期 **不能比目前已 commit 的舊檔還舊**——防止上游那天資料不全/
     回傳到一半就斷線，寫出一份「有資料但是舊的」蓋掉本來新的
  3. 新檔最後一筆對前一筆的漲跌幅不能超過 `MAX_DAY_MOVE`——0050 是 ETF，實務上
     不會有個股那種漲跌停以外的跳空，超過門檻視為資料損毀（欄位錯位／單位跑掉／
     ticker 抓錯）的警訊，不是「今天剛好大跌」的正常區間

三項有一項不過，**保留舊檔案、不覆寫**，印出原因、exit 1（rebuild.yml 那步
`continue-on-error: true`，不擋主線三清單，但會被後面的告警步驟撿到）。

用法：
    python scripts/promote_index_0050.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "data" / "upstream" / "index_0050.parquet"
DEST = REPO / "data" / "reference" / "index_0050.parquet"
MAX_DAY_MOVE = 0.15  # 15%——0050 是 ETF，正常交易日不會跳這麼多


def _load_close(p: Path) -> pd.DataFrame | None:
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if df.empty or "date" not in df.columns or "close" not in df.columns:
        return None
    df = df[["date", "close"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def validate_and_promote() -> int:
    if not SRC.exists():
        print(f"[SKIP] {SRC} 不存在——這次 bundle 沒附 U1b/index_0050，保留舊檔案")
        return 0

    new = _load_close(SRC)
    if new is None:
        print(f"[REJECT] {SRC} 是空的或缺 date/close 欄——不覆寫，保留舊檔案")
        return 1

    old = _load_close(DEST)
    new_last = new["date"].iloc[-1]
    if old is not None and not old.empty:
        old_last = old["date"].iloc[-1]
        if new_last < old_last:
            print(f"[REJECT] 新檔最後日期 {new_last.date()} 比目前已發佈的 "
                  f"{old_last.date()} 還舊——不覆寫，保留舊檔案")
            return 1

    if len(new) >= 2:
        prev_close, last_close = new["close"].iloc[-2], new["close"].iloc[-1]
        if prev_close and abs(last_close / prev_close - 1.0) > MAX_DAY_MOVE:
            print(f"[REJECT] 最後一筆漲跌幅 {last_close / prev_close - 1.0:+.1%} "
                  f"超過門檻 ±{MAX_DAY_MOVE:.0%}，疑似資料損毀——不覆寫，保留舊檔案")
            return 1

    DEST.parent.mkdir(parents=True, exist_ok=True)
    new.to_parquet(DEST, index=False)
    print(f"[OK] 寫入 {DEST}：{len(new)} 筆，最後一筆 {new_last.date()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(validate_and_promote())
