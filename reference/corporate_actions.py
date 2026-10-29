"""股數變動事件（分割 / 面額變更 / 減資 / 無償配股）的每股數字還原對照表。

## 為什麼要這張表

財報的每股 EPS、股利表的每股股利都是「當時的股數」；股數一變（分割、面額變更、減資彌補
虧損、盈餘／公積轉增資配股），事件日之前的每股數字就跟現在的股價不是同一把尺：
6669 緯穎 2026-09-02 配股 ×2.98，試算 EPS 變成市場預估的 3～4 倍（2026-10-29 使用者抓到）。
交易所的本益比在配股後也會沿用舊股數一段時間（見 `fix_exchange_ratios`）；只修 PER，PBR、殖利率定義未驗證、暫不修。

## 來源（2026-10-30 起）

1. **`_RESOLVED`（自動）**：`scripts/resolve_splits.py` 每次 rebuild 從自建事件表
   `corp_actions.parquet`（官方除權息／減資／面額變更 + FinMind 分割）產生，寫進
   `corporate_actions_resolved.json`（版控，app 端也讀它）。
2. **`_MANUAL`（手動覆寫）**：自動解錯時手動釘死。衝突時**手動贏**（整檔覆蓋）。

`IGNORE_JUMPS`：價格跳空偵測器掃到、判定是資料雜訊 → 列這裡讓偵測器閉嘴。

## 慣例

每個事件 `{date, type, m, pf}`：
  - `m`  ＝ 新股數 ÷ 舊股數（每股數字用）。分割 1→N：N；減資：< 1；配股 100‰：1.1。
    **現金減資 `m=None`**（IAS 33.29 不追溯調整，財報 EPS 也不會重編）。
  - `pf` ＝ 事件前收盤 ÷ 參考價（價格用；只有分割／面額變更／減資有，配股沒有——
    上游 data_pack 與自建包都已還原除權息）。
  - 舊格式 `{date, factor}`（`_MANUAL`、測試）＝ m 與 pf 都用 factor。
事件日**當天（含）之後**為新基準。各類每股數字的分界不同：
  - 價格：`adjust_prices`，事件日之前 ÷ pf，而且先檢查價格本身是否已還原；
  - 季 EPS：`adjust_eps`，看財報**公布時**股數換了沒（不是看季末）；
  - 股利：`adjust_dividends`，除息日 ≤ 事件日 → ÷ m（同日除權息的現金是舊股數發的）。
同一檔多次事件 → 依序累乘。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

_RESOLVED_PATH = Path(__file__).with_name("corporate_actions_resolved.json")

#: 手動覆寫層（自動解錯時用）。衝突時整檔蓋掉 _RESOLVED。
#: 2026-10-30 起自動來源改吃自建事件表，原本的 5904／6949／2321／8277／6669 都已自動涵蓋
#: （而且用官方事件日；2321、8277 舊手動條目方向是反的——減資股數變少 m 應 <1，卻寫 1.94）。
_MANUAL: dict[str, list[dict]] = {}

#: 價格還原只收 |ln pf| ≥ ln 1.5 的事件：小事件的跳空落在漲跌停 ±10% 以內，
#: `_jump_date` 分不出「已還原」還是「沒還原」，會誤除或狂發警告。
PRICE_MIN_RATIO = 1.5
#: 交易所沿用舊股數的修正（`fix_exchange_ratios`）只對配股類事件
EXCHANGE_LAG_TYPES = ("ex_rights", "ex_both")


def _load_resolved() -> dict[str, list[dict]]:
    if not _RESOLVED_PATH.exists():
        return {}
    try:
        raw = json.loads(_RESOLVED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if "events" in raw:                       # v2：resolve_splits.py 從 corp_actions 產
        return {str(tk): [dict(e) for e in evs] for tk, evs in raw["events"].items() if evs}
    return {str(tk): [{"date": e["date"], "factor": float(e["factor"])} for e in evs]
            for tk, evs in raw.get("splits", {}).items() if evs}


def _merge() -> dict[str, list[dict]]:
    out = _load_resolved()
    out.update(_MANUAL)            # 手動贏
    return out


#: {ticker(裸): [{"date": "YYYY-MM-DD", "factor": float}, ...]}
SPLITS: dict[str, list[dict]] = _merge()

#: 偵測器掃到、FinMind 查無事件、判定資料雜訊 → 不再每次 build 報。
IGNORE_JUMPS: dict[str, str] = {
    "2380": "2026-06-05 ×3.46（漲）——FinMind SplitPrice/CapitalReduction 皆無事件，資料雜訊",
    "4950": "2025-11-03 ×2.62（漲）——FinMind 兩張表皆無事件，資料雜訊",
    "5314": "2026-08-06 ×0.25——世紀 1 拆 20 是 2025-03-31（data_pack 已還原）；"
            "FinMind 對這筆 2026 跳空無事件，資料雜訊",
    "7772": "2026-04-20 ×1.85（漲）——FinMind 兩張表皆無事件，資料雜訊",
}


def reload() -> None:
    """重讀 `corporate_actions_resolved.json`（`resolve_splits.py --write` 後、同進程內生效）。"""
    global SPLITS
    SPLITS = _merge()


def _m(e: dict):
    return e.get("m") if ("m" in e or "type" in e) else e.get("factor")


def _pf(e: dict):
    return e.get("pf") if ("pf" in e or "type" in e) else e.get("factor")


def _events(ticker: str, types: tuple[str, ...] | None = None,
            upto: pd.Timestamp | None = None) -> list[tuple[pd.Timestamp, float]]:
    """每股數字用的事件 `[(日期, m)]`（現金減資等 m=None 的不列）。

    types 給了 → 只留 e.get("type") in types 的事件（沒有 type 的舊格式事件一律排除）；
    upto 給了 → 只留事件日 <= upto 的事件。其他行為不變。
    """
    out = []
    for e in SPLITS.get(str(ticker).split(".")[0], []):
        if types is not None and e.get("type") not in types:
            continue
        m = _m(e)
        if m is not None and m > 0 and abs(np.log(float(m))) > 1e-9:
            ts = pd.Timestamp(e["date"])
            if upto is not None and ts > upto:
                continue
            out.append((ts, float(m)))
    return out


def _price_events(ticker: str) -> list[tuple[pd.Timestamp, float]]:
    """價格用的事件 `[(日期, pf)]`：舊格式全收；新格式只收 |ln pf| ≥ ln PRICE_MIN_RATIO。"""
    out = []
    for e in SPLITS.get(str(ticker).split(".")[0], []):
        f = _pf(e)
        if f is None or not (f > 0):
            continue
        if "type" in e and abs(np.log(float(f))) < np.log(PRICE_MIN_RATIO):
            continue
        out.append((pd.Timestamp(e["date"]), float(f)))
    return out


def price_split_tickers() -> set[str]:
    """有價格事件的代號（偵測器 `scan_price_jumps`／`check_adjusted_jumps` 用）。"""
    return {t for t in SPLITS if _price_events(t)}


def adjust_per_share(df: pd.DataFrame, cols, date_col: str = "date",
                     ticker_col: str = "ticker", inclusive: bool = False) -> pd.DataFrame:
    """把 `cols`（每股數字）在各自事件日之前（`inclusive` 時含當天）的列 ÷ m，搬到最新股本基準。

    非破壞性：回傳 copy。`df` 缺欄或沒有已知事件 → 原樣返回。
    """
    return _divide_before(df, cols, date_col, ticker_col, _events, inclusive)


def _divide_before(df, cols, date_col, ticker_col, events_fn, inclusive: bool = False):
    if df is None or df.empty or ticker_col not in df.columns \
            or date_col not in df.columns:
        return df
    have = [c for c in cols if c in df.columns]
    if not have or not any(str(t).split(".")[0] in SPLITS
                           for t in df[ticker_col].unique()):
        return df
    d = df.copy()
    dates = pd.to_datetime(d[date_col])
    tk = d[ticker_col].astype(str).str.split(".").str[0]
    for t in tk.unique():
        evs = events_fn(t)
        if not evs:
            continue
        for ex_date, factor in evs:
            mask = (tk == t) & ((dates <= ex_date) if inclusive else (dates < ex_date))
            if mask.any():
                d.loc[mask, have] = d.loc[mask, have] / factor
    return d


#: `adjust_prices` 遇到「判不準」時留下的警告字串（程序內累積，build_lists 會讀出來寫進
#: `_meta.split_warning`）。判不準時寧可不除也不靜默：不除只是留一道看得見的斷崖。
PRICE_WARNINGS: list[str] = []

_SEARCH_ROWS = 5      # 在登記日前後各找幾根 K 棒的最大跳空（登記日可能偏一兩天，例 6949）
_TOL = 0.3            # |ln(r*/目標)| < _TOL × |ln f| 才算「對得上」


def adjust_prices(df: pd.DataFrame, cols, date_col: str = "date",
                  ticker_col: str = "ticker", probe_col: str = "close") -> pd.DataFrame:
    """價格欄版的 `adjust_per_share`：事件日之前 ÷ factor，**但先看價格本身有沒有還原**。

    為什麼：`_MANUAL`／`corporate_actions_resolved.json` 是為「上游 data_pack 沒還原」寫的；
    2026-10-13 起 tw-swing 吃自建包（日線已還原分割／面額變更／減資），再除一次會變成
    人造 2～20 倍斷崖（5904、6949、0052、4747、2321、8277），而 `scan_price_jumps()` 因為
    這些代號已列在 SPLITS 而略過，不報警。

    判法（每個事件，在登記日前後各 `_SEARCH_ROWS` 根 K 棒內找單日最大的跳空比值 r* = 前收/後收）：
      - r* 離 1 近（|ln r*| < 0.3|ln f|）→ 價格連續，資料源已還原 → 跳過；
      - r* 離 f 近（|ln(r*/f)| < 0.3|ln f|）→ 沒還原 → 以「實際跳空那天」為界 ÷ f
        （登記日偏一兩天也修得到）；
      - 其他（含方向相反 r*≈1/f、找不到事件日之後的資料）→ **不除**並寫 `PRICE_WARNINGS`，
        絕不靜默。收盤價 ≤ 0 的列不參與判斷。
    每股 EPS／股利沒有任何資料源還原過，仍用 `adjust_per_share`——只有價格走這支。
    缺 `probe_col` 時不檢查連續性、直接以登記日為界 ÷ pf（舊行為，只用價格事件）。
    """
    if df is None or df.empty or ticker_col not in df.columns             or date_col not in df.columns:
        return df
    if probe_col not in df.columns:
        return _divide_before(df, cols, date_col, ticker_col, _price_events)
    have = [c for c in cols if c in df.columns]
    if not have or not any(str(t).split(".")[0] in SPLITS
                           for t in df[ticker_col].unique()):
        return df
    d = df.copy()
    dates = pd.to_datetime(d[date_col]).to_numpy()
    tk = d[ticker_col].astype(str).str.split(".").str[0].to_numpy()
    probe = pd.to_numeric(d[probe_col], errors="coerce").to_numpy(dtype=float)
    # 一次分組：全市場日線數百萬列，逐檔 `tk == t` 會讓 rebuild 慢十分鐘（2026-10-30 實測）
    groups = pd.Series(np.arange(len(d)), index=tk).groupby(level=0).indices
    cis = [d.columns.get_loc(c) for c in have]
    for t, pos in groups.items():
        evs = _price_events(t)
        if not evs:
            continue
        sub = pd.DataFrame({"date": dates[pos], "px": probe[pos]})
        sub = sub[sub["px"] > 0].sort_values("date").reset_index(drop=True)
        for ex_date, factor in evs:
            cut = _jump_date(sub, ex_date, factor, t)
            if cut is None:
                continue
            rows = pos[dates[pos] < np.datetime64(cut)]
            if len(rows):
                for ci in cis:
                    d.iloc[rows, ci] = d.iloc[rows, ci].to_numpy(dtype=float) / factor
    return d


def _jump_date(sub: pd.DataFrame, ex_date: pd.Timestamp, factor: float, ticker: str):
    """回傳要 ÷ factor 的分界日（該日之前除）；None 表示不除（已還原或判不準，後者會留警告）。"""
    if not (factor > 0) or abs(np.log(factor)) < 1e-9:
        return None
    pos = int(sub["date"].searchsorted(ex_date))        # 第一根 >= 登記日
    if pos == 0:
        return None                                     # 事件早於資料起點：沒東西要除
    if pos >= len(sub):
        PRICE_WARNINGS.append(f"{ticker} {ex_date.date()} ×{factor:g}：登記日前後缺資料，未還原價格")
        return None
    lo, hi = max(1, pos - _SEARCH_ROWS), min(len(sub) - 1, pos + _SEARCH_ROWS)
    px = sub["px"].to_numpy()
    rs = {i: px[i - 1] / px[i] for i in range(lo, hi + 1)}
    j = max(rs, key=lambda i: abs(np.log(rs[i])))
    r = float(rs[j])
    scale = abs(np.log(factor))
    if abs(np.log(r)) < _TOL * scale:
        return None                                     # 連續 → 已還原
    if abs(np.log(r / factor)) < _TOL * scale:
        return sub["date"].iloc[j]                      # 沒還原 → 以實際跳空日為界
    PRICE_WARNINGS.append(
        f"{ticker} {ex_date.date()} ×{factor:g}：前後跳空 ×{r:.3f} 與登記 factor 對不上"
        f"（方向相反或日期偏離過大），未還原價格")
    return None


# ── 季 EPS：看「財報公布時」股數換了沒 ──────────────────────────────────────

#: 各季財報法定公布期限（月, 日）；Q4 是隔年。只拿來圈出「季末 < 事件日 ≤ 期限」的模糊季。
_DEADLINE = {3: (5, 15), 6: (8, 14), 9: (11, 14), 12: (3, 31)}
#: 金融業期限較晚、公司也可能延後公布 → 模糊窗口多放寬幾天，讓更多季走隱含股數判斷
_DEADLINE_SLACK = pd.Timedelta(days=21)


def report_deadline(period_end) -> pd.Timestamp:
    pe = pd.Timestamp(period_end)
    mo, dd = _DEADLINE.get(pe.month, (pe.month, 28))
    return pd.Timestamp(pe.year + (1 if pe.month == 12 else 0), mo, dd)


def _basis_switched_at(sh: np.ndarray, i: int, m: float):
    """第 i 季（模糊季）的隱含股數是新基準嗎？True/False；判不了 → None。
    比「跟上一季比 ≈m、跟下一季比 ≈1」vs「跟上一季 ≈1、跟下一季 ≈m」哪個比較像。"""
    lm = np.log(m)

    def lr(a, b):
        ok = np.isfinite(a) and np.isfinite(b) and a > 0 and b > 0
        return float(np.log(a / b)) if ok else None
    rp = lr(sh[i], sh[i - 1]) if i >= 1 else None
    rn = lr(sh[i + 1], sh[i]) if i + 1 < len(sh) else None
    if rp is None and rn is None:
        return None
    new = (abs(rp - lm) if rp is not None else 0) + (abs(rn) if rn is not None else 0)
    old = (abs(rp) if rp is not None else 0) + (abs(rn - lm) if rn is not None else 0)
    return bool(new < old)


#: 找「換基準那一季」的窗口：分界後第一季的季末落在 [事件日−N 個月, 事件日+4 個月]。
#: 減資、面額變更的財報換股數常比 corp_actions 的日期（恢復買賣日）早 1～2 季
#: （2208 2018-07-30 減資，Q1 2018 隱含股數已從 743M 掉到 313M；2026-10-30 全市場驗證）→ 9 個月。
#: 配股要等股東會（約 6 月）通過，最早只能是事件前最後一季 → 4 個月；放寬會抓到同期的
#: 現增／轉換（6596 2018 配股，1803 季股本 +10% 是現增，真正配股在 1809 季）。
_OBS_BEFORE = pd.DateOffset(months=9)
_OBS_BEFORE_BONUS = pd.DateOffset(months=4)
_OBS_AFTER = pd.DateOffset(months=4)
_OBS_TOL = 0.2            # |ln(跳動) − ln m| < 0.2·|ln m| 才算看到
_OBS_MIN_M = 1.05         # 小於 5% 的股數變化跟一般股數雜訊分不開 → 只用日期規則
_OBS_MIN_EPS = 0.05       # EPS 太小，隱含股數不可靠


def _observed_boundary(pe: pd.Series, eps: np.ndarray, sh: np.ndarray, ts, m,
                       typ: str | None = None):
    """資料裡看得到的換基準分界：回傳 b（b 之前的季是舊股數）；看不到 → None。
    在窗口內每一對相鄰季算隱含股數跳動，取最接近 m 的那對（容差 `_OBS_TOL`），
    而且下一季要維持在新水位（濾掉 Q4＝全年−前三季算出來的單季離群值）。"""
    lm = np.log(m)
    if abs(lm) < np.log(_OBS_MIN_M):
        return None
    before = _OBS_BEFORE_BONUS if typ in ("ex_rights", "ex_both") else _OBS_BEFORE
    lo, hi = pd.Timestamp(ts) - before, pd.Timestamp(ts) + _OBS_AFTER
    best, best_err = None, _OBS_TOL * abs(lm)
    pev = pe.to_numpy()
    for b in range(1, len(pev)):
        if not (lo <= pev[b] <= hi):
            continue
        a0, a1, e0, e1 = sh[b - 1], sh[b], eps[b - 1], eps[b]
        if not (np.isfinite(a0) and np.isfinite(a1) and a0 > 0 and a1 > 0):
            continue
        if e0 * e1 <= 0 or min(abs(e0), abs(e1)) < _OBS_MIN_EPS:
            continue
        err = abs(np.log(a1 / a0) - lm)
        if err >= best_err:
            continue
        if b + 1 < len(pev):
            a2, e2 = sh[b + 1], eps[b + 1]
            if np.isfinite(a2) and a2 > 0 and e2 * e1 > 0 and abs(e2) >= _OBS_MIN_EPS                     and abs(np.log(a2 / a1)) > 0.5 * abs(lm):
                continue                       # 下一季又跳走 → 單季離群，不是換基準
        best, best_err = b, err
    return best


def adjust_eps(q: pd.DataFrame, col: str = "eps", ticker_col: str = "ticker",
               period_col: str = "period_end",
               types: tuple[str, ...] | None = None,
               upto: pd.Timestamp | None = None) -> pd.DataFrame:
    """季 EPS 搬到最新股本基準。財報 EPS 用的是**公布當時**的股數（IAS 33.64：期後、
    公布前的配股／分割會追溯重編）。分界優先**看資料**：`_observed_boundary` 在事件前
    9 個月～後 4 個月內找隱含股數（歸母淨利 ÷ EPS）跳動 ≈ m 的相鄰兩季；看不到才用日期規則：
      - 公布期限（＋寬限）< 事件日 → 舊基準 → ÷ m；
      - 季末 ≥ 事件日 → 新基準 → 不動；
      - 中間（季末 < 事件日 ≤ 期限＋寬限）：公司早公布就是舊、晚公布就是新（實測
        2015～2026 上市配股 ≥10%：新 67／舊 26）→ 用隱含股數（歸母淨利 ÷ EPS，沒有
        就用淨利）跟前後季比；判不了當新基準（多數情況）。
    非破壞性；沒有事件 → 原樣返回。
    """
    if q is None or q.empty or col not in q.columns or ticker_col not in q.columns \
            or period_col not in q.columns:
        return q
    tks = q[ticker_col].astype(str).str.split(".").str[0]
    hit = [t for t in tks.unique() if _events(t)]
    if not hit:
        return q
    d = q.copy()
    pe_all = pd.to_datetime(d[period_col])
    # 隱含股數用損益表的歸母淨利 `ni_parent`（逐列缺值退用 net_income）。**不能用
    # `equity_parent`**：它在 load_quarterly（三清單）是資產負債表的業主權益、在
    # bundle_data.financials（個股頁）是歸母淨利，同名不同義（2026-10-29 抓到）。
    ni_cols = [c for c in ("ni_parent", "net_income") if c in d.columns]
    for t in hit:
        idx = d.index[(tks == t).to_numpy()]
        order = pe_all.loc[idx].sort_values().index
        pe = pe_all.loc[order]
        eps0 = pd.to_numeric(d.loc[order, col], errors="coerce").to_numpy(dtype=float)
        ni = np.full(len(order), np.nan)
        for c in reversed(ni_cols):
            v = pd.to_numeric(d.loc[order, c], errors="coerce").to_numpy(dtype=float)
            ni = np.where(np.isfinite(v), v, ni)
        with np.errstate(divide="ignore", invalid="ignore"):
            sh = ni / eps0
        div = np.ones(len(order))
        ev_types = {pd.Timestamp(e["date"]): e.get("type") for e in SPLITS.get(t, [])}
        for ts, m in _events(t, types=types, upto=upto):
            b = _observed_boundary(pe, eps0, sh, ts, m, ev_types.get(ts))
            if b is not None:                      # 資料看得到換基準那一季 → 以它為準
                div[:b] *= m
                continue
            for i, p in enumerate(pe):
                if p >= ts:
                    continue
                dl = report_deadline(p)
                if dl + _DEADLINE_SLACK < ts:
                    div[i] *= m
                    continue
                sw = _basis_switched_at(sh, i, m)
                # 判不了：事件在法定期限內 → 多半已用新股數公布；過了期限（寬限區）→ 舊
                if sw is False or (sw is None and ts > dl):
                    div[i] *= m
        d.loc[order, col] = eps0 / div
    return d


# ── 股利 ─────────────────────────────────────────────────────────────────

def adjust_dividends(div: pd.DataFrame, cols, ticker_col: str = "ticker",
                     date_cols=("ex_date", "CashExDividendTradingDate", "pay_date")) -> pd.DataFrame:
    """每股股利搬到最新股本基準：除息日 ≤ 事件日 → ÷ m（同日除權息的現金是舊股數領的）。
    除息日缺就依序退用其他日期欄。FinMind 股利表是「當時每股」（2026-10-30 對 8974 筆官方
    息值：94% 完全相同，其餘是資本公積現金沒併進來，沒有追溯調整過的）。"""
    if div is None or div.empty:
        return div
    have = [c for c in date_cols if c in div.columns]
    if not have:
        return div
    d = div.copy()
    eff = pd.to_datetime(d[have[0]], errors="coerce")
    for c in have[1:]:
        eff = eff.fillna(pd.to_datetime(d[c], errors="coerce"))
    d["_eff_date"] = eff
    d = adjust_per_share(d, cols, date_col="_eff_date", ticker_col=ticker_col, inclusive=True)
    return d.drop(columns="_eff_date")


# ── 交易所本益比／淨值比／殖利率 ─────────────────────────────────────────


def _restating_quarter(ts: pd.Timestamp) -> pd.Timestamp:
    """涵蓋事件日的那一季季末（事件日 ≤ 季末）；這份財報才會把舊季重編成新股數。"""
    return (ts.normalize() + pd.offsets.QuarterEnd(0)).normalize()


#: 交易所反推 EPS（收盤÷PER）變動多少以上算「換了一份財報」（切段用）
_STALE_TOL = 0.01


def fix_exchange_ratios(per: pd.DataFrame, quarterly: pd.DataFrame | None = None,
                        raw_close: pd.DataFrame | None = None) -> pd.DataFrame:
    """交易所每日 PER 修回當天股本基準（只修 `per` 欄；pbr、dividend_yield 原樣）。

    實證（2026-10-30，67 件配股逐日拆）：配股（ex_rights／ex_both）除權日當天交易所 PER 仍用
    舊股數的四季 EPS（反推 EPS 前後一日比值中位數 1.000）；之後**某一份財報公布時**舊季全部
    重編成新股數，之後不必修。哪一份不固定：7 月配股有的 8 月 Q2 財報就重編，6 月底／9 月配股
    有的拖到下一季甚至年報（推測跟新股交付日有關）。面額變更／分割交易所當天就調好，不修。
    （10/29 的「舊季不重編、四季才滾完」是驗證腳本拿今天股數當基準造成的誤判。）

    修法（逐段看資料）：令 Q＝涵蓋事件日 E 的季末，窗口＝E ～ Q 下一季的法定期限。
    窗口內交易所反推 EPS（未還原收盤÷PER）在兩份財報之間是常數 → 依變動 ≥1% 切段；每段跟
    「新股數四季加總 S」（`adjust_eps(upto=E)`，最近四季或提早公布多一季取最吻合）比：
    比 m×S 近 → 舊股數 → PER × m；比 S 近 → 已重編，該段起之後都不修。
    判不了（沒收盤、沒季 EPS、S ≤ 0）的段：季末 Q 的法定期限之前當舊、之後當已重編。
    同檔多次事件依序套用，窗口重疊時倍數相乘。

    per：[ticker, date, per, ...]；quarterly：[ticker, period_end, eps, ni_parent?, net_income?]
    （原始季 EPS，給 `adjust_eps` 用）；raw_close：[ticker, date, close]（未還原收盤）。
    quarterly／raw_close 沒給 → 全部走「判不了」規則。非破壞性。
    """
    if per is None or per.empty or not {"ticker", "date", "per"} <= set(per.columns):
        return per

    tks = per["ticker"].astype(str).str.split(".").str[0]
    evmap = {}
    for t in tks.unique():
        evs = sorted((pd.Timestamp(e["date"]), float(_m(e))) for e in SPLITS.get(t, [])
                     if e.get("type") in EXCHANGE_LAG_TYPES and _m(e) is not None
                     and float(_m(e)) > 1.0)
        if evs:
            evmap[t] = evs
    if not evmap:
        return per

    d = per.copy()
    d["per"] = pd.to_numeric(d["per"], errors="coerce").astype(float)
    dates_all = pd.to_datetime(d["date"]).to_numpy()

    closes: dict[str, pd.Series] = {}
    if raw_close is not None and not raw_close.empty:
        rc = raw_close[["ticker", "date", "close"]].copy()
        rc["ticker"] = rc["ticker"].astype(str).str.split(".").str[0]
        rc = rc[rc["ticker"].isin(evmap)]
        rc["date"] = pd.to_datetime(rc["date"])
        for t, g in rc.groupby("ticker", sort=False):
            closes[t] = g.drop_duplicates("date").set_index("date")["close"]

    qmap: dict[str, pd.DataFrame] = {}
    if quarterly is not None and not quarterly.empty             and {"ticker", "period_end", "eps"} <= set(quarterly.columns):
        qtks = quarterly["ticker"].astype(str).str.split(".").str[0]
        sel = qtks.isin(evmap)
        qsel = quarterly[sel].assign(ticker=qtks[sel])
        qsel["period_end"] = pd.to_datetime(qsel["period_end"])
        qmap = {t: g.sort_values("period_end").reset_index(drop=True)
                for t, g in qsel.groupby("ticker", sort=False)}

    pos_of = pd.Series(np.arange(len(d)), index=tks.to_numpy()).groupby(level=0).indices
    ci = d.columns.get_loc("per")

    for t, evs in evmap.items():
        if t not in pos_of:
            continue
        pos = pos_of[t]
        pos = pos[np.argsort(dates_all[pos], kind="stable")]
        dts = dates_all[pos]
        per0 = d.iloc[pos, ci].to_numpy(dtype=float)
        mult = np.ones(len(pos))
        cs = closes.get(t)
        c = (cs.reindex(pd.DatetimeIndex(dts)).to_numpy(dtype=float) if cs is not None
             else np.full(len(pos), np.nan))
        with np.errstate(divide="ignore", invalid="ignore"):
            x = np.where(per0 > 0, c / per0, np.nan)      # 交易所反推 EPS
        qt = qmap.get(t)

        for E, m in evs:
            Q = _restating_quarter(E)
            dQ = report_deadline(Q)
            end = report_deadline((Q + pd.offsets.QuarterEnd(1)).normalize())
            win = np.flatnonzero((dts >= E.to_datetime64()) & (dts < end.to_datetime64()))
            if len(win) == 0:
                continue
            fallback = dts[win] < dQ.to_datetime64()
            stale = fallback.copy()
            xw = x[win]
            if qt is not None and np.isfinite(xw).any():
                eps = pd.to_numeric(adjust_eps(qt, upto=E)["eps"], errors="coerce").to_numpy(float)
                ttm = pd.Series(eps).rolling(4).sum().to_numpy()        # ttm[k]：第 k-3～k 季
                dl = np.array([report_deadline(p).to_datetime64() for p in qt["period_end"]])
                n = np.searchsorted(np.sort(dl), dts[win], side="left")  # 期限已過的季數
                # 切段：反推 EPS 變動 ≥1% 換段（缺值沿用上一段）
                xf = pd.Series(xw).ffill().to_numpy()
                lx = np.log(np.where(xf > 0, xf, np.nan))
                brk = np.r_[True, ~(np.abs(np.diff(lx)) < _STALE_TOL)]
                seg = np.cumsum(brk)
                lm = np.log(m)
                verdict = np.full(len(win), np.nan)                    # 1＝舊股數、0＝已重編
                for i in range(len(win)):
                    if not np.isfinite(lx[i]):
                        continue
                    cand = [ttm[k - 1] for k in (n[i], n[i] + 1) if 4 <= k <= len(ttm)]
                    cand = [v for v in cand if np.isfinite(v) and v > 0]
                    if not cand:
                        continue
                    e_new = min(abs(lx[i] - np.log(v)) for v in cand)
                    e_old = min(abs(lx[i] - np.log(v) - lm) for v in cand)
                    verdict[i] = 1.0 if e_old < e_new else 0.0
                sv = pd.Series(verdict).groupby(seg).transform("mean").to_numpy()
                known = np.isfinite(sv)
                stale = np.where(known, sv > 0.5, fallback)
            # 一旦判已重編，之後都不修
            stale &= np.cumsum(~stale) == 0
            mult[win[stale]] *= m

        d.iloc[pos, ci] = per0 * mult

    return d
