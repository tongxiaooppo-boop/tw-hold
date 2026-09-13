"""美股總經追蹤（總經羅盤第二段）——yfinance 一天一次抓「已完成的常規盤收盤」。

## 設計依據

2026-09-11 已定案（memory `tw-hold-us-stock-tracking-design`）：**絕不即時**。
那斯達克/紐約交易所往 24 小時盤外交易發展是事實，但常規盤（美東 4pm）收盤價仍是
市場公認的基準報價；即時報價要錢，這個專案的規模不到那個等級，雲端 app 本身也
一律不發即時請求（PRD §8）。這支腳本只在 CI 跑，app 只讀它的產出。

## 三種用途、一張長表

- **指數**（道瓊/那斯達克/費半）：夠格套跟 0050/006201 一樣的 MA60/MA200
  多空卡（`reference/market_status.py` 本來就是吃任意收盤序列，不用改）。
- **VIX / 美債殖利率 / 美元指數**：不是「市場」，套多空卡沒意義，改用「現值 +
  漲跌 + 近一年分位」的數字卡（2026-09-13 使用者選定）。
- **七巨頭 + 美光**：個股，維持 app 一貫「不幫個股打分」的立場，只顯示
  現值 + 漲跌，不套多空判斷。

抓 2 年日線一次滿足全部——MA200 要 200+ 交易日、分位要近一年（~252 個交易日），
2 年绰绰有余。

## 排程

**不搭台股那條 `rebuild.yml`**——那條是台股收盤觸發（台北午後），此時美股都還沒開盤。
獨立開 `.github/workflows/us_macro.yml`，UTC 22:00 跑（美東 4pm 收盤最晚 21:00 UTC，
留 1 小時緩衝），對應台北時間隔天早上 6 點。

用法：
    python scripts/fetch_us_macro.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yfinance as yf

OUT = Path(__file__).resolve().parents[1] / "data" / "reference" / "us_macro.parquet"

#: symbol -> 中文名。三組意義不同，畫面端各自決定怎麼呈現，這裡只負責抓齊。
INDICES = {"^DJI": "道瓊", "^IXIC": "那斯達克", "^SOX": "費城半導體"}
GAUGES = {"^VIX": "VIX", "DX-Y.NYB": "美元指數",
          "^IRX": "美債短天期(13週)", "^TNX": "美債10年", "^TYX": "美債長天期(30年)"}
STOCKS = {"AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet", "AMZN": "Amazon",
          "META": "Meta", "NVDA": "NVIDIA", "TSLA": "Tesla", "MU": "美光"}

ALL_SYMBOLS = {**INDICES, **GAUGES, **STOCKS}


def fetch() -> pd.DataFrame:
    raw = yf.download(list(ALL_SYMBOLS), period="2y", interval="1d",
                       progress=False, group_by="ticker", auto_adjust=True)
    frames = []
    for sym in ALL_SYMBOLS:
        sub = raw[sym][["Close"]].dropna().rename(columns={"Close": "close"})
        if sub.empty:
            print(f"  ⚠️ {sym}（{ALL_SYMBOLS[sym]}）沒抓到資料")
            continue
        sub = sub.reset_index().rename(columns={"Date": "date"})
        sub["symbol"] = sym
        frames.append(sub[["symbol", "date", "close"]])
    if not frames:
        raise RuntimeError("yfinance 全部抓空——網路問題或 Yahoo 介面改了？")
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None)
    return out.sort_values(["symbol", "date"]).reset_index(drop=True)


def main() -> None:
    df = fetch()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    got = sorted(df["symbol"].unique())
    missing = sorted(set(ALL_SYMBOLS) - set(got))
    print(f"寫入 {OUT}：{len(df)} 筆、{len(got)}/{len(ALL_SYMBOLS)} 檔"
          + (f"　缺：{missing}" if missing else ""))


if __name__ == "__main__":
    main()
