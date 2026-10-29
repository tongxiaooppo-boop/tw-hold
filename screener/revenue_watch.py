"""「月營收」分頁的計算層（2026-10-29 框架由 Opus 定，實作由 Cline 填）。

全部是純函式：不連網、不讀檔，餵 DataFrame / dict 就能測。讀檔與組裝在
`build_revenue_watch.py`；排版在 `app/streamlit_app.py::_revenue_page`。

## 產出 `data/derived/revenue_watch.json` 的格式（介面，不准改）

```
{
  "built_at":   "2026-10-29T18:52:00+08:00",
  "price_date": "2026-10-29",          # 現價／均線用到的最後收盤日
  "universe_note": "市值前500∪成交值前500（universe.parquet in_universe，與其他清單一致，asof 2026-10-19）",
  "periods": [                         # 最新的營收月份在前，固定 2 期（見 periods_to_show）
    {
      "month": "2026-09",              # 營收月份
      "pub_month": "2026-10",          # 公布月份＝month 的下一個月
      "source": "mops" | "bundle",     # 這期營收數字的來源（mops＝data/revenue_mops/<month>.parquet）
      "has_first_seen": false,         # 這期有沒有逐家「第一次看到」時間（2026-10 營收起才有）
      "n_universe": 650,
      "n_published": 498,              # universe 裡已公布的家數
      "rows": [Row, ...]               # universe 裡已公布的每一家（排序／取前 30 是 UI 的事）
    }
  ]
}
```

Row（`make_row` 回傳；金額單位元、比例用小數 0.123＝12.3%、缺值一律 None）：

| 欄位 | 說明 |
|---|---|
| code, name, industry | 裸代號、名稱、產業（universe.parquet） |
| market_cap | 市值（元），universe.parquet |
| revenue, revenue_prev_month, revenue_last_year | 當月、上月、去年同月營收 |
| mom, yoy, cum_yoy | 月增、年增、累計年增（分母 ≤0 或缺 → None） |
| note | 公司填的備註；"-"、"" → "" |
| first_seen_at | "YYYY-MM-DD HH:MM" 或 None（bundle 來源一律 None） |
| revised | 第一次看到後數字被改過（bundle 來源一律 False） |
| yoy_streak | 到這個月為止「年增 > 0」連續幾個月（本月年增 ≤0 或缺 → 0） |
| record_high | 本月營收 ≥ 歷史所有更早月份的最大值（歷史少於 12 個月 → False） |
| low_base | revenue_last_year 缺值或 < LOW_BASE_REV |
| price, ma20, ma60 | 最新收盤、20 日／60 日均（月線／季線），還原價 |
| above_ma20, above_ma60 | price > ma；任一缺 → None |
| est_ok, est_reason | valuation.estimate 的 ok／reason |
| run_eps, est_eps | estimate 的 eps.run_ex（年化試算）／year.est（今年預估） |
| band_low, band_mid, band_high | estimate 的 band（便宜／合理／昂貴） |
| growth_price | estimate 的 growth_price（成長價） |
| upside_mid, upside_growth | band_mid / price − 1、growth_price / price − 1 |
| at_valuation | price ≥ band_mid；任一缺 → None |
| cyclical | estimate 的 cycle.pct ≥ 0.8（營益率在歷史高檔，景氣循環股警示） |
| pe_wide | estimate 的 pe.wide（近 5 年各年平均本益比差 > 4 倍，歷史倍數不可靠）；2026-10-29 Opus 加：9 月實測價差前 30 名有 15 檔是這種、23 檔是 cyclical，價差動輒 +500%，③ 預設排除這兩類 |
| warns | estimate 的 warns ＋ infos（字串清單，原文） |
"""
from __future__ import annotations

import pandas as pd

LOW_BASE_REV = 1e8          # 去年同月營收 < 1 億元 → 低基期，年增排行預設排除
UPSIDE_GOAL = 0.40          # 估值價差門檻（使用者朋友的口徑：價差 40% 以上）
TOP_N = 30                  # 排行只顯示前 30 名（使用者 2026-10-29）
RECORD_MIN_MONTHS = 12      # 歷史少於這麼多個月不判斷創新高


def _na(v) -> bool:
    """缺值判斷：None 或 NaN → True（涵蓋 numpy 浮點）。"""
    if v is None:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def periods_to_show(today: pd.Timestamp) -> list[pd.Period]:
    """要顯示的兩期營收月份，新的在前：[上個月, 上上個月]。

    例：2026-10-29 → [2026-09, 2026-08]；2026-11-03 → [2026-10, 2026-09]。
    （11/3 時 2026-10 只公布了一部分，照樣列，UI 標「公布中」。）
    """
    m = pd.Period(pd.Timestamp(today), freq="M")
    return [m - 1, m - 2]


def ratio(num: float | None, den: float | None) -> float | None:
    """num / den − 1。任一缺值、den ≤ 0 → None。"""
    try:
        num = float(num)
        den = float(den)
    except (TypeError, ValueError):
        return None
    if _na(num) or _na(den) or den <= 0:
        return None
    return num / den - 1


def yoy_streak(hist: pd.DataFrame, month: pd.Period) -> int:
    """`hist`＝單一公司月營收 `[month(Timestamp 月初), revenue]`（bundle_data.revenue 格式，
    已含本月）。從 `month` 往回數「revenue > 去年同月 revenue」連續成立幾個月；
    `month` 本身不成立或缺資料 → 0；中間缺任一個月（本月或去年同月）就停。
    """
    if hist is None or hist.empty:
        return 0
    by_month: dict[pd.Period, float] = {}
    for ts, v in zip(hist["month"], hist["revenue"]):
        if _na(ts) or _na(v):
            continue
        by_month[pd.Period(pd.Timestamp(ts), freq="M")] = float(v)
    cur = month
    streak = 0
    while True:
        cur_rev = by_month.get(cur)
        if cur_rev is None:
            break
        prev_rev = by_month.get(cur - 12)
        if prev_rev is None or not (cur_rev > prev_rev):
            break
        streak += 1
        cur = cur - 1
    return streak


def record_high(hist: pd.DataFrame, month: pd.Period) -> bool:
    """`month` 的營收 ≥ 所有更早月份的最大值。更早的月份少於 RECORD_MIN_MONTHS → False。"""
    if hist is None or hist.empty:
        return False
    ts = month.to_timestamp()
    m = pd.to_datetime(hist["month"])
    earlier = hist[m < ts]["revenue"]
    if len(earlier) < RECORD_MIN_MONTHS:
        return False
    cur = hist[m == ts]["revenue"]
    if cur.empty or _na(cur.iloc[0]):
        return False
    return bool(float(cur.iloc[0]) >= float(earlier.max()))


def ma_status(px: pd.DataFrame) -> dict:
    """`px`＝`[date, close]` 依日期排序（還原價）。回
    `{"price", "ma20", "ma60", "above_ma20", "above_ma60", "price_date"}`；
    筆數不足 20／60 的那條均線為 None，對應 above_* 為 None。px 空 → 全 None。
    """
    out = {"price": None, "ma20": None, "ma60": None,
           "above_ma20": None, "above_ma60": None, "price_date": None}
    if px is None or px.empty:
        return out
    px = px.sort_values("date").reset_index(drop=True)
    last = px.iloc[-1]
    price = last["close"]
    out["price"] = None if _na(price) else float(price)
    out["price_date"] = pd.Timestamp(last["date"]).strftime("%Y-%m-%d")
    closes = pd.to_numeric(px["close"], errors="coerce")
    n = len(closes)
    if n >= 20:
        ma20 = float(closes.tail(20).mean())
        out["ma20"] = ma20
        if out["price"] is not None:
            out["above_ma20"] = out["price"] > ma20
    if n >= 60:
        ma60 = float(closes.tail(60).mean())
        out["ma60"] = ma60
        if out["price"] is not None:
            out["above_ma60"] = out["price"] > ma60
    return out


def valuation_fields(est: dict, price: float | None) -> dict:
    """把 `valuation.estimate()` 的回傳攤平成 Row 的估值欄位
    （est_ok, est_reason, run_eps, est_eps, band_low/mid/high, growth_price,
    upside_mid, upside_growth, at_valuation, cyclical, pe_wide, warns）。
    est["ok"] 為 False → est_ok False、est_reason 帶原因、其餘數字 None、warns []。
    `price` 用參數（不用 est["price"]）：build 端可能用比 bundle 更新的收盤價。
    """
    out = {"est_ok": True, "est_reason": None, "run_eps": None, "est_eps": None,
           "band_low": None, "band_mid": None, "band_high": None, "growth_price": None,
           "upside_mid": None, "upside_growth": None, "at_valuation": None,
           "cyclical": False, "pe_wide": False, "warns": []}
    if not est or not est.get("ok"):
        out["est_ok"] = False
        out["est_reason"] = (est or {}).get("reason")
        return out
    out["est_reason"] = est.get("reason")
    eps = est.get("eps") or {}
    out["run_eps"] = eps.get("run_ex")
    year = est.get("year") or {}
    out["est_eps"] = year.get("est")
    band = est.get("band")
    if band:
        out["band_low"] = band.get("low")
        out["band_mid"] = band.get("mid")
        out["band_high"] = band.get("high")
    out["growth_price"] = est.get("growth_price")
    mid = band.get("mid") if band else None
    out["upside_mid"] = ratio(mid, price)
    out["upside_growth"] = ratio(est.get("growth_price"), price)
    if mid is not None and price is not None:
        out["at_valuation"] = price >= mid
    cycle = est.get("cycle") or {}
    pct = cycle.get("pct")
    out["cyclical"] = (pct is not None and pct >= 0.8)
    out["pe_wide"] = bool((est.get("pe") or {}).get("wide"))
    out["warns"] = list(est.get("warns") or []) + list(est.get("infos") or [])
    return out


def make_row(base: dict, hist: pd.DataFrame, month: pd.Period, ma: dict,
             val: dict) -> dict:
    """組一列 Row。

    base：code, name, industry, market_cap, revenue, revenue_prev_month,
          revenue_last_year, revenue_cum, revenue_cum_last_year, note,
          first_seen_at（Timestamp 或 None）, revised
    hist：該公司月營收歷史（已含本月）；ma：ma_status()；val：valuation_fields()
    欄位順序照上表；first_seen_at 轉 "YYYY-MM-DD HH:MM" 字串。
    """
    fs = base.get("first_seen_at")
    fs = None if _na(fs) else pd.Timestamp(fs).strftime("%Y-%m-%d %H:%M")
    note = base.get("note")
    note = "" if _na(note) else str(note).strip()
    note = "" if note == "-" else note
    rly = base.get("revenue_last_year")
    row = {
        "code": base.get("code"),
        "name": base.get("name"),
        "industry": base.get("industry"),
        "market_cap": base.get("market_cap"),
        "revenue": base.get("revenue"),
        "revenue_prev_month": base.get("revenue_prev_month"),
        "revenue_last_year": rly,
        "mom": ratio(base.get("revenue"), base.get("revenue_prev_month")),
        "yoy": ratio(base.get("revenue"), rly),
        "cum_yoy": ratio(base.get("revenue_cum"), base.get("revenue_cum_last_year")),
        "note": note,
        "first_seen_at": fs,
        "revised": bool(base.get("revised", False)),
        "yoy_streak": yoy_streak(hist, month),
        "record_high": record_high(hist, month),
        "low_base": _na(rly) or rly < LOW_BASE_REV,
    }
    row.update({
        "price": ma.get("price"),
        "ma20": ma.get("ma20"),
        "ma60": ma.get("ma60"),
        "above_ma20": ma.get("above_ma20"),
        "above_ma60": ma.get("above_ma60"),
    })
    for k in ("est_ok", "est_reason", "run_eps", "est_eps", "band_low", "band_mid",
              "band_high", "growth_price", "upside_mid", "upside_growth",
              "at_valuation", "cyclical", "pe_wide", "warns"):
        row[k] = val.get(k)
    return row


def rank(rows: list[dict], key: str, n: int = TOP_N, *, exclude_low_base: bool = False,
         require: tuple[str, ...] = (), exclude: tuple[str, ...] = ()) -> list[dict]:
    """依 `key` 由大到小取前 n 名（UI 用；放這裡才測得到）。
    `key` 為 None 的列排除；exclude_low_base → 排除 low_base；`require` 裡的欄位
    必須為真（例：("est_ok",)）；`exclude` 裡的欄位必須為假（例：("cyclical", "pe_wide")）。
    同分以 market_cap 大者在前。
    """
    out = []
    for r in rows:
        v = r.get(key)
        if _na(v):
            continue
        if exclude_low_base and r.get("low_base"):
            continue
        if any(not r.get(f) for f in require):
            continue
        if any(r.get(f) for f in exclude):
            continue
        out.append(r)
    out.sort(key=lambda r: (-float(r.get(key)), -(float(r.get("market_cap") or 0))))
    return out[:n]


def hold_signal(row: dict) -> str | None:
    """④ 持有提示（朋友口徑：到估值先賣一些、跌破線再全賣）。回：
    - "跌破季線"：above_ma60 is False
    - "跌破月線"：above_ma20 is False（且沒跌破季線）
    - "已到估值"：at_valuation is True（且沒跌破任何線）
    - None：其他
    優先序就是上面的順序（跌破線比到估值嚴重）。
    """
    if row.get("above_ma60") is False:
        return "跌破季線"
    if row.get("above_ma20") is False:
        return "跌破月線"
    if row.get("at_valuation") is True:
        return "已到估值"
    return None
