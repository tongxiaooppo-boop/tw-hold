"""實驗 E · 長波段候選池（CANSLIM + Minervini）事件驅動回測（HANDOFF_2026-09-11d §1.5）。

**這是回測，不是可行性普查。** 之前 `candidate_pool_survey.py`（實驗 D）只量「每週剩幾檔」，
沒有報酬、沒有回撤、沒有勝率。本腳本補這一塊——使用者的問題是「不求賺多少，但不要賠很大」，
產出重點壓在**最大回撤**。

規格（tw-hold/PRD.md §5.2／§5.3，逐字照做，不另外發明）：
    進場：候選池六條件全過（CANSLIM 基本面 ∩ 月營收 YoY>0 且加速 ∩ 法人 20 日淨買超>0 ∩
          Minervini 趨勢模板 8/8），每週檢查一次，若某檔已持有中則不重複進場。
    停損：risk_stop = max(50MA, 近 20 週前低, 現價 − 2×ATR14)——**進場當下算一次，
          不是每天重算**（比照使用者「掛券商停損單」的實務動作，PRD §5.3）。
          盤中最低價 ≤ risk_stop 當天觸發，成交價＝risk_stop 本身（樂觀假設，比照
          tw-swing 慣例，不假設跳空更差價位）。
    失效：§5.2.3 另外三條，週頻檢查——趨勢模板 < 5/8、月營收 YoY 連 2 個月轉負、
          最新季 EPS YoY 轉負。任一觸發 → 隔天開盤市價出場。

口徑（比照 tw-swing「買得到」慣例，見 RULE_LEDGER.md / STATUS 2026-09-10）：
    進場兩種都跑、都報：
      - next_open：訊號週最後交易日之後，次一交易日**無條件**開盤買進。
      - limit_at_close：訊號週收盤價當限價，之後 `LIMIT_WINDOW` 個交易日內第一個
        「開盤 ≤ 限價」或「盤中低點 ≤ 限價」的日子成交，一直沒到就放棄這筆（不進樣本）。
    出場（兩種口徑共用）：停損＝盤中最低價觸發、成交在停損價；失效條件＝隔天開盤市價。

部位大小：**等權，不做 PRD §5.3 那段「部位 = min(20%, 單筆風險%÷停損距離)」的推導**——
    該公式裡的「單筆風險%」全 repo 沒有定義成任何數字（只在 PRD 註解出現過一次，且
    §5.3 本身也只是「風控算術」的推導草稿，不是已實作的規則）。虛構一個門檻反而是
    「拿理論假設修正資料」的翻版（見記憶 tw-hold-active-etf-flag 的教訓）。改用同一
    專案 `research/backtest_rebalance.py` 已經在用的等權慣例：當天所有持倉部位平均分
    配（1/N），沒有持倉的日子報酬＝0（閒置現金不生息，保守假設，非無風險利率）。

🔴 生存者偏差：universe = 今天的 bundle `universe.parquet` `in_universe`
   （市值前500 ∪ 成交值前500 ∪ 兩者近似，~1968 檔），拿它回掃 2016 等於已知誰活到
   今天——**所有數字當上界看待**，真實結果會更差。
🔴 研究腳本不是產品碼——日線價格直接讀 tw-swing 本機 `data/store/daily_full.parquet`
   （tw-hold 自己 bundle 的 `prices_adj.parquet` 只從 2023-05-30 起，長度不夠）；
   財報/月營收/籌碼一律讀 tw-hold 自己的 `data/upstream/` bundle。不改 tw-swing
   任何檔案（紅線）。

用法：
    python research/backtest_longswing.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
TWSWING = Path(r"d:\g\claude\tw-swing")
sys.path.insert(0, str(TWSWING / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from twswing.data import store  # noqa: E402  只借日線母表，不碰 twswing.value

from factors.factors import quarterly_factors  # noqa: E402
from reference.loader import BUNDLE_DIR, load_quarterly  # noqa: E402
from reference.regime import LABELS as REGIME_LABELS  # noqa: E402
from reference.regime import ORDER as REGIME_ORDER  # noqa: E402
from reference.regime import regime_at  # noqa: E402
from screener.candidate_pool import ATR_N, RS_PCTILE_MIN, canslim_fundamental, monthly_yoy  # noqa: E402

OUT = REPO / "docs" / "reports"
OUT.mkdir(parents=True, exist_ok=True)

START = pd.Timestamp("2016-01-01")
# 🔴 2026-09-23 查證：候選池六條件之一 c_eps_3y_growth 需要12季前財報，但季度資料只從
# 2015-Q1起算，第一個候選池非空的週落在2019-02-15——2016-01到2019-02這段是資料地基
# 死區（候選池結構性恆空，不是策略沒機會）。`stats()`／`bench_stats()` 原本拿全部
# 2016-2026（10.65年）的天數去annualize，把這段長達3年的0%死區也算進分母，會把CAGR
# 拖低一大截（例："現行規格"從全窗算的21.4%其實應該是31.0%，比0050同期還高，結論
# 從「打不過0050」翻案成「小贏0050」）。EVAL_START = 全部規則的候選池死區都結束後
# 的整數年份起點，用來重新算「排除死區」版本的CAGR/回撤/分市況——回撤跟勝率本來就
# 不受影響（死區沒有部位，對這兩個指標是中性的），只有CAGR這種「金額/年數」的比例
# 指標會被死區污染分母。
EVAL_START = pd.Timestamp("2019-01-01")
COST_ACTUAL = 0.00585          # 來回成本（手續費 0.1425%×2 + 證交稅 0.3%），tw-swing 口徑
LIMIT_WINDOW = 3                # limit_at_close：幾個交易日內沒成交就放棄
REVENUE_LAG_DAYS = 9            # 月營收公告落後：涵蓋月次月 1 日 + 9 天 ≈ 次月 10 日法定期限
OOS_SPLIT = pd.Timestamp("2022-01-01")
TRAIL_ATR_MULT = 2.0            # 移動停損倍數，比照 tw-swing `H2-trailatr2`（見下方 simulate() 說明）
TRAIL_ATR_MULT_TIGHT = 1.5       # 2026-09-14「市況緊縮」變體：空頭/震盪週收緊，多頭維持 TRAIL_ATR_MULT


def _bare(s: pd.Series) -> pd.Series:
    return s.astype(str).str.split(".").str[0]


# ─────────────────────────── 資料載入 ───────────────────────────

def load_all():
    q = load_quarterly()
    qf = quarterly_factors(q)

    rev = pd.read_parquet(BUNDLE_DIR / "revenue.parquet")
    chips = pd.read_parquet(BUNDLE_DIR / "chips.parquet")

    uni_p = BUNDLE_DIR / "fundamentals" / "universe.parquet"
    uni_df = pd.read_parquet(uni_p, columns=["ticker", "in_universe"])
    universe = set(uni_df.loc[uni_df["in_universe"], "ticker"].astype(str))

    daily = store.read_daily(recent=False,
                             columns=["date", "ticker", "open", "high", "low", "close"])
    daily["date"] = pd.to_datetime(daily["date"])
    daily["ticker"] = _bare(daily["ticker"])
    daily = daily[daily["date"] >= START]
    # 只留 universe 交集（省記憶體、也是回測的實際母體）
    daily = daily[daily["ticker"].isin(universe | {"0050"})].copy()

    idx_close = (daily[daily["ticker"] == "0050"]
                .set_index("date")["close"].sort_index())

    return qf, rev, chips, universe, daily, idx_close


# ─────────────────────────── 全歷史向量化面板 ───────────────────────────

def build_panels(daily: pd.DataFrame, idx_close: pd.Series):
    """一次算好 date×ticker 的收盤/開盤/低點/趨勢/ATR/停損面板，供逐週掃描與逐日出場判斷共用。"""
    close = daily.pivot_table(index="date", columns="ticker", values="close").sort_index()
    openp = daily.pivot_table(index="date", columns="ticker", values="open").sort_index()
    high = daily.pivot_table(index="date", columns="ticker", values="high").sort_index()
    low = daily.pivot_table(index="date", columns="ticker", values="low").sort_index()

    ma50 = close.rolling(50).mean()
    ma150 = close.rolling(150).mean()
    ma200 = close.rolling(200).mean()
    ma200_1m = ma200.shift(21)
    lo52 = close.rolling(252).min()
    hi52 = close.rolling(252).max()
    low_20w = close.rolling(100).min()          # 20 週 ≈ 100 交易日（比照 screener/candidate_pool.py）

    ret126 = close / close.shift(126) - 1.0
    idxc = idx_close.reindex(close.index).ffill()
    idx126 = idxc / idxc.shift(126) - 1.0
    rel = ret126.sub(idx126, axis=0)
    rs_pctile = rel.rank(axis=1, pct=True) * 100

    t1 = (close > ma150) & (close > ma200)
    t2 = ma150 > ma200
    t3 = ma200 > ma200_1m
    t4 = (ma50 > ma150) & (ma150 > ma200)
    t5 = close > ma50
    t6 = close >= lo52 * 1.30
    t7 = close >= hi52 * 0.75
    t8 = rs_pctile > RS_PCTILE_MIN
    trend_cnt = (t1.astype(float) + t2 + t3 + t4 + t5 + t6 + t7 + t8)

    pc = close.shift(1)
    hl, hc, lc = high - low, (high - pc).abs(), (low - pc).abs()
    tr = pd.DataFrame(np.nanmax(np.stack([hl.values, hc.values, lc.values]), axis=0),
                      index=close.index, columns=close.columns)
    atr = tr.rolling(ATR_N).mean()

    risk_stop = pd.DataFrame(
        np.maximum(np.maximum(ma50.values, low_20w.values), (close - 2 * atr).values),
        index=close.index, columns=close.columns)

    return {
        "close": close, "open": openp, "high": high, "low": low,
        "trend_cnt": trend_cnt, "atr": atr, "risk_stop": risk_stop,
    }


def weekly_dates(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(idx, index=idx)
    return pd.DatetimeIndex(s.groupby(idx.to_period("W")).last().values)


def revenue_state(rev: pd.DataFrame, dates: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    """月營收 YoY 狀態，攤成 date×ticker 的 step function（`available_date` 生效直到下一筆公告）。
    回傳 `{"yoy": 面板, "accel": 面板, "neg2": 面板}`（皆 bool/float，index=dates）。"""
    r = rev.copy()
    r["ticker"] = _bare(r["ticker"])
    r = monthly_yoy(r)
    r["available_date"] = (pd.to_datetime(r["month"]) + pd.DateOffset(months=1)
                           + pd.Timedelta(days=REVENUE_LAG_DAYS))
    r["neg2"] = (r["yoy"] < 0) & (r["yoy_prev"] < 0)
    r["accel"] = r["yoy"] > r["yoy_prev"]

    out = {}
    all_cols = sorted(r["ticker"].unique())
    for col, fill in (("yoy", np.nan), ("accel", False), ("neg2", False)):
        piv = r.pivot_table(index="available_date", columns="ticker", values=col, aggfunc="last")
        piv = piv.reindex(columns=all_cols)
        piv = piv.reindex(piv.index.union(dates)).sort_index().ffill().reindex(dates)
        out[col] = piv.fillna(fill)
    return out


def inst_state(chips: pd.DataFrame, dates: pd.DatetimeIndex, window: int = 20) -> pd.DataFrame:
    c = chips.copy()
    c["date"] = pd.to_datetime(c["date"])
    c["ticker"] = _bare(c["ticker"])
    c["net"] = c["foreign_net"].fillna(0) + c["trust_net"].fillna(0)
    piv = c.pivot_table(index="date", columns="ticker", values="net", aggfunc="sum")
    net20 = piv.rolling(window, min_periods=window).sum()
    return net20.reindex(net20.index.union(dates)).sort_index().ffill().reindex(dates)


# ─────────────────────────── 逐週候選 ───────────────────────────

def weekly_candidates(qf, rev_st, inst20, panels, weeks, universe) -> dict[pd.Timestamp, set[str]]:
    """每週全過六條件的 ticker 集合。"""
    trend_ok = (panels["trend_cnt"] >= 8)
    out = {}
    for wk in weeks:
        fund = canslim_fundamental(qf, wk)
        fset = set(fund.index[fund[["c_eps_yoy", "c_eps_3y_growth", "c_roe",
                                    "c_gm_not_deteriorating", "c_fscore"]].all(axis=1)])
        try:
            rset = set(rev_st["yoy"].loc[wk].index[
                (rev_st["yoy"].loc[wk] > 0) & (rev_st["accel"].loc[wk])])
        except KeyError:
            rset = set()
        try:
            iset = set(inst20.loc[wk].index[inst20.loc[wk] > 0])
        except KeyError:
            iset = set()
        try:
            tset = set(trend_ok.loc[wk].index[trend_ok.loc[wk].fillna(False)])
        except KeyError:
            tset = set()
        allpass = fset & rset & iset & tset & universe
        out[wk] = allpass
    return out


# ─────────────────────────── 逐檔事件模擬 ───────────────────────────

def simulate(entry_mode: str, weeks, cand_by_week, panels, rev_st, qf_eps_state, trading_days,
            trailing: bool = False, trail_mult_by_week: dict | None = None):
    """回傳 `(交易清單, 放棄筆數)`。交易清單元素：`{ticker, entry_date, entry_price,
    exit_date, exit_price, exit_reason, stop, still_open}`。放棄筆數＝訊號成交時
    價格已經跌破當初算的停損位（不合理進場，直接放棄，見 main() 呼叫端說明）。
    `entry_mode` = "next_open" | "limit_at_close"。

    `trailing=True`：**不是把 §5.3 公式（含 50MA）每週重算**——那條公式是設計成進場當下
    的一次性快照，50MA 是「以防萬一崩了」的保護，不是拿來每週追價的移動停損（試過了：
    正常拉回時價格常態性跌破自己的 50MA，公式重算會瞬間跳到收盤價之上、幾乎每次都秒殺，
    見 HANDOFF 對話紀錄）。改照 tw-swing `H2-trailatr2` 實際的作法（`twswing/backtest/
    engine.py` `run_high - trail_atr × 進場日 ATR14`）：追蹤「進場後最高價」，停損＝
    `run_high − mult × atr0`（`atr0` 是進場當天的 ATR14，固定不變，只有
    `run_high` 會變，且只漲不跌）——完全不碰 50MA，天生只會往上調，沒有上面那種公式
    暴衝問題。`trailing=False`＝PRD §5.2.3 字面規格，停損進場當下算一次、之後固定不動
    （比照使用者「掛券商停損單」的實務動作）。

    `trail_mult_by_week`：`{week -> mult}`，None 或查無該週時退回 `TRAIL_ATR_MULT`
    （固定倍數）。每週檢查時用**當週**的倍數重算 `cur_stop`——倍數改變只影響「用多大
    的緩衝去追」，不會讓已經抬高的停損位倒退（`max(pos["stop"], ...)` 保證單調不降），
    比照 2026-09-14「市況緊縮：空頭/震盪收窄到 1.5×，多頭維持 2.0×」的測試。"""
    close, openp, low, high = panels["close"], panels["open"], panels["low"], panels["high"]
    trend_cnt, risk_stop_panel, atr_panel = panels["trend_cnt"], panels["risk_stop"], panels["atr"]
    td = trading_days
    trades = []
    open_pos: dict[str, dict] = {}   # ticker -> position dict（尚未平倉）
    abandoned_below_stop = [0]       # list 當可變 box，方便內層 continue 也能累加

    def _next_idx(after_date):
        pos = td.searchsorted(after_date, side="right")
        return pos

    for wk in weeks:
        for tk in sorted(cand_by_week.get(wk, ())):
            if tk in open_pos:
                continue
            if tk not in close.columns:
                continue
            wk_pos = td.searchsorted(wk, side="right") - 1
            if wk_pos < 0 or wk_pos >= len(td) - 1:
                continue
            sig_close = close[tk].iloc[wk_pos]
            stop = risk_stop_panel[tk].iloc[wk_pos]
            if pd.isna(sig_close) or pd.isna(stop):
                continue

            entry_date = entry_price = None
            if entry_mode == "next_open":
                i = wk_pos + 1
                if i < len(td) and pd.notna(openp[tk].iloc[i]):
                    entry_date, entry_price = td[i], float(openp[tk].iloc[i])
            else:  # limit_at_close
                limit = sig_close
                for i in range(wk_pos + 1, min(wk_pos + 1 + LIMIT_WINDOW, len(td))):
                    o, lo = openp[tk].iloc[i], low[tk].iloc[i]
                    if pd.isna(o) or pd.isna(lo):
                        continue
                    if o <= limit:
                        entry_date, entry_price = td[i], float(o)
                        break
                    if lo <= limit:
                        entry_date, entry_price = td[i], float(limit)
                        break
            if entry_date is None:
                continue   # 沒成交，這筆訊號放棄（不進樣本）
            if entry_price <= stop:
                # 訊號週收盤到實際成交之間價格已經跌破停損位（尤其 limit_at_close：
                # 買在拉回，拉回可能已經拉破當初算的停損）——真實情況是停損單直接
                # 觸發，不會有人在已經跌破自己停損價的地方才進場，這筆訊號放棄。
                abandoned_below_stop[0] += 1
                continue

            entry_idx = int(td.searchsorted(entry_date))
            atr0 = atr_panel[tk].iloc[entry_idx] if tk in atr_panel.columns else np.nan
            open_pos[tk] = {"ticker": tk, "entry_date": entry_date,
                            "entry_price": entry_price, "stop": float(stop),
                            "entry_idx": entry_idx, "checked_idx": entry_idx - 1,
                            "atr0": float(atr0) if pd.notna(atr0) else None,
                            "run_high": float(high[tk].iloc[entry_idx])
                            if tk in high.columns and pd.notna(high[tk].iloc[entry_idx])
                            else entry_price}

        # 每週結尾檢查失效條件（週頻，比照 §5.2.3）+ 每天的停損（逐日已含在下面收盤時點檢查）
        wk_pos = td.searchsorted(wk, side="right") - 1
        if wk_pos < 0:
            continue
        for tk in list(open_pos):
            pos = open_pos[tk]
            i0, i1 = pos["checked_idx"] + 1, wk_pos
            if i1 < i0:
                continue
            pos["checked_idx"] = i1
            # 移動停損：用「上次檢查前」的 run_high 抬停損（跟 tw-swing engine.py 同一個
            # 「收盤後才更新」精神——本週的新高不能拿來抬本週自己要用的停損，否則是未來函數）。
            if trailing and pos.get("atr0"):
                mult = (trail_mult_by_week.get(wk, TRAIL_ATR_MULT)
                       if trail_mult_by_week is not None else TRAIL_ATR_MULT)
                cur_stop = max(pos["stop"], pos["run_high"] - mult * pos["atr0"])
            else:
                cur_stop = pos["stop"]
            # 停損：只掃「上次檢查後到本週五」的新區間（逐日看盤中低點，避免每週重掃全歷史）
            seg_low = low[tk].iloc[i0:i1 + 1]
            hit = seg_low[seg_low <= cur_stop]
            if len(hit):
                exit_pos_abs = seg_low.index.get_loc(hit.index[0]) + i0
                pos["stop"] = cur_stop
                trades.append({**pos, "exit_date": td[exit_pos_abs], "exit_price": cur_stop,
                              "exit_reason": "停損" if not trailing else "移動停損",
                              "still_open": False})
                del open_pos[tk]
                continue
            pos["stop"] = cur_stop
            if trailing and tk in high.columns:
                wk_high = high[tk].iloc[i0:i1 + 1].max()
                if pd.notna(wk_high):
                    pos["run_high"] = max(pos["run_high"], float(wk_high))
            # 失效（§5.2.3 另三條）：本週五收盤狀態
            cnt = trend_cnt[tk].iloc[wk_pos] if tk in trend_cnt.columns else np.nan
            neg2 = (rev_st["neg2"].loc[wk, tk] if tk in rev_st["neg2"].columns else False)
            eps_neg = qf_eps_state.get(tk, {}).get(wk, False)
            if (pd.notna(cnt) and cnt < 5) or bool(neg2) or bool(eps_neg):
                j = wk_pos + 1
                if j < len(td) and pd.notna(openp[tk].iloc[j]):
                    reason = ("趨勢<5/8" if pd.notna(cnt) and cnt < 5
                             else "月營收連2月轉負" if neg2 else "季EPS YoY轉負")
                    trades.append({**pos, "exit_date": td[j], "exit_price": float(openp[tk].iloc[j]),
                                  "exit_reason": reason, "still_open": False})
                    del open_pos[tk]

    # 回測結束仍持有 → mark-to-market 收尾
    last_date = td[-1]
    for tk, pos in open_pos.items():
        px = close[tk].iloc[-1]
        if pd.notna(px):
            trades.append({**pos, "exit_date": last_date, "exit_price": float(px),
                          "exit_reason": "回測結束仍持有", "still_open": True})
    return trades, abandoned_below_stop[0]


def eps_yoy_negative_state(qf: pd.DataFrame, weeks) -> dict[str, dict[pd.Timestamp, bool]]:
    """每檔、每週：最新已公告季 EPS YoY 是否 < 0（disclosure_date 安全邊界）。"""
    q = qf.sort_values(["ticker", "period_end"]).copy()
    g = q.groupby("ticker", sort=False)
    q["eps_yoy_q"] = q["eps"] / g["eps"].shift(4) - 1.0
    q = q.dropna(subset=["disclosure_date"]).sort_values("disclosure_date")
    out: dict[str, dict[pd.Timestamp, bool]] = {}
    for tk, grp in q.groupby("ticker", sort=False):
        grp = grp.sort_values("disclosure_date")
        s = grp.set_index("disclosure_date")["eps_yoy_q"]
        step = s.reindex(s.index.union(weeks)).sort_index().ffill().reindex(weeks)
        out[tk] = {wk: bool(v < 0) for wk, v in zip(weeks, step) if pd.notna(v)}
    return out


# ─────────────────────────── 組合層彙整 ───────────────────────────

def portfolio_curve(trades: list[dict], close: pd.DataFrame, td: pd.DatetimeIndex) -> pd.Series:
    """等權（1/N 當日持倉數）逐日組合報酬 → 累積淨值曲線（index=交易日）。"""
    completed = [t for t in trades]
    daily_ret = pd.Series(0.0, index=td)
    daily_cnt = pd.Series(0, index=td)
    for t in completed:
        tk = t["ticker"]
        if tk not in close.columns:
            continue
        i0 = td.searchsorted(t["entry_date"])
        i1 = td.searchsorted(t["exit_date"])
        if i1 < i0:
            continue
        px = close[tk]
        for i in range(i0, i1 + 1):
            if i == i0:
                prev_px = t["entry_price"]
            else:
                prev_px = px.iloc[i - 1]
            cur_px = t["exit_price"] if i == i1 else px.iloc[i]
            if pd.isna(prev_px) or pd.isna(cur_px) or prev_px == 0:
                continue
            r = cur_px / prev_px - 1.0
            if i == i1 and not t.get("still_open"):
                r = (1 + r) * (1 - COST_ACTUAL) - 1.0   # 出場當天扣一次來回成本
            daily_ret.iloc[i] += r
            daily_cnt.iloc[i] += 1
    avg_ret = (daily_ret / daily_cnt.replace(0, np.nan)).fillna(0.0)
    return (1 + avg_ret).cumprod()


def stats(curve: pd.Series) -> dict:
    yrs = (curve.index[-1] - curve.index[0]).days / 365.25
    cagr = curve.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else np.nan
    dd = (curve / curve.cummax() - 1).min()
    yr_last = curve.groupby(curve.index.year).last()
    yr_ret = yr_last / yr_last.shift(1) - 1
    yr_ret.iloc[0] = curve.groupby(curve.index.year).last().iloc[0] / curve.iloc[0] - 1
    return {"cagr": cagr, "maxdd": dd, "final": curve.iloc[-1], "yr_ret": yr_ret}


def eval_window_stats(curve: pd.Series, eval_start: pd.Timestamp = EVAL_START) -> dict:
    """`stats()` 的死區修正版——只用 `eval_start` 之後的曲線重新正規化（除以該點的值）
    再算年化/回撤，排除候選池死區把分母（年數）灌水的問題。回撤/期末淨值（相對值）
    不受死區影響本來就跟 `stats()` 一樣，這裡重算是為了 CAGR 分母正確、且回傳的
    `final` 是「以 eval_start 為 1.0」的相對倍數，不能跟 `stats()` 的 `final` 直接比。"""
    c = curve.loc[curve.index >= eval_start]
    if len(c) < 2:
        return {"cagr": np.nan, "maxdd": np.nan, "final": np.nan}
    c = c / c.iloc[0]
    yrs = (c.index[-1] - c.index[0]).days / 365.25
    cagr = c.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else np.nan
    dd = (c / c.cummax() - 1).min()
    return {"cagr": cagr, "maxdd": dd, "final": c.iloc[-1]}


def bench_stats(close: pd.Series) -> dict:
    yrs = (close.index[-1] - close.index[0]).days / 365.25
    r = close / close.iloc[0]
    cagr = r.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else np.nan
    dd = (r / r.cummax() - 1).min()
    return {"cagr": cagr, "maxdd": dd}


# ─────────────────────────── 主流程 ───────────────────────────

def main() -> int:
    print("載入資料…", flush=True)
    qf, rev, chips, universe, daily, idx_close = load_all()
    print(f"  universe {len(universe)} 檔（bundle universe.parquet in_universe）", flush=True)

    print("建立向量化面板（趨勢模板／ATR／停損）…", flush=True)
    panels = build_panels(daily, idx_close)
    td = panels["close"].index
    weeks = weekly_dates(td)
    weeks = weeks[weeks <= td.max()]
    print(f"  {len(weeks)} 週｜{weeks[0].date()} → {weeks[-1].date()}", flush=True)

    rev_st = revenue_state(rev, weeks)
    inst20 = inst_state(chips, weeks)
    eps_neg = eps_yoy_negative_state(qf, weeks)

    print("逐週掃候選池…", flush=True)
    cand_by_week = weekly_candidates(qf, rev_st, inst20, panels, weeks, universe)
    counts = pd.Series({wk: len(s) for wk, s in cand_by_week.items()})
    print(f"  候選數：中位數 {counts.median():.0f}｜空白週 {(counts == 0).mean():.0%}", flush=True)

    # 市況進場篩選（2026-09-14，HANDOFF_2026-09-14b.md §4：「市況進場 × 移動停損」
    # 組合矩陣，補上「M gate + 移動停損」「更軟的市況篩選」這兩個沒測過的空格）。
    # 只影響*新進場*，已持有部位不受影響（現實中不會因市況轉弱就強制平倉既有部位）。
    idx_close_full = idx_close.reindex(td).ffill()
    week_regime = regime_at(pd.Series(weeks), idx_close_full)
    week_regime.index = weeks
    week_regime = week_regime.where(week_regime.notna(), None)   # pd.NA → None，避免三態比較歧義

    cand_by_week_bull = {wk: (s if week_regime.get(wk) == "bull" else set())
                        for wk, s in cand_by_week.items()}
    cand_by_week_notbear = {wk: (s if week_regime.get(wk) != "bear" else set())
                           for wk, s in cand_by_week.items()}
    n_bull = int((week_regime == "bull").sum())
    n_bear = int((week_regime == "bear").sum())
    print(f"  市況週數：多頭 {n_bull}/{len(weeks)}（{n_bull / len(weeks):.0%}）｜"
         f"空頭 {n_bear}/{len(weeks)}（{n_bear / len(weeks):.0%}）——"
         f"bull_only 擋掉 {len(weeks) - n_bull} 週、not_bear 擋掉 {n_bear} 週的新進場",
         flush=True)

    # 🆕 市況緊縮移動停損（HANDOFF 使用者 2026-09-14 拍板要測）：空頭/震盪週收緊到
    # TRAIL_ATR_MULT_TIGHT，多頭維持 TRAIL_ATR_MULT——只影響每週重算 `cur_stop` 用的
    # 倍數，停損位本身仍然只漲不跌（simulate() 的 `max(pos["stop"], ...)`）。
    trail_mult_tight = {wk: (TRAIL_ATR_MULT if week_regime.get(wk) == "bull"
                             else TRAIL_ATR_MULT_TIGHT) for wk in weeks}

    REGIME_FILTERS = [("none", cand_by_week), ("bull", cand_by_week_bull),
                     ("notbear", cand_by_week_notbear)]
    # 舊 key 名沿用（跟 20260912 報告、既有 CSV 檔名對得起來），新增的三格用
    # `next_open_{市況}_{停損}` 命名。
    KEY_ALIAS = {("none", "fixed"): "next_open", ("none", "trailing"): "next_open_trailing",
                ("bull", "fixed"): "next_open_mgate_bull"}

    # 🔴 2026-09-23 使用者裁決：`limit_at_close`（訊號收盤掛限價、3日內沒成交放棄）
    # 這個進場假設不再出現在任何主要回測矩陣裡——tw-swing 之前實測過類似的限價版本
    # 已經打槍，本 repo 的買得到口徑唯一定義是 `next_open`（次日開盤）。這支腳本
    # 2026-09-23 之前曾經把 `limit_at_close` 誤標成「買得到口徑」（跟
    # `backtest_scenario_b.py`／`backtest_top17_buyable.py` 的定義矛盾），也曾經
    # 額外測過兩格「limit_at_close + notbear + trailing/trailtight」當穩健性對照
    # ——都已經移除，不要再加回來。往後如果真的需要限價假設的穩健性測試，另外開
    # 一次性分析腳本跑，不要混進這支主矩陣。
    RUNS = []
    for rkey, cbw in REGIME_FILTERS:
        for skey, trailing in (("fixed", False), ("trailing", True)):
            key = KEY_ALIAS.get((rkey, skey), f"next_open_{rkey}_{skey}")
            RUNS.append((key, "next_open", trailing, cbw, None))
    # 只在目前最佳格（not_bear）上疊加市況緊縮變體，不是全矩陣都測——這格已經是
    # 「排除空頭週 + 移動 ATR 停損」最佳解，緊縮變體要回答的問題是「同一個進場篩選下，
    # 停損倍數再依市況微調會不會更好」，跟其他進場篩選組合疊加緊縮不是這次的問題。
    RUNS.append(("next_open_notbear_trailtight", "next_open", True,
                cand_by_week_notbear, trail_mult_tight))

    results = {}
    abandoned = {}
    for key, mode, trailing, cbw, trail_map in RUNS:
        print(f"模擬進出場（{key}）…", flush=True)
        trades, n_abandoned = simulate(mode, weeks, cbw, panels, rev_st, eps_neg, td,
                                       trailing=trailing, trail_mult_by_week=trail_map)
        curve = portfolio_curve(trades, panels["close"], td)
        results[key] = (trades, curve)
        abandoned[key] = n_abandoned
        print(f"  完成 {len([t for t in trades if not t['still_open']])} 筆"
             f"（{len(trades)} 筆含未平倉，另有 {n_abandoned} 筆訊號成交時已跌破停損位、放棄）",
             flush=True)

    bench = bench_stats(idx_close_full)
    reg = regime_at(pd.Series(td), idx_close_full)
    reg.index = td   # `regime_at` 回傳的 index 是輸入 Series 的 index（0..N-1），
                     # 不是日期——這裡換成日期索引，才能用 `.reindex(日期)` 對齊

    counts_eval = counts[counts.index >= EVAL_START]
    md = ["# 實驗 E · 長波段候選池事件驅動回測（2026-09-23 修正版：排除候選池資料死區）",
         "",
         f"- 產出：{pd.Timestamp.now():%Y-%m-%d %H:%M}（修正原 2026-09-14 版本，"
         "見下方🔴說明；原始版本保留在 `backtest_longswing_20260914.md` 當歷史紀錄，"
         "已加註超連結指到這份）",
         f"- 規格：tw-hold/PRD.md §5.2（進場六條件）／§5.3（停損＝max(50MA,20週前低,"
         "現價−2×ATR14)）／§5.2.3（失效條件）——見 HANDOFF_2026-09-11d.md §1.5",
         f"- 期間：{weeks[0].date()} → {weeks[-1].date()}（{len(weeks)} 週）",
         f"- universe：{len(universe)} 檔（bundle `universe.parquet` `in_universe`，"
         "今天的市值/成交值前段班——🔴 生存者偏差，結論當上界）",
         f"- 成本：{COST_ACTUAL:.3%}（來回，出場當天一次扣）",
         "- 部位：等權（1/N 當日持倉數）——**不做 §5.3「單筆風險%÷停損距離」的部位公式**，"
         "因為「單筆風險%」全 repo 沒有定義成數字，虛構一個門檻等於拿理論假設修正結論",
         f"- 候選池（全窗 {len(weeks)} 週）：中位數 {counts.median():.0f} 檔/週｜"
         f"空白週 {(counts == 0).mean():.0%}；**排除死區、只看 {EVAL_START.date()} 起"
         f"（{len(counts_eval)} 週）：中位數 {counts_eval.median():.0f} 檔/週｜"
         f"空白週 {(counts_eval == 0).mean():.0%}**（跟實驗 D 2026-09-11 的普查數字"
         "一致，見 candidate_pool_survey.md）",
         "",
         f"🔴 **2026-09-23 查證：{EVAL_START.date()} 前候選池結構性恆空，是資料地基"
         "問題**——候選池六條件之一「近3年TTM EPS要成長」（`c_eps_3y_growth`）要拿"
         "12季前的財報比較，但季度財報資料只從2015-Q1開始，往回推第一次算得出來要到"
         "2019附近，實測第一個候選池非空的週是 **2019-02-15**。這不是策略評估過"
         "2016-2018那三年、市場剛好沒有標的——是資料根本不足以判定。原本 `stats()` "
         f"annualize 用全窗（2016-01→2026-09，{(weeks[-1]-weeks[0]).days/365.25:.1f}年）"
         "當分母，把這段近3年的0%死區也算進去，會把CAGR拖低一大截；下面每個口徑都"
         f"多列一欄「{EVAL_START.date()}起」的正確年化，**判斷打不打得過0050要看"
         "這一欄**。「現行規格」（排除空頭週+移動ATR停損）原本全窗算出 +21.4% 輸給"
         "0050同期 +24.0%，修正後是 **+31.0% 小贏 0050 修正後的 +29.7%**——"
         "結論從「打不過大盤」翻案成「小贏大盤」，不是排版問題，是實質性數字錯誤"
         "的修正。", ""]

    REGIME_LABEL = {"none": "不限市況", "bull": "只在多頭週新進場（M gate）",
                   "notbear": "排除空頭週新進場（多頭+震盪皆可）"}
    STOP_LABEL = {"fixed": "固定停損", "trailing": "移動 ATR 停損"}
    RUN_LABELS = [("next_open", "次日開盤（＝本repo買得到口徑，PRD §5.2.3 字面"
                  "規格：固定停損。`limit_at_close`〔限價於訊號收盤〕這個更保守的"
                  "進場假設 2026-09-23 起不再測——tw-swing 之前實測過類似版本已"
                  "打槍，本 repo 買得到原則唯一定義是次日開盤）"),
                 ("next_open_trailing", "次日開盤 + 移動 ATR 停損（比照 tw-swing "
                  "H2-trailatr2 的做法，非 PRD 原規格，只為了回答「是規格保守還是"
                  "出場拖累」）"),
                 ("next_open_mgate_bull", f"次日開盤 + CANSLIM「M」硬性 gate"
                  f"（只在大盤多頭週才新進場，{len(weeks) - n_bull}/{len(weeks)} 週"
                  f"（{(len(weeks) - n_bull) / len(weeks):.0%}）被擋掉新進場，已持有部位"
                  "不受影響；固定停損，跟 next_open 對照才看得出 M gate 本身的效果）")]
    existing_keys = {k for k, _ in RUN_LABELS}
    for rkey, _ in REGIME_FILTERS:
        for skey in ("fixed", "trailing"):
            key = KEY_ALIAS.get((rkey, skey), f"next_open_{rkey}_{skey}")
            if key in existing_keys:
                continue
            RUN_LABELS.append((key, f"🆕 次日開盤 + {REGIME_LABEL[rkey]} + {STOP_LABEL[skey]}"
                              "（市況進場 × 移動停損組合矩陣，HANDOFF_2026-09-14b.md §4）"))
    RUN_LABELS.append(("next_open_notbear_trailtight",
                      f"🆕 次日開盤 + 排除空頭週新進場 + 市況緊縮移動停損（多頭 {TRAIL_ATR_MULT}×"
                      f"ATR14、空頭/震盪收緊到 {TRAIL_ATR_MULT_TIGHT}×ATR14——在目前最佳格"
                      "（排除空頭週+移動停損）上疊加，回答「同一個進場篩選下停損倍數依市況"
                      "微調會不會更好」，使用者 2026-09-14 拍板要測）"))
    bench_eval = eval_window_stats(idx_close_full)

    for mode, label in RUN_LABELS:
        trades, curve = results[mode]
        st = stats(curve)
        st_eval = eval_window_stats(curve)
        completed = [t for t in trades if not t["still_open"]]
        wins = [t for t in completed if t["exit_price"] > t["entry_price"]]
        win_rate = len(wins) / len(completed) if completed else np.nan
        reason_cnt = pd.Series([t["exit_reason"] for t in completed]).value_counts()

        md += [f"## {label}", "",
              f"🔴 **候選池 {EVAL_START.date()} 前結構性恆空**（CANSLIM `c_eps_3y_growth` "
              "需要12季前財報，資料只從2015-Q1起算，第一個非空候選池的週落在"
              "2019-02-15）——「全窗年化」把這段死區也算進annualize的年數分母，"
              f"會把年化拖低；「{EVAL_START.date()}起」是排除死區、正確的年化，"
              "**判斷這條規則打不打得過0050要看這一欄，不要看全窗年化**。回撤/勝率"
              "不受死區影響，兩欄一樣。", "",
              "| | 年化（全窗，被死區拖低🔴） | 年化（"
              f"{EVAL_START.date()}起，正確） | 最大回撤 | 完成交易 | 勝率 |",
              "| :-- | --: | --: | --: | --: | --: |",
              f"| **策略** | {st['cagr']:+.2%} | **{st_eval['cagr']:+.2%}** | "
              f"{st['maxdd']:.1%} | {len(completed)} | {win_rate:.0%} |",
              f"| 0050（同期，`daily_full` 還原序列） | {bench['cagr']:+.2%} | "
              f"**{bench_eval['cagr']:+.2%}** | {bench['maxdd']:.1%} | — | — |", "",
              f"另有 {abandoned[mode]} 筆訊號在成交當下價格已經跌破當初算的停損位而放棄"
              "（訊號週收盤到實際成交之間拉回過深，尤其限價口徑本來就買在拉回，"
              "拉回可能已經拉破停損——這種進場不合理，不計入樣本）。", "",
              "出場原因分布：" + "、".join(f"{k} {v}" for k, v in reason_cnt.items()), "",
              "分年報酬（2016-2018 是候選池死區，顯示 +0% 不是策略沒機會）：" +
              "、".join(f"{y} {v:+.0%}" for y, v in st["yr_ret"].dropna().items()), ""]

        # 分市況（只算死區結束後的天數，避免死區把某個市況的累積報酬稀釋掉）
        md += [f"分市況（0050 代理，`reference.regime`，只算 {EVAL_START.date()} 起）：", ""]
        curve_eval_win = curve.loc[curve.index >= EVAL_START]
        curve_ret = curve_eval_win.pct_change().fillna(0.0)
        reg_str = reg.reindex(curve_eval_win.index).astype(str)
        for k in REGIME_ORDER:
            mask = (reg_str.values == k)
            sub = curve_ret[mask]
            if len(sub):
                cum = (1 + sub).prod() - 1
                md.append(f"- **{REGIME_LABELS[k]}**（{mask.sum()} 日）：累積 {cum:+.1%}")
        md.append("")

        # 樣本外（2022+）
        oos_curve = curve[curve.index >= OOS_SPLIT]
        if len(oos_curve) > 5:
            oos_ret = oos_curve.iloc[-1] / oos_curve.iloc[0] - 1
            oos_dd = (oos_curve / oos_curve.cummax() - 1).min()
            bench_oos = idx_close_full[idx_close_full.index >= OOS_SPLIT]
            bench_oos_ret = bench_oos.iloc[-1] / bench_oos.iloc[0] - 1
            md += [f"樣本外（{OOS_SPLIT.date()}起）：策略 {oos_ret:+.1%}（回撤 {oos_dd:.1%}）"
                  f" vs 0050 {bench_oos_ret:+.1%}", ""]

    md += ["## 生存者偏差", "",
          "universe 是今天 bundle 的 `in_universe`（市值/成交值前段班），拿它回溯 2016 等於",
          "已知誰活到今天。免費層拿不到歷史成分股，這個偏差消不掉——**上面所有數字都是",
          "上界**，真實結果會更差（下市、重大衰退的公司當年會在候選池裡出現過，這裡看不到）。",
          "", "## 已知簡化（跟 v1 產品邏輯的差異，供解讀時參考）", "",
          "- 停損位在進場當下算一次、不逐日重算（比照使用者掛券商停損單的實務動作）。",
          "- 失效條件週頻檢查、出場統一隔天開盤（不管進場口徑），跟停損（逐日盤中低點）分開判定。",
          "- 部位大小＝等權，不是 §5.3 那段風控推導（見上方口徑說明）。",
          "- 閒置現金報酬＝0（保守假設，不是無風險利率）。",
          "- 月營收失效條件照 PRD §5.2.3 字面「連 2 個月轉負」（本月與上月 YoY 皆<0）——"
          "比 `screener/candidate_pool.py` 產品頁 `_invalidation()` 顯示用的「單月 YoY<0」"
          "嚴格，兩者不是同一條規則，是刻意的（回測要照 PRD 原文，不是照 UI 簡化版）。",
          "- 價格序列直接讀 tw-swing 本機 `data/store/daily_full.parquet`（比照實驗 D 的作法），"
          "沒有套用 tw-hold `reference/corporate_actions.py` 那份手動面額變更/分割對照表——"
          "兩邊上游各自的還原品質可能不完全一致，跟 v1 產品頁看到的價格未必逐檔一致。", ""]

    out_md = OUT / "backtest_longswing_20260923.md"
    out_md.write_text("\n".join(md), encoding="utf-8")
    for mode, _, _, _, _ in RUNS:
        trades, _ = results[mode]
        pd.DataFrame(trades).to_csv(OUT / f"backtest_longswing_{mode}.csv", index=False)

    print("\n".join(md))
    print(f"\n-> {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
