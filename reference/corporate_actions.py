"""股票分割 / 面額變更 / 減資的每股數字還原對照表。

## 為什麼要這張表

上游 `data_pack` 的還原引擎有還原**除權息**，但**沒處理面額變更 / 分割 / 減資**。
結果 bundle 的 `prices_adj` 在事件日會有一道 ~Nx 的斷崖，而財報的每股 EPS / 每股股利
在事件日之前仍是舊基準 → normalized_EPS 隱含 PE 被灌歪 → 價值清單 verdict 被
`eps_basis_suspect` 擋成「資料不足」；K 線 / 回測跨越事件日全錯（`me` 被 2327 國巨逼出
`price_adjuster.py` 就是這個）。

## 兩個來源

1. **`_RESOLVED`（自動）**：`scripts/resolve_splits.py` 每次 rebuild 跑——
   `build_factors.scan_price_jumps()` 掃到 bundle 跳空 → 抓 FinMind `TaiwanStockSplitPrice`
   / `TaiwanStockCapitalReductionReferencePrice`（免費）→ **FinMind 給 factor、偵測器給日期**
   → 寫進 `corporate_actions_resolved.json`（版控）。
2. **`_MANUAL`（手動覆寫）**：FinMind 也沒有、或自動解錯時，手動釘死。衝突時**手動贏**。

`IGNORE_JUMPS`：偵測器掃到、FinMind 查無事件、判定是資料雜訊 → 列這裡讓偵測器閉嘴。

## 慣例

`factor` = 新股數 ÷ 舊股數（= 事件前股價 ÷ 事件後股價）。
  - 分割 / 面額變更（1 股 → N 股）：factor = N（> 1）
  - 減資：factor < 1
事件日**當天（含）之後**為新基準；之前的每股數字（還原股價 OHLC、每股 EPS、每股股利）
一律 ÷ factor 搬到新基準。同一檔多次事件 → 依序累乘。

⚠️ **日期用 bundle `prices_adj` 實際跳空那天**（跑 `scan_price_jumps()` 拿），
   不是 FinMind 事件日、也不是 TWSE 官方新股上市日——三者常差幾天，用錯會把
   已經是新基準的那幾天再 ÷factor 一次。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

_RESOLVED_PATH = Path(__file__).with_name("corporate_actions_resolved.json")

#: 手動覆寫層（FinMind 沒有 / 自動解錯時用）。衝突時蓋掉 _RESOLVED。
_MANUAL: dict[str, list[dict]] = {
    # 5904 寶雅 面額 10→1。FinMind factor 10（720/72）；bundle 2026-07-20 收 611 → 07-21 收 63.3。
    "5904": [{"date": "2026-07-21", "factor": 10}],
    # 6949 沛爾生醫 面額 10→0.5（factor 20）。bundle 跳空 2026-09-07（資料尾端只一根新價，
    #   比例略偏 ×0.045）。bundle 累積完整後回頭校日期。
    "6949": [{"date": "2026-09-07", "factor": 20}],
    # 2321 東訊、8277 商丞：減資彌補虧損（非現金減資），FinMind 查無事件（2026-09-15
    # resolve_splits.py 連續多天解不了）。官方減資比例反推的 factor 跟 bundle 實際跳空
    # 比例對到小數點後 4 位（2321 官方 1÷0.54687826≈1.9369 vs bundle 27.794121/14.35≈
    # 1.936873；8277 官方 1÷0.431087≈2.3111 vs bundle 18.557737/8.03≈2.311051），
    # 用 bundle 實測值（跟其他事件一致）。停止買賣 09-10、換發新股 09-21 恢復交易。
    "2321": [{"date": "2026-09-02", "factor": 1.936873}],
    "8277": [{"date": "2026-09-02", "factor": 2.311051}],
}


def _load_resolved() -> dict[str, list[dict]]:
    if not _RESOLVED_PATH.exists():
        return {}
    try:
        raw = json.loads(_RESOLVED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
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


def _events(ticker: str) -> list[tuple[pd.Timestamp, float]]:
    return [(pd.Timestamp(e["date"]), float(e["factor"]))
            for e in SPLITS.get(str(ticker).split(".")[0], [])]


def adjust_per_share(df: pd.DataFrame, cols, date_col: str = "date",
                     ticker_col: str = "ticker") -> pd.DataFrame:
    """把 `cols`（每股數字）在各自事件日之前的列 ÷ factor，搬到最新股本基準。

    非破壞性：回傳 copy。`df` 缺欄或沒有已知事件 → 原樣返回。
    """
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
        evs = _events(t)
        if not evs:
            continue
        for ex_date, factor in evs:
            mask = (tk == t) & (dates < ex_date)
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
    缺 `probe_col` 時退回 `adjust_per_share` 的舊行為。
    """
    if df is None or df.empty or ticker_col not in df.columns             or date_col not in df.columns or probe_col not in df.columns:
        return adjust_per_share(df, cols, date_col, ticker_col)
    have = [c for c in cols if c in df.columns]
    if not have or not any(str(t).split(".")[0] in SPLITS
                           for t in df[ticker_col].unique()):
        return df
    d = df.copy()
    dates = pd.to_datetime(d[date_col])
    tk = d[ticker_col].astype(str).str.split(".").str[0]
    for t in tk.unique():
        evs = _events(t)
        if not evs:
            continue
        sel = tk == t
        sub = pd.DataFrame({"date": dates[sel],
                            "px": pd.to_numeric(d.loc[sel, probe_col], errors="coerce")})
        sub = sub[sub["px"] > 0].sort_values("date").reset_index(drop=True)
        for ex_date, factor in evs:
            cut = _jump_date(sub, ex_date, factor, t)
            if cut is None:
                continue
            mask = sel & (dates < cut)
            if mask.any():
                d.loc[mask, have] = d.loc[mask, have] / factor
    return d


def _jump_date(sub: pd.DataFrame, ex_date: pd.Timestamp, factor: float, ticker: str):
    """回傳要 ÷ factor 的分界日（該日之前除）；None 表示不除（已還原或判不準，後者會留警告）。"""
    if not (factor > 0) or abs(np.log(factor)) < 1e-9:
        return None
    pos = int(sub["date"].searchsorted(ex_date))        # 第一根 >= 登記日
    if pos >= len(sub) or pos == 0:
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
