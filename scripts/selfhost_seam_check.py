"""偵測上游還原價的「還原接縫」並產出可追溯清單（**只讀分析，不改任何現行資料**）。

## 原理
上游 `updater.py` 只重抓最近 7 天，除權息日（ex）之前超過約 8 天的歷史停在「尚未套用這次事件」的舊基準。
令 r(d) = 還原收盤(d) / 官方未還原收盤(d)。無接縫時 r 只在 ex 日跳一次（還原連續、未還原跳空）；
有接縫時 r 在 ex 前多一個階梯（階梯日 S），**S 之前的列水位偏高**。

## 對齊與去污染（Opus 審查 2026-10-05 後加）
- 比對只用「官方實價有的日期」：母表在休市日有 volume=0 的幽靈列（例：2026-07-10 颱風休市）、停牌期間也有，
  inner join 官方實價日曆即自動排除。
- 事件日 ex 先對到「官方實價日曆上 ≥ ex 的第一個交易日」（ex_eff），颱風／補班造成的官方日期與實際首個交易日不同時不會錯位。
- 階梯必須**持續**到 ex_eff 前一天（排除母表 r 被誤乘兩次造成的單日尖刺，例：2026-07-06 有 8 檔）。

## 狀態分類（status）
| status | 意義 |
| :-- | :-- |
| `seam` | 找到持續階梯，大小與官方因子差 ≤ TOL（0.3%） |
| `seam_factor_diff` | 找到持續階梯、同方向、大小是官方因子的 0.3～1.7 倍 ——上游（Yahoo）對權息／除權／現金增資事件的因子與官方不同；**自建以官方為準，不用此階梯訂正，只記錄偏差** |
| `seam_unverifiable` | 有大小相近的同向階梯，但落在 ex 前 1–2 個交易日、後面不夠日數驗證「持續」→ 不能判斷是否為接縫（≠已修好）；人工看 |
| `healed_or_none` | 窗口內沒有持續階梯：上游全量重抓後已修好，或事件早於全量重抓 |
| `too_small` | 事件因子影響 < 0.4%，無法偵測；仍由「由實價重算還原」涵蓋（`selfhost_adjust.py`），不靠偵測 |
| `no_data` | 母表或官方實價沒有該檔 |
| `no_raw_window` | 事件前 20 日曆日窗口內官方實價不足 8 天（全歷史回補尚未涵蓋）→ 不判斷 |
`multi=True`：該檔在 ±40 日曆日內另有事件（階梯可能混在一起，需人工看）。

## 殘留（無跡可循）清單
對 status=seam 且非 multi 的事件做訂正（S 之前乘官方因子）後，r 在**非 ex_eff 日**仍有 |step| > 0.4% 的日子，
寫入 `data/selfhost/seam_residual.csv`（ticker、date、step）——每個都該能歸到某個已知類別
（非除權息事件如減資／面額變更、停牌、母表壞資料）；歸不到的就是真的「無跡可循」，要人看。

## ⚠️ 舊年份（約 2015–2016）限制（Opus 複查）
上游早年歷史收盤價與官方對不起來（r 每天在 ±1% 內亂跳，例：1101 於 2016-09-14 上游換算 34.25 vs 官方 33.95），這是**系統性雜訊**，
不是單日壞資料——該段的殘留清單與 `seam_factor_diff` 沒有參考價值（`market_wide_same_day` 歸因在該段不準），
**以 data_pack 驗收還原引擎只能限定近年（例如最近 250 個交易日）**。2015–16 年另有約 3/2,280 件 `seam_factor_diff` 疑為假陽性（1477、3324、8421）。

## 輸入／輸出
- 還原日線：預設讀 tw-swing 母表（**僅本機分析用**，`--adj` 可指定 bundle 的 prices_adj.parquet）
- 官方實價：`data/selfhost/raw_prices.parquet`；事件：`data/selfhost/corp_actions.parquet`
- 輸出：`data/selfhost/seam_events.csv`、`data/selfhost/seam_residual.csv`

用法：
    python scripts/selfhost_seam_check.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import selfhost_adjust as sa  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "data" / "selfhost"
RAW = SH / "raw_prices.parquet"
EV = SH / "corp_actions.parquet"
SEAMS = SH / "seam_events.csv"
RESID = SH / "seam_residual.csv"
DEFAULT_ADJ = ROOT.parent / "tw-swing" / "data" / "store" / "daily_full.parquet"   # 僅本機分析用
MIN_DROP = 0.004          # 因子影響 <0.4% 的事件不偵測
TOL = 0.003               # seam：階梯與官方因子的容許差
RATIO_LO, RATIO_HI = 0.3, 1.7      # seam_factor_diff：階梯 / 官方階梯 的容許範圍
PERSIST_TOL = 0.002       # 階梯後 r 必須維持在階梯水位 ±0.2%
WINDOW_DAYS = 20          # 在 ex_eff 前幾個日曆日內找階梯
MULTI_DAYS = 40
MIN_PERSIST_DAYS = 3      # 階梯日起算（含）到 ex 前一天至少要有幾個官方實價日，才能驗證「持續」
MIN_WINDOW_DAYS = 8       # 事件前窗口內至少要有幾個官方實價日，才有資格判斷


def detect(r: pd.Series, ex_eff: pd.Timestamp, fac: float) -> tuple[pd.Timestamp | None, float | None, str]:
    """回傳 (階梯日 S, 觀察到的階梯大小, 分類 'seam'|'seam_factor_diff'|'unverifiable'|'none')。"""
    w = r[(r.index >= ex_eff - pd.Timedelta(days=WINDOW_DAYS)) & (r.index < ex_eff)]
    if len(w) < 3:
        return None, None, "none"
    want = fac - 1
    step = (w / w.shift(1) - 1).dropna()
    best, best_key, short = None, None, False
    for d, v in step.items():
        if v * want <= 0 or abs(v) < MIN_DROP / 2:      # 同方向、非雜訊
            continue
        after = w[w.index >= d]
        if len(after) < MIN_PERSIST_DAYS:
            short = short or (RATIO_LO <= v / want <= RATIO_HI)   # 階梯很貼近 ex（後面不夠日數驗證持續）：「看不到」≠「已修好」
            continue
        if (after / after.iloc[0] - 1).abs().max() > PERSIST_TOL:
            continue                                      # 階梯不持續 → 單日尖刺，不算
        key = abs(v - want)
        if best is None or key < best_key:
            best, best_key = (d, float(v)), key
    if best is None:
        return None, None, ("unverifiable" if short else "none")
    d, v = best
    if abs(v - want) <= TOL:
        return d, v, "seam"
    if RATIO_LO <= v / want <= RATIO_HI:
        return d, v, "seam_factor_diff"
    return None, None, "none"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adj", default=str(DEFAULT_ADJ))
    a = ap.parse_args(argv)

    raw = pd.read_parquet(RAW)
    raw["date"] = pd.to_datetime(raw["date"])
    cal = np.sort(raw["date"].unique())
    d0, d1 = raw["date"].min(), raw["date"].max()
    print(f"官方未還原價：{len(cal)} 天（{d0.date()}～{d1.date()}）")

    ev = pd.read_parquet(EV)
    ev["date"] = pd.to_datetime(ev["date"])
    ev = sa.resolve_events(ev)
    # 事件日對到官方實價日曆上 ≥ ex 的第一個交易日；落在覆蓋期（扣掉窗口）之外的不分析
    pos = np.searchsorted(cal, ev["date"].to_numpy())
    ev = ev[pos < len(cal)].copy()
    ev["ex_eff"] = pd.to_datetime(cal[np.searchsorted(cal, ev["date"].to_numpy())])
    ev = ev[ev["ex_eff"] > d0 + pd.Timedelta(days=WINDOW_DAYS)]
    print(f"事件（覆蓋期內，去重後）：{len(ev)} 件")

    adj = pd.read_parquet(a.adj, columns=["date", "ticker", "close"])
    adj["date"] = pd.to_datetime(adj["date"])
    adj["code"] = adj["ticker"].astype(str).str.replace(r"\..*$", "", regex=True)
    adj = adj[adj["date"] >= d0]
    m = adj.merge(raw[["ticker", "date", "close"]].rename(columns={"ticker": "code", "close": "raw"}),
                  on=["code", "date"])          # inner：自動排除母表休市／停牌幽靈列
    m["r"] = m["close"] / m["raw"]
    R = {c: g.set_index("date")["r"].sort_index() for c, g in m.groupby("code")}

    ev = ev.sort_values(["ticker", "ex_eff"]).copy()
    ev["gap_prev"] = ev.groupby("ticker")["ex_eff"].diff().dt.days
    ev["gap_next"] = -ev.groupby("ticker")["ex_eff"].diff(-1).dt.days
    out = []
    for e in ev.itertuples():
        s = R.get(e.ticker)
        status, S, obs = "no_data", None, None
        if s is not None:
            nwin = int(((s.index >= e.ex_eff - pd.Timedelta(days=WINDOW_DAYS)) & (s.index < e.ex_eff)).sum())
            if nwin < MIN_WINDOW_DAYS:
                status = "no_raw_window"        # 官方實價在該事件前的窗口不連續（回補尚未涵蓋）→ 不判斷，避免誤當成「已修好」
            elif abs(1 - e.factor) < MIN_DROP:
                status = "too_small"
            else:
                S, obs, status = detect(s, e.ex_eff, e.factor)
                status = {"none": "healed_or_none", "unverifiable": "seam_unverifiable"}.get(status, status)
        multi = bool((e.gap_prev == e.gap_prev and e.gap_prev <= MULTI_DAYS) or
                     (e.gap_next == e.gap_next and e.gap_next <= MULTI_DAYS))
        out.append({"ticker": e.ticker, "type": e.type, "source": e.source, "ex": e.date.date(),
                    "ex_eff": e.ex_eff.date(), "fac": round(e.factor, 6),
                    "observed_step": None if obs is None else round(obs, 6),
                    "seam_date": None if S is None else S.date(), "status": status, "multi": multi})
    res = pd.DataFrame(out)
    SEAMS.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(SEAMS, index=False)
    print(res["status"].value_counts().to_string())
    seam = res[res["status"].isin(["seam", "seam_factor_diff"])]
    if len(seam):
        gaps = (pd.to_datetime(seam["ex_eff"]) - pd.to_datetime(seam["seam_date"])).dt.days
        print(f"有接縫：{len(seam)} 件 / {seam['ticker'].nunique()} 檔；階梯日距 ex 的日曆日 "
              f"中位數 {int(gaps.median())}、P10 {int(gaps.quantile(.1))}、P90 {int(gaps.quantile(.9))}")

    # 驗證：訂正「seam 且非 multi」的事件後，r 在非 ex_eff 日不應再有階梯
    ok = res[(res["status"] == "seam") & (~res["multi"])]
    exs_by = {t: {pd.Timestamp(x) for x in g["ex_eff"]} for t, g in res.groupby("ticker")}
    rows = []
    for t, g in ok.groupby("ticker"):
        s = R[t].copy()
        for e in g.itertuples():
            s[s.index < pd.Timestamp(e.seam_date)] *= e.fac
        st = (s / s.shift(1) - 1)
        # 只比「官方交易日曆上相鄰的兩天」：實價回補未連續時，跨缺口的比值不是階梯
        cpos = pd.Series(np.searchsorted(cal, s.index.to_numpy()), index=s.index)
        near = s.index.to_series().diff().dt.days <= 10          # 回補段之間的缺口（如 2017→2026）不算相鄰
        st = st[(cpos.diff() == 1) & near].dropna()
        bad = st[(st.abs() > MIN_DROP) & (~st.index.isin(exs_by.get(t, set())))]
        rows += [{"ticker": t, "date": d.date(), "step": round(float(v), 6)} for d, v in bad.items()]
    resid = pd.DataFrame(rows, columns=["ticker", "date", "step"])
    # 歸因：①多檔同日（≥30 檔）＝上游單日壞資料／日期錯位；②該檔在 ±3 個交易日內有任何公司行為事件（含未納入訂正的 multi／too_small／
    # seam_factor_diff）＝事件相關；③都不是 ＝ unexplained（無跡可循，要人看）
    if len(resid):
        resid["date"] = pd.to_datetime(resid["date"])
        per_day = resid.groupby("date")["ticker"].transform("size")
        ev_pos = {t: np.searchsorted(cal, g["ex_eff"].to_numpy(dtype="datetime64[ns]")) for t, g in
                  res.assign(ex_eff=pd.to_datetime(res["ex_eff"])).groupby("ticker")}

        # 單日尖刺：同一檔相鄰兩個官方交易日的階梯方向相反、幅度相近（≤30% 差）＝母表（或實價）那一天的單日壞值，隔天恢復
        step_at = {(r_["ticker"], np.searchsorted(cal, np.datetime64(r_["date"]))): r_["step"] for r_ in resid.to_dict("records")}

        def spike(row):
            k = (row["ticker"], int(np.searchsorted(cal, np.datetime64(row["date"]))))
            for dk in (-1, 1):
                o = step_at.get((k[0], k[1] + dk))
                if o is not None and o * row["step"] < 0 and abs(abs(o) - abs(row["step"])) <= 0.3 * abs(row["step"]):
                    return True
            return False

        def why(row, n):
            if n >= 30:
                return "market_wide_same_day"
            if spike(row):
                return "one_day_spike"
            p_ = np.searchsorted(cal, np.datetime64(row["date"]))
            return "near_event" if any(abs(int(q) - int(p_)) <= 3 for q in ev_pos.get(row["ticker"], [])) else "unexplained"
        resid["reason"] = [why(r_, n) for r_, n in zip(resid.to_dict("records"), per_day)]
        resid["date"] = resid["date"].dt.date
    resid.to_csv(RESID, index=False)
    print(f"訂正後驗證：{len(ok)} 件訂正，非 ex 日殘留階梯 {len(resid)} 個（→ {RESID.name}）")
    if len(resid):
        print("  殘留歸因：" + "、".join(f"{k} {v}" for k, v in resid["reason"].value_counts().items()))
    print(f"→ {SEAMS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
