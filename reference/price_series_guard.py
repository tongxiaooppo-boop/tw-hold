"""收盤序列落地前的共用守門——「前一日的資料錯誤不可原諒，寧可暫時舊也不要覆蓋成錯的」。

`scripts/promote_index_0050.py`（0050，從 tw-swing bundle 搬）與
`scripts/fetch_index_proxy.py`（006201，向 FinMind 全量重抓）共用同一套，
2026-09-16 審核後抽出來——原本只有 0050 有驗證、006201 直接覆寫，那個不對稱
沒有正當理由：006201 的風險反而更高（0050 至少還過了 `fetch_bundle.py` 的 G1
sha256 + 欄位檢查，006201 是直接吃 FinMind 回來的 JSON）。

## 兩段式：先 sanitize，再 validate

**sanitize（清乾淨，不是拒絕）**：FinMind 實際會吐 `close = 0` 的列——
`index_006201.parquet` 裡 2016-08-24、2017-04-10 兩筆就是（2026-09-16 實測，
日報酬序列因此出現 `inf`）。這種列每次全量重抓都會再來一次，**若設計成「看到就
拒絕」，006201 會從此永遠拒絕、資料凍死**。所以先 drop 掉，再驗剩下的。

**validate（拒絕就保留舊檔）**：專防 sanitize 清不掉、而且上游 schema 檢查也看不出來的東西：

  1. 列數太少（餵不動 MA200）／**比舊檔大幅縮水**——最重要的一條。
     上游若寫出「只剩最近 30 列」的檔，欄位對、sha256 對、最後日期是今天、
     最後一筆漲跌正常，**舊版三道檢查全部放行**，覆寫後 `market_status.ma_verdict`
     因為 `len < 200` 靜默回 `None`，卡片變空白且 `freshness_check.py` 也抓不到
     （它只看最後一筆日期，而最後一筆是新的）。這是唯一「壞了沒人知道」的路徑。
  2. 最後日期倒退——上游回傳到一半斷線，用一份「有資料但是舊的」蓋掉新的。
  3. 最後一筆單日漲跌幅超標。門檻 12%：2015 年起 2847 筆 0050 日報酬實測，
     最大絕對值**恰好 10.0%**（台股 ±10% 漲跌停，ETF 同受限），99.9 分位 9.26%
     ——合法值進不了 10~12% 這個帶，不是憑感覺定的。
  4. **重疊區的日報酬不一致**——防「上游重新回填／改寫歷史」。
     比的是報酬不是價格：還原型序列（本檔兩支都是）每逢除息/分割會把事件日之前
     的價格整段乘上一個常數，**價格會全變、但日報酬只有事件日當天那一筆會變**。
     所以容許 1 天不一致（＝一次合法的還原基準變更），≥2 天視為歷史被竄改。
"""
from __future__ import annotations

import pandas as pd

MAX_DAY_MOVE = 0.12      # 台股 ±10% 漲跌停 + 緩衝；見檔頭實測數字
MIN_ROWS = 250           # MA200 要 200 筆，留緩衝
SHRINK_TOLERANCE = 5     # 允許的列數減少（上游偶爾修掉幾筆爛資料是正常的）
OVERLAP_DAYS = 60        # 重疊區只比最近這麼多天，更早的歷史差異不影響任何畫面
RETURN_EPS = 1e-6        # 日報酬視為相同的容差


def sanitize(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """留 `[date, close]`、丟掉不可能是真實收盤的列，依日期排序。

    不能用的（缺欄／空表）回 `None`；清完變空的也回 `None`。
    """
    if df is None or df.empty or "date" not in df.columns or "close" not in df.columns:
        return None
    d = df[["date", "close"]].copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    d = d[d["close"] > 0]                                  # 0／負／NaN 一起濾掉
    d = d.dropna(subset=["date"])
    d = (d.sort_values("date")
          .drop_duplicates("date", keep="last")            # 同一天兩筆：留後寫的
          .reset_index(drop=True))
    return d if not d.empty else None


def load_clean(path) -> pd.DataFrame | None:
    """讀 parquet → `sanitize`。檔案不存在／讀不起來回 `None`（不拋，呼叫端要能區分
    「沒有舊檔」跟「舊檔壞了」都走同一條路：照樣寫新的）。"""
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return None
    try:
        return sanitize(pd.read_parquet(p))
    except Exception:  # noqa: BLE001 — 壞檔等同沒有舊檔
        return None


def _return_mismatches(new: pd.DataFrame, old: pd.DataFrame) -> int:
    """重疊區最近 `OVERLAP_DAYS` 天裡，日報酬對不起來的天數。"""
    m = new.merge(old, on="date", suffixes=("_new", "_old")).tail(OVERLAP_DAYS + 1)
    if len(m) < 3:
        return 0                                           # 重疊太少，這條不表態
    r_new = m["close_new"].astype("float64").pct_change()
    r_old = m["close_old"].astype("float64").pct_change()
    return int(((r_new - r_old).abs() > RETURN_EPS).sum())


def validate(new: pd.DataFrame | None, old: pd.DataFrame | None) -> list[str]:
    """回「拒絕理由」清單，空 list = 通過。`new`／`old` 都要是 `sanitize` 過的。"""
    if new is None:
        return ["新資料是空的或缺 date/close 欄（或清掉異常列後就沒剩了）"]

    reasons: list[str] = []
    if len(new) < MIN_ROWS:
        reasons.append(f"只有 {len(new)} 筆，不足 {MIN_ROWS} 筆（MA200 會算不出來）")

    if old is not None and not old.empty:
        if len(new) < len(old) - SHRINK_TOLERANCE:
            reasons.append(f"筆數從 {len(old)} 縮到 {len(new)}，疑似上游只回了一段歷史")
        if new["date"].iloc[-1] < old["date"].iloc[-1]:
            reasons.append(f"最後日期 {new['date'].iloc[-1].date()} 比目前已發佈的 "
                           f"{old['date'].iloc[-1].date()} 還舊")
        bad = _return_mismatches(new, old)
        if bad > 1:
            reasons.append(f"重疊區最近 {OVERLAP_DAYS} 天有 {bad} 天的日報酬跟舊檔對不起來，"
                           "疑似歷史被回填／改寫（合法的還原基準變更只會動到 1 天）")

    if len(new) >= 2:
        prev, last = new["close"].iloc[-2], new["close"].iloc[-1]
        move = last / prev - 1.0
        if abs(move) > MAX_DAY_MOVE:
            reasons.append(f"最後一筆漲跌幅 {move:+.1%} 超過門檻 ±{MAX_DAY_MOVE:.0%}，疑似資料損毀")

    return reasons
