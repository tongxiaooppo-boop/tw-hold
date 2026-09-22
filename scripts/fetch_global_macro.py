"""國際總經追蹤（總經導航第二段）——yfinance 一天一次抓「已完成的常規盤收盤」。

2026-09-13 從「只有美股」擴大成「跟台股連動的國際指數 + 美股總經背景」——
日經/恆生/KOSPI 是亞股情緒領先指標，隔夜表現常直接影響台股開盤，跟道瓊/那斯達克/
費半放在同一段「國際指數」比只看美股更貼近使用者真正在意的事。檔名跟著改，
避免半年後看到 `fetch_us_macro.py` 卻裝著日經以為自己記錯。

## 設計依據

2026-09-11 已定案（memory `tw-hold-us-stock-tracking-design`）：**絕不即時**。
那斯達克/紐約交易所往 24 小時盤外交易發展是事實，但常規盤收盤價仍是市場公認的
基準報價；即時報價要錢，這個專案的規模不到那個等級，雲端 app 本身也一律不發
即時請求（PRD §8）。這支腳本只在 CI 跑，app 只讀它的產出。

⚠️ **黃金/白銀/BTC 刻意不收**——這幾樣是真的 24/7 交易，沒有「收盤」這個市場
共識事件，硬取一個 UTC 時間點當「close」是假的，跟「只抓已完成收盤」的精神
直接衝突（2026-09-13 使用者親自否決）。期貨（如 CL=F 原油）有真正的每日結算，
邏輯上不受此限，但目前沒收——是完全不同的資產類別，混進「指數」段會很怪。

## 三種用途、一張長表

- **指數**（道瓊/那斯達克/費半/日經/恆生/KOSPI）：夠格套跟 0050/006201 一樣的
  MA60/MA200 多空卡（`reference/market_status.py` 本來就是吃任意收盤序列，
  不用改；但美股/國際指數這段畫面上只列 MA200，見機構慣例）。
- **VIX / 美債殖利率 / 美元指數**：不是「市場」，套多空卡沒意義，改用「現值 +
  漲跌 + 近一年分位」的數字卡（2026-09-13 使用者選定）。
- **七巨頭 + 美光**：個股，維持 app 一貫「不幫個股打分」的立場，只顯示
  現值 + 漲跌，不套多空判斷。

抓 2 年日線一次滿足全部——MA200 要 200+ 交易日、分位要近一年（~252 個交易日），
2 年绰绰有余。

## 排程

**不搭台股那條 `rebuild.yml`**——那條是台股收盤觸發（台北午後），此時美股/日經
以外的多數市場時段都對不上（日經恆生 KOSPI 其實台北時間下午就收了，但美股才是
最晚收的一個，排程照美股收盤後排最保險，反正日經/恆生/KOSPI 資料早就到齊）。
獨立開 `.github/workflows/global_macro.yml`，UTC 22:00 跑（美東 4pm 收盤最晚
21:00 UTC，留 1 小時緩衝），對應台北時間隔天早上 6 點。

用法：
    python scripts/fetch_global_macro.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

OUT = Path(__file__).resolve().parents[1] / "data" / "reference" / "global_macro.parquet"
META_OUT = OUT.with_name("global_macro_meta.json")

#: 這支腳本每次都整段 2 年全量覆寫（不是增量），理論上每檔的最新日期應該跟
#: 「這批一起抓到的最新日期」一致（都是同一次收盤後跑的）。2026-09-15 第一次
#: 自動排程就發生過美股個股 + 恆生卡在 4 天前、指數/利率卻是最新的情況——
#: Yahoo 那端對同一批次裡部分 ticker 回傳了還沒補齊尾端的資料，腳本本身沒報錯、
#: 也沒有任何地方會發現，直到有人手動去翻 parquet 才注意到。這裡補上「部分過期」
#: 偵測（跟原本只抓「整檔全空」的 missing 判斷是兩回事）。門檻抓 3 天，蓋過一個
#: 長週末，避免遇到假日就誤報。
STALE_THRESHOLD_DAYS = 3

#: symbol -> 中文名。四組意義不同，畫面端各自決定怎麼呈現，這裡只負責抓齊。
INDICES = {"^DJI": "道瓊", "^IXIC": "那斯達克", "^SOX": "費城半導體",
           "^N225": "日經225", "^HSI": "恆生指數", "^KS11": "韓國KOSPI"}
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


def _check_staleness(df: pd.DataFrame) -> list[dict]:
    """回傳落後參考日期超過門檻的 symbol 清單（部分過期，不是整檔全空）。"""
    latest = df.groupby("symbol")["date"].max()
    ref = latest.max()
    stale = []
    for sym, d in latest.items():
        lag = (ref - d).days
        if lag > STALE_THRESHOLD_DAYS:
            stale.append({"symbol": sym, "name": ALL_SYMBOLS[sym],
                          "latest": d.strftime("%Y-%m-%d"), "lag_days": lag})
    return stale


def _retry_stale(df: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    """對過期的 symbol 個別重抓一次短天期序列，補進去蓋掉過期的尾端。

    只挑「這批批次下載卡住的那幾檔」單獨重試，不整批重抓——那幾檔的問題是
    Yahoo 對長天期批次請求回應過期，短天期單檔請求常常打到不同的路徑而拿到
    當下資料（yfinance 已知現象，不是本專案能控制的）。10 天夠蓋過一個長週末。
    """
    frames = [df]
    for sym in symbols:
        try:
            raw = yf.download(sym, period="10d", interval="1d",
                               progress=False, auto_adjust=True)
            if isinstance(raw.columns, pd.MultiIndex):
                # 單檔 yf.download 仍回傳 MultiIndex 欄位（Price, Ticker）；
                # 不拉平的話 concat 時跟其他 frame 的單層 "symbol" 欄位對不上，
                # 整批 NaN 掉（2026-09-22 炸過：sorted() float/str 混列 TypeError）。
                raw.columns = raw.columns.get_level_values(0)
            sub = raw[["Close"]].dropna().rename(columns={"Close": "close"})
            if sub.empty:
                continue
            sub = sub.reset_index().rename(columns={"Date": "date"})
            sub["symbol"] = sym
            sub["date"] = pd.to_datetime(sub["date"]).dt.tz_localize(None)
            frames.append(sub[["symbol", "date", "close"]])
        except Exception as e:
            print(f"  ⚠️ {sym} 重試失敗：{e}")
    merged = pd.concat(frames, ignore_index=True)
    # 同一天同一檔以後蓋前——重試的資料排在 frames 後面，keep="last" 讓它贏。
    merged = merged.drop_duplicates(subset=["symbol", "date"], keep="last")
    return merged.sort_values(["symbol", "date"]).reset_index(drop=True)


def main() -> None:
    df = fetch()

    stale = _check_staleness(df)
    if stale:
        print(f"偵測到 {len(stale)} 檔部分過期，單獨重試：{[s['symbol'] for s in stale]}")
        df = _retry_stale(df, [s["symbol"] for s in stale])
        stale = _check_staleness(df)  # 重試後才是最終結果，寫進 meta／告警的是這份

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    got = sorted(df["symbol"].unique())
    missing = sorted(set(ALL_SYMBOLS) - set(got))
    print(f"寫入 {OUT}：{len(df)} 筆、{len(got)}/{len(ALL_SYMBOLS)} 檔"
          + (f"　缺：{missing}" if missing else ""))

    META_OUT.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reference_date": df["date"].max().strftime("%Y-%m-%d"),
        "stale": stale,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    for s in stale:
        print(f"::warning::{s['symbol']}（{s['name']}）資料落後 {s['lag_days']} 天"
              f"（最新只到 {s['latest']}）——Yahoo 這批可能沒補齊，不是整檔全空但已經過期")


if __name__ == "__main__":
    main()
