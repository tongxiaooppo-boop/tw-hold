"""月營收「當晚公告」收集（MOPS 彙總頁，逐家累積）。

## 為什麼不能沿用 bundle 的月營收（OpenAPI）

OpenAPI `t187ap05_L`／`mopsfin_t187ap05_O` 是**整期一次換**：2026-10 實測
10/01～10/10 一直是 8 月、10/13 才整批跳成 9 月。月初就公布的公司，在那條路上
也要等到 11～13 號才看得到，於是「公布當晚就估整季 EPS」做不到。

MOPS 的彙總頁 `/nas/t21/{sii,otc}/t21sc03_<民國年>_<月>.html`
在公布期開始前就存在（2026-10-29 實測 10 月那頁 200、「查無資料」），
⚠️ **推定**它隨公司申報逐家長出來——這一點 2026-11 第一個公布期才驗得到，
驗證方式就是 `runs.csv` 的逐次列數有沒有逐日成長。

## point-in-time 定義

| 欄位 | 定義 |
| :--- | :--- |
| `first_seen_at` | 這筆 (ticker, period) **第一次出現在我們抓取結果**的台北時間 |
| `last_seen_at` | 最近一次看到的時間 |
| `revised` | 第一次看到之後數字有沒有被改過（更正）；數字一律保留**第一次看到的** |

`first_seen_at` 比實際公告晚「排程間隔＋GitHub 排程延遲」，是保守值，不會偷看未來。

## 頁面網址用無尾碼那一種

`_0` 只有國內、`_1` 只有外國（KY）；無尾碼那頁兩者都有（2026-10-29 實測 9 月上市
1090 家、其中 KY 92 家，與 OpenAPI 1088 家相符）。一個市場打一發就好——
MOPS 短時間連打會直接斷線（同日實測約十幾發後 curl 也拿到空回應）。
編碼有 cp950／big5 兩種，解析時都試。
"""

from __future__ import annotations

import html as _html
import re

import pandas as pd

from pathlib import Path

MOPS_DIR = Path(__file__).resolve().parents[1] / "data" / "revenue_mops"
RUNS_LOG = MOPS_DIR / "runs.csv"

BASE = "https://mopsov.twse.com.tw/nas/t21"
MARKETS = {"TWSE": "sii", "TPEX": "otc"}

# 公布期：10 號截止，遇假日順延，留到 14 號（與 revenue_watch.yml 的 cron 日期一致）
WINDOW_LAST_DAY = 14

# 千元 → 元，與 bundle revenue.parquet 同單位
UNIT_MULTIPLIER = 1_000

VALUE_COLS = ["revenue", "revenue_prev_month", "revenue_last_year",
              "revenue_cum", "revenue_cum_last_year"]
COLUMNS = ["ticker", "code", "name", "market", "period", *VALUE_COLS, "note",
           "first_seen_at", "last_seen_at", "revised"]

_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def page_url(market: str, period: pd.Period) -> str:
    roc = period.year - 1911
    return f"{BASE}/{MARKETS[market]}/t21sc03_{roc}_{period.month}.html"


def target_period(today: pd.Timestamp) -> pd.Period:
    """公布期在當月 1～10 號（含晚報），要抓的是**上個月**的營收。"""
    return pd.Period(today, freq="M") - 1


def decode(raw: bytes) -> str:
    for enc in ("cp950", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp950", "replace")


def _num(text: str) -> float | None:
    s = text.strip().replace(",", "")
    if not s or s in {"-", "--", "N/A"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_page(text: str, market: str, period: pd.Period) -> pd.DataFrame:
    """彙總頁 HTML → 每家一列（不含 first/last_seen）。純函式。

    資料列的形狀：代號、名稱、當月、上月、去年當月、上月比較%、去年同月%、
    當月累計、去年累計、前期比較%、備註，共 11 格。產業小計列的第一格不是代號，丟掉。
    頁面自述的期別對不上就整頁不收（拿錯期的數字會製造假的公告時間）。
    """
    title = f"{period.year - 1911}年{period.month}月份"
    if title not in text:
        return pd.DataFrame(columns=COLUMNS[:-3])
    out = []
    for tr in _TR.findall(text):
        cells = [_html.unescape(_TAG.sub("", c)).replace("\xa0", " ").strip()
                 for c in _TD.findall(tr)]
        if len(cells) < 10 or not re.fullmatch(r"\d{4,6}[A-Z]?", cells[0]):
            continue
        vals = [_num(cells[i]) for i in (2, 3, 4, 7, 8)]
        if vals[0] is None:
            continue
        code = cells[0]
        out.append({
            "ticker": f"{code}{'.TW' if market == 'TWSE' else '.TWO'}",
            "code": code,
            "name": cells[1],
            "market": market,
            "period": str(period),
            **{k: None if v is None else v * UNIT_MULTIPLIER
               for k, v in zip(VALUE_COLS, vals)},
            "note": cells[10] if len(cells) > 10 else "",
        })
    if not out:
        return pd.DataFrame(columns=COLUMNS[:-3])
    return pd.DataFrame(out).drop_duplicates("ticker")


def merge_seen(existing: pd.DataFrame | None, snapshot: pd.DataFrame,
               seen_at: pd.Timestamp) -> pd.DataFrame:
    """把這次抓到的併進該期累積表。純函式。

    - 新出現的 ticker：first_seen_at = last_seen_at = seen_at
    - 已有的：只更新 last_seen_at；數字跟第一次不同就 revised=True（數字不覆蓋）
    - 這次沒出現的（抓取失敗或頁面暫時少列）：原樣保留，不刪
    """
    if snapshot.empty and existing is not None:
        return existing
    snap = snapshot.copy()
    snap["first_seen_at"] = seen_at
    snap["last_seen_at"] = seen_at
    snap["revised"] = False
    snap = snap.reindex(columns=COLUMNS)
    if existing is None or existing.empty:
        return snap.sort_values("ticker").reset_index(drop=True)

    old = existing.set_index("ticker")
    new = snap.set_index("ticker")
    both = old.index.intersection(new.index)
    if len(both):
        a = old.loc[both, VALUE_COLS].astype(float)
        b = new.loc[both, VALUE_COLS].astype(float)
        changed = ~((a == b) | (a.isna() & b.isna())).all(axis=1)
        old.loc[both, "last_seen_at"] = seen_at
        old.loc[both, "revised"] = old.loc[both, "revised"].astype(bool) | changed
    fresh = new.loc[new.index.difference(old.index)]
    merged = pd.concat([old, fresh]).reset_index()
    return merged.reindex(columns=COLUMNS).sort_values("ticker").reset_index(drop=True)


def period_path(period: pd.Period):
    return MOPS_DIR / f"{period}.parquet"


def load_period(period: pd.Period) -> pd.DataFrame | None:
    p = period_path(period)
    return pd.read_parquet(p) if p.exists() else None
