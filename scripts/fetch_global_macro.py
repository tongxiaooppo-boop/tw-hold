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
獨立開 `.github/workflows/global_macro.yml`，UTC 22:37 跑（美東 4pm 收盤最晚
21:00 UTC，留 1 小時緩衝），對應台北時間隔天早上約 6:37。

用法：
    python scripts/fetch_global_macro.py
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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

#: 日經/恆生/KOSPI 各自的國定連假（日本黃金週、農曆年、韓國連假）常讓這三檔
#: 相對美股落後 4~6 天，用同一個 3 天門檻會連續好幾天誤報、還每次觸發一次
#: 沒意義的 _retry_stale 重抓。2026-09-22 Opus 審出，門檻放寬到 7。
_ASIA_STALE_THRESHOLD_DAYS = {"^N225": 7, "^HSI": 7, "^KS11": 7}

#: symbol -> 中文名。四組意義不同，畫面端各自決定怎麼呈現，這裡只負責抓齊。
INDICES = {"^DJI": "道瓊", "^IXIC": "那斯達克", "^SOX": "費城半導體",
           "^N225": "日經225", "^HSI": "恆生指數", "^KS11": "韓國KOSPI"}
GAUGES = {"^VIX": "VIX", "DX-Y.NYB": "美元指數",
          "^IRX": "美債短天期(13週)", "^TNX": "美債10年", "^TYX": "美債長天期(30年)"}
STOCKS = {"AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet", "AMZN": "Amazon",
          "META": "Meta", "NVDA": "NVIDIA", "TSLA": "Tesla", "MU": "美光"}

ALL_SYMBOLS = {**INDICES, **GAUGES, **STOCKS}


#: 亞洲三大指數收盤（台北時間）：日經 12:30、KOSPI 14:30、恆生 16:00。排程延遲時（實測 2~9 小時）
#: 台北上午就跑，這三檔「今天」那一列是盤中價——Yahoo 日線會把盤中即時價當當日收盤。
#: 2026-10-20 Opus 審出：本機 meta 10/16 00:42 UTC（台北 08:42）的快照裡 ^N225、^KS11 已有
#: 10/16 那列而美股只到 10/15，且這列會被拿去當 reference_date。台北 17:00 前一律丟掉「今天」那列。
_ASIA_CLOSE_CUTOFF_HOUR_TPE = 17
_ASIA_SYMBOLS = ("^N225", "^HSI", "^KS11")


def _drop_intraday_asia(df: pd.DataFrame, now_utc: datetime | None = None) -> pd.DataFrame:
    now_tpe = (now_utc or datetime.now(timezone.utc)) + timedelta(hours=8)
    if now_tpe.hour >= _ASIA_CLOSE_CUTOFF_HOUR_TPE:
        return df
    today = pd.Timestamp(now_tpe.date())
    bad = df["symbol"].isin(_ASIA_SYMBOLS) & (df["date"] >= today)
    if bad.any():
        print(f"  ⚠️ 台北 {now_tpe:%H:%M} 亞洲盤還沒全收，丟掉盤中價：" +
              "、".join(sorted(f"{r.symbol} {r.date:%m-%d}" for r in df[bad].itertuples())))
    return df[~bad].reset_index(drop=True)


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
    out = _drop_intraday_asia(out)
    return out.sort_values(["symbol", "date"]).reset_index(drop=True)


def _check_staleness(df: pd.DataFrame) -> list[dict]:
    """回傳落後參考日期超過門檻的 symbol 清單（部分過期，不是整檔全空）。"""
    latest = df.groupby("symbol")["date"].max()
    ref = latest.max()
    stale = []
    for sym, d in latest.items():
        lag = (ref - d).days
        threshold = _ASIA_STALE_THRESHOLD_DAYS.get(sym, STALE_THRESHOLD_DAYS)
        if lag > threshold:
            stale.append({"symbol": sym, "name": ALL_SYMBOLS[sym],
                          "latest": d.strftime("%Y-%m-%d"), "lag_days": lag})
    return stale


def fetch_quotes(symbols) -> dict[str, dict]:
    """美股個股抓取當下的最新價＋Yahoo 的前一收盤（`fast_info`），寫進 meta 的 `quotes`。

    2026-10-23 使用者拍板：美股幾乎 24 小時交易（盤前／盤後／夜盤），沒有「收盤」概念了，
    個股卡改顯示抓取當下的價、標抓取時間。順便避開 Yahoo 日線的坑：當天實測個股前一交易日
    那根日線收盤是 NaN（指數正常），日線卡天天晚一天。單檔失敗就略過，App 退回日線卡。"""
    out = {}
    for sym in symbols:
        try:
            fi = yf.Ticker(sym).fast_info
            price, prev = float(fi["lastPrice"]), float(fi["previousClose"])
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠️ {sym} 即時報價失敗：{e}")
            continue
        if price > 0 and prev > 0:
            out[sym] = {"price": round(price, 4), "prev_close": round(prev, 4)}
    return out


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
    merged = _drop_intraday_asia(merged)          # 重試抓的短天期序列一樣可能帶盤中價
    return merged.sort_values(["symbol", "date"]).reset_index(drop=True)

#: 2026-11-16 Yahoo 日線三檔亞洲指數 Close 全是 NaN（被 dropna 丟掉、最新日停在前一個交易日），
#: 同一天小時線卻完整（最後一根收盤與官方只差約 0.06%）。日線缺平日時用小時線最後一根補，
#: 並記進 meta 的 estimated，畫面標「推估」。
_HOURLY_FILL_LOOKBACK_DAYS = 10
_HOURLY_FILL_MIN_BARS = 3


def _fetch_hourly(symbol: str, days: int) -> pd.Series:
    """yf.Ticker(symbol).history(period=f"{days}d", interval="1h")["Close"].dropna()。
    index 保留 Yahoo 給的交易所時區。任何例外都回空 Series（印一行 ⚠️），不中斷。"""
    try:
        h = yf.Ticker(symbol).history(period=f"{days}d", interval="1h")
        return h["Close"].dropna()
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️ {symbol} 小時線抓取失敗：{e}")
        return pd.Series(dtype="float64")


def _fill_gaps_from_hourly(df: pd.DataFrame, symbols=_ASIA_SYMBOLS, now_utc: datetime | None = None,
                           fetch_hourly=None) -> tuple[pd.DataFrame, list[dict]]:
    """日線缺的平日用小時線最後一根補。回 (新 df, 補了哪些 [{"symbol","date":"YYYY-MM-DD","close"}])。"""
    fetch_hourly = fetch_hourly or _fetch_hourly
    today_tpe = ((now_utc or datetime.now(timezone.utc)) + timedelta(hours=8)).date()
    earliest = today_tpe - timedelta(days=_HOURLY_FILL_LOOKBACK_DAYS)
    new_rows, estimated = [], []
    for sym in symbols:
        if not (df["symbol"] == sym).any():
            # 日線整檔沒抓到（2026-11-17 實測 ^N225 批次下載偶爾「possibly delisted」）時不補：
            # 補了會變成只有幾列推估值的序列，卡片拿去算均線比整檔缺更誤導，交給原本的缺資料處理。
            continue
        try:
            hourly = fetch_hourly(sym, _HOURLY_FILL_LOOKBACK_DAYS)
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠️ {sym} 小時線抓取失敗：{e}")
            continue
        if hourly is None or len(hourly) == 0:
            continue
        hourly = hourly.dropna().sort_index()
        have = set(df.loc[df["symbol"] == sym, "date"].dt.date)
        local_dates = pd.Series(hourly.index.date, index=hourly.index)
        for d, grp in hourly.groupby(local_dates):
            if (len(grp) < _HOURLY_FILL_MIN_BARS or d.weekday() >= 5 or d >= today_tpe
                    or d < earliest or d in have):
                continue
            close = float(grp.iloc[-1])
            new_rows.append({"symbol": sym, "date": pd.Timestamp(d), "close": close})
            estimated.append({"symbol": sym, "date": d.strftime("%Y-%m-%d"), "close": close})
    if not new_rows:
        return df, []
    add = pd.DataFrame(new_rows).astype(df.dtypes.to_dict())
    out = pd.concat([df, add], ignore_index=True)
    out = out.sort_values(["symbol", "date"]).reset_index(drop=True)
    estimated.sort(key=lambda r: (r["symbol"], r["date"]))
    return out, estimated


def _business_days_since(d, today) -> int:
    """`d`（date）到 `today`（date）之間的營業日數，只扣週末，不管國定假日——
    跟 `STALE_THRESHOLD_DAYS` 同精神，粗略夠用，不追求精確。"""
    n, cur = 0, d
    while cur < today:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


def _carry_forward(df: pd.DataFrame, old: pd.DataFrame | None,
                   symbols: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """整檔漏抓的 symbol 用上一版（執行前的 OUT）補回歷史；新抓的列優先。

    回 (新 df, carried)：carried＝補完後仍完全沒有新列、只靠舊資料的 symbol。
    old 沒有該檔就維持缺（不報錯）。"""
    if old is None or old.empty or not symbols:
        return df, []
    old_rows = old[old["symbol"].isin(symbols)]
    if old_rows.empty:
        return df, []
    have_new = set(df["symbol"])
    carried = sorted(s for s in symbols if s not in have_new and s in set(old_rows["symbol"]))
    old_rows = old_rows[["symbol", "date", "close"]].copy()
    old_rows["date"] = pd.to_datetime(old_rows["date"])
    merged = pd.concat([old_rows, df], ignore_index=True)        # 新抓的排後面 → keep="last" 新值贏
    merged = merged.drop_duplicates(subset=["symbol", "date"], keep="last")
    return merged.sort_values(["symbol", "date"]).reset_index(drop=True), carried


def _read_old() -> pd.DataFrame | None:
    try:
        return pd.read_parquet(OUT) if OUT.exists() else None
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️ 讀不到上一版 {OUT.name}：{e}")
        return None


def main() -> None:
    old = _read_old()                       # 要在寫入 OUT 之前讀
    df = fetch()

    missing0 = sorted(set(ALL_SYMBOLS) - set(df["symbol"]))
    carried: list[str] = []
    if missing0:
        print(f"整檔沒抓到，單檔重抓：{missing0}")
        df = _retry_stale(df, missing0)
        df, carried = _carry_forward(df, old, missing0)
        if carried:
            print(f"::warning::沿用上一版：{carried}")

    stale = _check_staleness(df)
    if stale:
        print(f"偵測到 {len(stale)} 檔部分過期，單獨重試：{[s['symbol'] for s in stale]}")
        df = _retry_stale(df, [s["symbol"] for s in stale])
        stale = _check_staleness(df)  # 重試後才是最終結果，寫進 meta／告警的是這份

    df, estimated = _fill_gaps_from_hourly(df)
    if estimated:
        print(f"小時線補 {len(estimated)} 列：" +
              "、".join(f"{e['symbol']} {e['date'][5:]}" for e in estimated))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    got = sorted(df["symbol"].unique())
    missing = sorted(set(ALL_SYMBOLS) - set(got))
    print(f"寫入 {OUT}：{len(df)} 筆、{len(got)}/{len(ALL_SYMBOLS)} 檔"
          + (f"　缺：{missing}" if missing else ""))

    # 絕對新鮮度——2026-09-22 Opus 審出：`_check_staleness()` 只比「這批自己
    # 最新的那檔」，如果整批（例如這支 CI 連續好幾天沒跑成功）都卡在同一個
    # 舊日期，彼此之間沒有落差，stale 會是空的，app 卡片一個 ⚠️ 都不會出現。
    # 這裡另外記一個跟「執行當下」比的落後天數，才是使用者真正在意的
    # 「這批資料是不是新的」。
    quotes = fetch_quotes(STOCKS)
    print(f"美股個股即時報價 {len(quotes)}/{len(STOCKS)} 檔")

    ref_date = df["date"].max().date()
    today = datetime.now(timezone.utc).date()
    snapshot_lag_days = _business_days_since(ref_date, today)

    META_OUT.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reference_date": df["date"].max().strftime("%Y-%m-%d"),
        "snapshot_lag_days": snapshot_lag_days,
        "stale": stale,
        "quotes": quotes,
        "estimated": estimated,
        "carried_forward": carried,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    if snapshot_lag_days > 2:
        print(f"::warning::整批快照落後 {snapshot_lag_days} 個營業日"
              f"（最新只到 {ref_date}）——這條 workflow 本身可能連續沒跑成功")
    for s in stale:
        print(f"::warning::{s['symbol']}（{s['name']}）資料落後 {s['lag_days']} 天"
              f"（最新只到 {s['latest']}）——Yahoo 這批可能沒補齊，不是整檔全空但已經過期")


if __name__ == "__main__":
    main()
