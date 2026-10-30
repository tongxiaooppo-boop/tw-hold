"""個股查詢「估值速覽」：營收 → EPS → 股價的透明試算（2026-10-29）。

不是預測、不是目標價——把「拿最近的營運速度年化，再套自己過去的本益比」這條
常見的試算攤開，並把最容易灌水的兩個輸入（業外、單月營收）處理掉：

- 營收：近 3 個月月營收合計（不用單月×3）。
- 毛利率：最新一季；敏感度矩陣另外 ±3pp。
- 營業費用：最新一季**費用率** × 試算營收（2026-10-29 使用者拍板；原本固定金額
  會在營收升時偏樂觀，留在推導表當對照）。
- 業外：主版本「排除業外」＝業外歸零（也一併拿掉利息費用，所以不叫「核心」）；
  對照版本加回近 4 季平均業外。
- 稅：不估稅率，用 TTM「歸母淨利 ÷ 稅前」轉換率（含稅與非控制權益），原值攤開。
- 股數：近 4 季「歸母淨利 ÷ EPS」中位數（EPS 近零的季不算），不用股本÷10
  （非 10 元面額會錯）。
- 今年預估 EPS：已公布季實際 ＋ 未公布季 × 試算單季 EPS（2026-10-29 使用者要求）。
- 三段價：近 5 年各年平均 trailing PE（排除虧損日）的最低/中間/最高 × 今年預估 EPS
  ＝便宜/合理/昂貴（使用者指定；外資的平均 ±1σ 在展開當對照）。trailing 倍數乘預估 EPS 是口徑錯配，只能當「市場照過去倍數給今年獲利」的試算。
- 成長價（使用者 Excel 口徑）：今年預估 EPS × 交易所最新本益比——倍數不變、
  讓獲利成長推股價；成長越陡越樂觀。
- 停損參考與支撐／壓力候選（2026-10-30 使用者要求，`risk_levels`）：只替**現價**算，現價
  落在買進區間內才給停損（2026-10-30 使用者改；原本是現價低於成長價）。停損參考＝現價 −
  2×週 ATR14（已收完週、Wilder），**跟支撐分開**、不被大量區改動；距現價 <8% 或 >20% 只提示、
  不改價。倍數由 2015～2026、603 檔、15 萬個買點的 26 週模擬定案：2× 讓「虧 >30%」從 3.5%
  降到 0.4%、2022／2025 空頭最差 5% 少虧約 10 個百分點；2.5×、3× 保護明顯變差，1.5× 半年內
  一半以上會被停掉。這是現價快照，不是持倉的移動停損。
  支撐／壓力候選＝近 250 日「日 K 估計」大量區（典型價分 40 箱、量 ≥ 平均 1.5 倍），價格換算
  到目前基準；現價所在區的下／上緣優先，否則下方／上方最近一區。
- 持股停損（2026-10-30 使用者拍板，`hold_stop`）：現價不在買進區間時改給已持有的人。不知道成本、
  個股查詢也沒有「開始追蹤」的起點，所以**無狀態**：每次直接算近 22 週最高 − 2×週ATR14，週收盤
  跌破上週的線才算。模擬（research/stop_design_2026-10-30/holdsim2.py）：無狀態跟「只上移」差
  <1pp；線上組最差 5% −26%→−13%、虧 >20% 8.7%→1.0%，代價半年內 96% 出場、六成賣後又漲回；
  2.5×／3× 尾端明顯變差。只有「本週剛跌破」是訊號。固定 22 週高會讓 56% 的股票線卡在現價上方
  （2317 盤整 20 週還顯示 273 > 248），所以改混合版：固定線在價格上方時改用跌破後的高點重算，
  原本線上的結果不變、原本沒保護的那群最差 5% −26.7%→−15.2%（holdsim4）。

全部是純函式，吃 `_stock_data()` 的 qf / rev / px / per，回 dict，UI 在 streamlit_app。
"""
from __future__ import annotations

import pandas as pd

PE_YEARS = 5                    # 近 5 個日曆年（含今年到資料日）
PE_MIN_YEAR_DAYS = 20           # 某年有效（per>0）交易日少於這個 → 該年不算（多半是虧損年）
PE_MIN_YEARS = 3                # 有效年數少於這個 → 不給三段價
PE_WIDE_RATIO = 4.0             # 最高年均 > 最低年均 × 這個 → 區間太寬，卡片不列
CYCLE_QUARTERS = 24             # 營益率歷史位置看近 24 季（跟 stockcharts.QUARTERS_LOOKBACK 同尺度）
CYCLE_MIN_QUARTERS = 8
NONOP_WARN_RATIO = 0.20         # |最新季業外| / |最新季稅前| 超過 → 警示
EPS_NEAR_ZERO = 0.05            # |EPS| 小於這個的季不拿來推股數
SENS_REV = (-0.10, 0.0, 0.10)
SENS_GM = (-0.03, 0.0, 0.03)
STOP_WATR_MULT = 2.0            # 停損＝現價 − 2×週 ATR14
WATR_WEEKS = 14
BUY_C = 0.9                     # 買進上緣＝成長價 × 0.9（預估獲利至少比近四季多 11%）
BUY_C_CAUTIOUS = 0.8            # 景氣高峰或業外 >20% 時改 0.8（至少多 25%）
BUY_IN_STATES = ("in", "in_above_fair", "cap_in")  # 現價落在買進區間（或上限）內 → 給停損參考
HOLD_WEEKS = 22                 # 持股停損＝近 22 週最高 − 2×週ATR14（不在買進區間時給已持有的人）
HOLD_WATR_MULT = 2.0
HINT_NEAR = 0.08                # 停損距現價 < 8% → 提示太近（不改價）
HINT_WIDE = 0.20                # 停損距現價 > 20% → 提示太寬（不改價）
VP_DAYS = 250                   # 成交量分布看近 250 個交易日（約一年）
VP_BINS = 40
VP_NODE_RATIO = 1.5             # 某價格箱的量 ≥ 平均 × 這個 → 大量區


def _qlabel(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts.year}Q{(ts.month - 1) // 3 + 1}"


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _quarters(qf: pd.DataFrame) -> pd.DataFrame:
    need = ["period_end", "revenue", "gross_profit", "op_income", "pretax_income",
            "net_income", "eps"]
    if qf is None or qf.empty or any(c not in qf.columns for c in need):
        return pd.DataFrame(columns=need)
    q = qf[need].copy()
    q["period_end"] = pd.to_datetime(q["period_end"])
    for c in need[1:]:
        q[c] = pd.to_numeric(q[c], errors="coerce")
    # 轉換率與股數都要用「歸母」淨利：net_income 是合併淨利（含非控制權益），2317 用它推股數
    # 會多出 15%（2026-10-30 抓到）。ni_parent（損益表歸母淨利）缺值的季才退回 net_income。
    if "ni_parent" in qf.columns:
        q["net_income"] = pd.to_numeric(qf["ni_parent"], errors="coerce").fillna(q["net_income"])
    return (q.dropna(subset=["revenue"]).drop_duplicates("period_end", keep="last")
             .sort_values("period_end").reset_index(drop=True))


def _shares(q: pd.DataFrame) -> float | None:
    t = q.tail(4)
    t = t[(t["eps"].abs() >= EPS_NEAR_ZERO) & t["net_income"].notna()]
    s = (t["net_income"] / t["eps"])
    s = s[s > 0]
    return float(s.median()) if not s.empty else None


def _revenue_block(rev: pd.DataFrame, q: pd.DataFrame) -> dict | None:
    if rev is None or rev.empty or len(rev) < 3:
        return None
    r = rev.sort_values("month").reset_index(drop=True)
    last3 = r.tail(3)
    months = pd.to_datetime(last3["month"]).dt.to_period("M")
    # 中間缺月、重複月份、任一月營收空白 → 不是完整的連續三個月，不湊（sol 審查 2026-10-30）
    if ((months.iloc[-1] - months.iloc[0]).n != 2 or months.nunique() != 3
            or last3["revenue"].isna().any()):
        return None
    m3 = float(last3["revenue"].sum())
    prev = r[pd.to_datetime(r["month"]).dt.to_period("M").isin(months - 12)]
    yoy = (m3 / float(prev["revenue"].sum()) - 1) if len(prev) == 3 and prev["revenue"].sum() > 0 else None
    lq = q.iloc[-1]
    lq_rev = _num(lq["revenue"])
    lq_end = pd.Timestamp(lq["period_end"]).to_period("M")
    return {
        "m3_sum": m3,
        "first_month": months.iloc[0].strftime("%Y/%m"),
        "last_month": months.iloc[-1].strftime("%Y/%m"),
        "yoy": yoy,
        "last_q_rev": lq_rev,
        "vs_last_q": (m3 / lq_rev - 1) if lq_rev else None,
        # 近 3 個月剛好就是最新一季財報期間 → 試算 ≈ 實際，UI 要講
        "same_as_reported_q": months.iloc[-1] == lq_end,
    }


def _pe_block(per: pd.DataFrame, px: pd.DataFrame) -> dict | None:
    """近 5 個日曆年「各年平均本益比」（排除 per≤0 的日子）→ 最低／中間／最高＝三段倍數
    （使用者 2026-10-29 指定）。另給全期日資料的平均 ±1σ（外資 PE band 口徑）當對照。"""
    if per is None or per.empty:
        return None
    p = per[["date", "per"]].copy()
    p["date"] = pd.to_datetime(p["date"])
    p["per"] = pd.to_numeric(p["per"], errors="coerce")
    y0 = int(p["date"].max().year) - (PE_YEARS - 1)
    p = p[(p["date"].dt.year >= y0) & (p["per"] > 0)]
    g = p.groupby(p["date"].dt.year)["per"].agg(["mean", "size"])
    g = g[g["size"] >= PE_MIN_YEAR_DAYS]
    if len(g) < PE_MIN_YEARS:
        return None
    m = g["mean"]
    days = p[p["date"].dt.year.isin(g.index)]["per"]
    low, high = float(m.min()), float(m.max())
    return {"years": [{"year": int(y), "pe": float(v), "days": int(n)}
                      for y, v, n in zip(g.index, g["mean"], g["size"])],
            "low": low, "mid": float(m.median()), "high": high,
            "mean": float(days.mean()), "sd": float(days.std()),
            "wide": high > low * PE_WIDE_RATIO}


def _cycle_block(q: pd.DataFrame) -> dict | None:
    t = q.tail(CYCLE_QUARTERS)
    t = t[t["revenue"] > 0]
    om = (t["op_income"] / t["revenue"]).dropna()
    if len(om) < CYCLE_MIN_QUARTERS:
        return None
    cur = float(om.iloc[-1])
    return {"current": cur, "min": float(om.min()), "max": float(om.max()),
            "n": int(len(om)), "pct": float((om < cur).mean())}


def _year_block(q: pd.DataFrame, year: int, run_q_eps: float | None) -> dict | None:
    """今年預估 EPS ＝ 今年已公布季的實際 EPS ＋ 未公布季數 × 試算單季 EPS（排除業外）。
    使用者 Excel 是「已公布累計 × 4/n」；這裡改用近 3 月營收的速度補未公布的季。
    去年 4 季不齊 → 不給成長率；試算單季 EPS 推不出來且今年還有季沒公布 → None。"""
    yr = q[q["period_end"].dt.year == year]
    ly = q[q["period_end"].dt.year == year - 1]
    n = int(len(yr))
    if n < 4 and run_q_eps is None:
        return None
    if yr["eps"].isna().any():
        return None
    est = float(yr["eps"].sum()) + (4 - n) * (run_q_eps or 0.0)
    last = float(ly["eps"].sum()) if len(ly) == 4 and ly["eps"].notna().all() else None
    return {"year": year, "reported_q": n, "reported_eps": float(yr["eps"].sum()),
            "est": est, "last": last,
            "growth": (est / last - 1) if (last and last > 0) else None}


def _current_pe(per: pd.DataFrame) -> dict | None:
    """交易所公布的最新 trailing PER（>0 才算）；使用者 Excel 的「成長價」用這個倍數。"""
    if per is None or per.empty:
        return None
    p = per[["date", "per"]].copy()
    p["per"] = pd.to_numeric(p["per"], errors="coerce")
    # 不先 dropna：最新一天交易所 PER 空白（虧損時顯示「-」）就該不給，不能退回舊的正值
    p = p.dropna(subset=["date"]).sort_values("date")
    v = p["per"].iloc[-1] if not p.empty else None
    if v is None or pd.isna(v) or not float(v) > 0:
        return None
    return {"pe": float(p["per"].iloc[-1]),
            "date": pd.Timestamp(p["date"].iloc[-1]).strftime("%Y/%m/%d")}


def _weekly_bars(px: pd.DataFrame) -> pd.DataFrame | None:
    """已收完的週 K（週五收）[high, low, close]。最後一天不是週五 → 該週還沒收完，丟掉
    （週五休市時會少算一週，可接受）。px＝[date, high, low, close]。"""
    if px is None or px.empty or not {"date", "high", "low", "close"} <= set(px.columns):
        return None
    d = px[["date", "high", "low", "close"]].copy()
    d["date"] = pd.to_datetime(d["date"])
    for c in ("high", "low", "close"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna().set_index("date").sort_index()
    if d.empty:
        return None
    w = d.resample("W-FRI").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    if d.index[-1].weekday() != 4:
        w = w.iloc[:-1]
    return w


def _watr_series(w: pd.DataFrame, weeks: int = WATR_WEEKS) -> pd.Series:
    """每週的 Wilder ATR（前 weeks 個 TR 平均起算、之後遞迴）；算不出的週＝NaN。"""
    pc = w["close"].shift()
    tr = pd.concat([w["high"] - w["low"], (w["high"] - pc).abs(), (w["low"] - pc).abs()],
                   axis=1).max(axis=1)
    out = pd.Series(float("nan"), index=w.index)
    if len(w) < weeks + 1:
        return out
    a = float(tr.iloc[1:weeks + 1].mean())
    out.iloc[weeks] = a
    for i in range(weeks + 1, len(w)):
        a = (a * (weeks - 1) + float(tr.iloc[i])) / weeks
        out.iloc[i] = a
    return out


def weekly_atr(px: pd.DataFrame, weeks: int = WATR_WEEKS) -> float | None:
    """已收完週 K 的 Wilder ATR（最新一週）。週數不足 → None。px＝[date, high, low, close]。"""
    w = _weekly_bars(px)
    if w is None or len(w) < weeks + 1:
        return None
    a = float(_watr_series(w, weeks).iloc[-1])
    return a if a > 0 else None


def hold_stop(px: pd.DataFrame) -> dict | None:
    """持股停損（給已持有、成本未知的人；不存使用者狀態，全由價格歷史推出）。混合版
    （2026-10-30 使用者拍板，sol 建議、research/stop_design_2026-10-30/holdsim4.py 模擬）：
      固定線 F_q＝近 22 週最高 − 2×週ATR14；
      重算線 R_q＝max(週高[max(b, q−21)..q]) − 2×週ATR14，b＝最近一次「週收盤 < R_{q−1}」的週；
      採用線 L_q＝F_q（F_q < 該週收盤）否則 R_q——固定線還在價格下方就用固定線（原本線上的
      結果完全不變），固定線跑到價格上方（舊高點卡住）才改用跌破後的高點重算。
    第 q 週收盤 < L_{q−1} ＝「跌破」→ 下週一處理；已觸發的跌破不會被新線取消。
    回 `{"line", "hh", "since", "watr", "price", "dist", "state", "reset", "brk_line",
    "brk_date", "under_now"}`：
      line＝最新已收完週的 L（下一次週收盤拿它比）；hh／since＝算這條線用的最高價與起算週
      （since＝None 表示就是近 22 週）；dist＝line/現價−1；
      state＝"new"（最近一週收盤剛跌破 brk_line）／"above"（線在現價下方）／
      "na"（線仍高於最近已收完週的收盤：暫無可用參考線）；
      reset＝線是跌破後重算的；brk_line／brk_date＝最近一次跌破的那條線與那週（22 週內，沒有＝None）；
      under_now＝日收盤已低於線、還沒週收盤確認。週數不足、線 ≤ 0 → None。"""
    w = _weekly_bars(px)
    if w is None or len(w) < max(HOLD_WEEKS, WATR_WEEKS + 1) + 1:
        return None
    atr = _watr_series(w).to_numpy()
    hi, cl = w["high"].to_numpy(), w["close"].to_numpy()
    n = len(w)
    fixed = w["high"].rolling(HOLD_WEEKS).max().to_numpy() - HOLD_WATR_MULT * atr
    re = [float("nan")] * n
    re_lo = [0] * n
    b = 0
    for q in range(n):
        if q >= 1 and re[q - 1] > 0 and cl[q] < re[q - 1]:
            b = q                                         # 本週收盤跌破重算線 → 從本週重新起算
        lo = max(b, q - HOLD_WEEKS + 1)
        re_lo[q] = lo
        if q >= HOLD_WEEKS - 1 and atr[q] == atr[q]:      # atr 非 NaN
            re[q] = float(hi[lo:q + 1].max()) - HOLD_WATR_MULT * float(atr[q])
    use_fixed = [bool(fixed[q] < cl[q]) for q in range(n)]   # NaN 比較為 False
    line = [float(fixed[q]) if use_fixed[q] else re[q] for q in range(n)]
    if not line[-1] > 0:
        return None
    brk = next((q for q in range(n - 1, max(n - HOLD_WEEKS - 1, 0), -1)   # 最近 22 週
                if line[q - 1] > 0 and cl[q] < line[q - 1]), None)
    p = px.sort_values("date")
    price = _num(p.iloc[-1]["close"])
    if price is None or price <= 0:
        return None
    lv = line[-1]
    if brk == n - 1:
        state = "new"
    elif cl[-1] < lv:
        state = "na"
    else:
        state = "above"
    reset = not use_fixed[-1]
    since = w.index[re_lo[-1]] if reset and re_lo[-1] > n - HOLD_WEEKS else None
    hh = float(hi[re_lo[-1]:].max()) if reset else float(hi[-HOLD_WEEKS:].max())
    return {"line": lv, "hh": hh, "since": None if since is None else since.strftime("%m/%d"),
            "watr": float(atr[-1]), "price": price, "dist": lv / price - 1,
            "state": state, "reset": reset,
            "brk_line": None if brk is None else line[brk - 1],
            "brk_date": None if brk is None else w.index[brk].strftime("%m/%d"),
            "under_now": bool(state == "above" and price < lv)}


def volume_zones(px: pd.DataFrame, days: int = VP_DAYS, bins: int = VP_BINS,
                 ratio: float = VP_NODE_RATIO) -> list[dict]:
    """日 K 估計的大量區：近 days 日，典型價 (H+L+C)/3 分 bins 箱、整天量歸到該箱（不是實際
    分價成交），量 ≥ 平均×ratio 的相鄰箱併成一區；中間只隔一箱、且那箱量 ≥ 平均的兩區再合併。
    回 `[{"lo", "hi", "share"}]`（share＝區內所有箱、含橋接箱的量占全期），由低到高。
    還原價＝換算到目前價格基準。資料不足 60 日 → []。"""
    need = {"date", "high", "low", "close", "volume"}
    if px is None or px.empty or not need <= set(px.columns):
        return []
    d = px[list(need)].copy()
    for c in ("high", "low", "close", "volume"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.sort_values("date").tail(days).dropna()      # 先取近 days 日再丟缺值，不往前補舊資料
    d = d[d["volume"] > 0]
    if len(d) < 60:
        return []
    lo, hi = float(d["low"].min()), float(d["high"].max())
    if not hi > lo:
        return []
    tp = (d["high"] + d["low"] + d["close"]) / 3
    width = (hi - lo) / bins
    idx = ((tp - lo) / width).astype(int).clip(0, bins - 1)
    vol = d["volume"].groupby(idx).sum().reindex(range(bins), fill_value=0.0)
    total, mean = float(vol.sum()), float(vol.mean())
    hot = (vol >= mean * ratio).to_numpy()
    spans, start = [], None                          # [起箱, 迄箱)
    for i in range(bins + 1):
        if i < bins and hot[i]:
            start = i if start is None else start
        elif start is not None:
            spans.append([start, i])
            start = None
    merged: list[list[int]] = []
    for s, e in spans:
        if merged and s - merged[-1][1] == 1 and vol.iloc[merged[-1][1]] >= mean:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [{"lo": lo + s * width, "hi": lo + e * width,
             "share": float(vol.iloc[s:e].sum()) / total} for s, e in merged]


def risk_levels(px: pd.DataFrame) -> dict | None:
    """現價快照的停損參考＋支撐／壓力候選。停損與支撐分開：停損只看波動，不被大量區改動
    （2026-10-30 使用者＋sol／DeepSeek 討論、2015～2026 模擬定案）。週 ATR 算不出來 → None。
    回 `{"watr", "price", "stop", "risk", "hint", "support", "sup_px", "sup_far", "at",
    "resist", "res_px", "high", "days"}`：
      stop＝現價 − 2×週ATR（≤0 → None）；hint＝距離 <8%／>20% 的提示（不改價）；
      support＝現價所在區，不在區內就是下方最近一區；sup_px＝所在區下緣／下方區上緣；
      sup_far＝支撐在停損參考之下（離太遠，不是近端支撐）；
      res_px＝所在區上緣，不在區內就是上方最近一區下緣；沒有 → None（另給近一年高 high）。"""
    watr = weekly_atr(px)
    if watr is None:
        return None
    p = px.sort_values("date")
    price = _num(p.iloc[-1]["close"])
    if price is None or price <= 0:
        return None
    zones = volume_zones(px)
    at = next((z for z in zones if z["lo"] <= price <= z["hi"]), None)
    below = [z for z in zones if z["hi"] < price]
    above = [z for z in zones if z["lo"] > price]
    stop = price - STOP_WATR_MULT * watr
    stop = stop if stop > 0 else None
    risk = (stop / price - 1) if stop else None
    hint = None
    if risk is not None and risk > -HINT_NEAR:
        hint = f"距現價不到 {HINT_NEAR:.0%}，正常波動就可能碰到"
    elif risk is not None and risk < -HINT_WIDE:
        hint = f"距現價超過 {HINT_WIDE:.0%}：這檔波動大，停損本來就寬，可用較小部位"
    support = at if at is not None else (below[-1] if below else None)
    sup_px = None if support is None else (support["lo"] if support is at else support["hi"])
    if at is not None and at["hi"] > price:
        res_zone, res_px = at, at["hi"]
    elif above:
        res_zone, res_px = above[0], above[0]["lo"]
    else:
        res_zone, res_px = None, None
    high = float(pd.to_numeric(p.tail(VP_DAYS)["high"], errors="coerce").max())
    return {"watr": watr, "price": price, "stop": stop, "risk": risk, "hint": hint,
            "support": support, "sup_px": sup_px,
            "sup_far": bool(sup_px is not None and stop is not None and sup_px < stop),
            "at": at, "resist": res_zone, "res_px": res_px, "high": high,
            "days": int(min(len(p), VP_DAYS))}


def buy_range(price: float | None, fair: float | None, growth: float | None,
              cycle_peak: bool = False, nonop_high: bool = False) -> dict | None:
    """買進區間（2026-10-30 使用者定義、sol／DeepSeek／Sonnet 討論後採 Claude 建議）：
    上緣 U＝成長價 × c；c＝0.9，最新季營益率在近 24 季前 20%（景氣高峰）或業外占稅前 >20%
    任一成立改 0.8（不疊加）——這兩種情況試算 EPS 容易偏高。三段價太寬不影響 c（只影響合理價）。
    下緣 L＝合理價；現價已低於合理價就用現價。成長價 ≈ 現價 × 預估EPS ÷ 近四季EPS，所以
    「現價 ≤ U」⇔ 預估 EPS 至少比近四季多 1/c − 1（11%／25%）：這是**成長門檻**，不是估值折價，
    而且 U 會跟著現價移動，不是固定的等待買點。
    成長價或現價算不出來 → None。回 `{"c", "why", "min_growth", "lo", "hi", "fair", "impl", "state"}`
    （impl＝成長價/現價−1 ≈ 預估獲利成長；現價 ≤ U ⇔ impl ≥ min_growth）：
      state＝"in"（現價 ≤ 合理價，區間 現價～U）／"in_above_fair"（合理價 < 現價 ≤ U）／
      "above"（現價 > U、合理價 ≤ U）／"none"（U < 合理價且現價 > U：區間不成立）／
      "cap_in"／"cap_above"（沒有合理價，只有上限；現價 ≤／> U）。"""
    if not price or not growth or price <= 0 or growth <= 0:
        return None
    why = [w for w, on in (("營益率在歷史高峰", cycle_peak), ("業外占稅前 >20%", nonop_high)) if on]
    c = BUY_C_CAUTIOUS if why else BUY_C
    hi = c * growth
    out = {"c": c, "why": why, "min_growth": 1 / c - 1, "hi": hi, "fair": fair, "lo": None,
           "impl": growth / price - 1}
    if fair is None or fair <= 0:
        out["state"] = "cap_in" if price <= hi else "cap_above"
        out["fair"] = None
        return out
    lo = min(price, fair)
    out["lo"] = lo
    if price <= hi:
        out["state"] = "in" if price <= fair else "in_above_fair"
    else:
        out["state"] = "above" if fair <= hi else "none"
    return out


def estimate(qf: pd.DataFrame, rev: pd.DataFrame, px: pd.DataFrame,
             per: pd.DataFrame) -> dict:
    """回 `{"ok": bool, "reason": str|None, ...}`。

    ok=False 只在連營收試算都做不出來時（財報 <4 季、無毛利欄＝金融業等、月營收不足
    3 個連續月）。EPS／本益比算不出來（股數推不出、試算 EPS ≤ 0、PE 樣本不足）時
    ok 仍為 True，對應欄位為 None，UI 就地說明。
    """
    q = _quarters(qf)
    if len(q) < 4:
        return {"ok": False, "reason": "財報不足 4 季，不做試算。"}
    lq = q.iloc[-1]
    if _num(lq["gross_profit"]) is None or _num(lq["op_income"]) is None \
            or _num(lq["pretax_income"]) is None:
        return {"ok": False, "reason": "最新一季沒有毛利／營業利益／稅前欄位（金融業等），"
                                       "這套「營收→毛利→EPS」試算不適用。"}
    rv = _revenue_block(rev, q)
    if rv is None:
        return {"ok": False, "reason": "月營收不足連續 3 個月，不做試算。"}

    warns: list[str] = []
    infos: list[str] = []
    last8 = q.tail(8).copy()
    last8["nonop"] = last8["pretax_income"] - last8["op_income"]
    gm = float(lq["gross_profit"]) / float(lq["revenue"]) if lq["revenue"] else None
    opex = float(lq["gross_profit"]) - float(lq["op_income"])
    opex_ratio = opex / float(lq["revenue"]) if lq["revenue"] else None
    nonop_latest = float(lq["pretax_income"]) - float(lq["op_income"])
    nonop_avg4 = float(last8["nonop"].tail(4).mean())
    lq_pretax = float(lq["pretax_income"])
    if lq_pretax != 0 and abs(nonop_latest) / abs(lq_pretax) > NONOP_WARN_RATIO:
        warns.append(
            f"最新一季業外占稅前 {nonop_latest / abs(lq_pretax):+.0%}"
            f"（近 {len(last8)} 季業外 {last8['nonop'].min() / 1e8:+.2f}～"
            f"{last8['nonop'].max() / 1e8:+.2f} 億），主試算已排除業外。")

    t4 = q.tail(4)
    # 缺一季就不湊：四季都要有稅前／淨利，且首尾正好相隔三季（中間沒漏季）
    span = (t4["period_end"].iloc[-1].to_period("Q") - t4["period_end"].iloc[0].to_period("Q")).n
    t4ok = bool(t4[["pretax_income", "net_income"]].notna().all(axis=1).all() and span == 3)
    ttm_pretax, ttm_net = float(t4["pretax_income"].sum()), float(t4["net_income"].sum())
    conv = ttm_net / ttm_pretax if (t4ok and ttm_pretax > 0) else None
    if conv is None:
        warns.append("近 4 季稅前合計 ≤ 0 或有季缺稅前／淨利，推不出「歸母淨利 ÷ 稅前」轉換率，不試算 EPS。")
    elif not 0.6 <= conv <= 1.0:
        warns.append(f"近 4 季歸母淨利 ÷ 稅前 = {conv:.0%}，偏離一般稅負範圍"
                     "（非控制權益、遞延稅、虧損扣抵…），EPS 試算受影響。")
    shares = _shares(q)
    if shares is None and conv is not None:
        warns.append("近 4 季 EPS 都接近 0，推不出股數，不試算 EPS。")

    def _run_eps(rev_q: float, gm_: float, nonop: float = 0.0) -> float | None:
        if conv is None or shares is None or gm_ is None:
            return None
        if opex_ratio is None:
            return None
        # 營業費用＝最新季費用率 × 試算營收（2026-10-29 使用者拍板，取代固定金額）
        return (rev_q * (gm_ - opex_ratio) + nonop) * conv / shares * 4

    m3 = rv["m3_sum"]
    run_ex = _run_eps(m3, gm)
    run_incl = _run_eps(m3, gm, nonop_avg4)
    # 對照：營業費用固定為最新季金額（營收升時偏樂觀）
    run_fixed_opex = ((m3 * gm - opex) * conv / shares * 4
                      if (conv is not None and shares is not None and gm is not None) else None)
    ttm_eps = float(t4["eps"].sum()) if t4["eps"].notna().all() else None

    sens = None
    if run_ex is not None:
        sens = {"rev": list(SENS_REV), "gm": list(SENS_GM),
                "eps": [[_run_eps(m3 * (1 + dr), gm + dg) for dg in SENS_GM] for dr in SENS_REV]}

    price = px_date = None
    if px is not None and not px.empty:
        last = px.sort_values("date").iloc[-1]
        price, px_date = _num(last["close"]), pd.Timestamp(last["date"]).strftime("%Y/%m/%d")
    pe = _pe_block(per, px)
    implied_pe = price / run_ex if (price and run_ex and run_ex > 0) else None
    yb = _year_block(q, int(rv["last_month"][:4]), run_ex / 4 if run_ex is not None else None)
    est_eps = yb["est"] if yb else None
    # 三段價（便宜/合理/昂貴）＝ 近 5 年各年平均 PE 最低/中間/最高 × 今年預估 EPS
    band = None
    if pe and est_eps and est_eps > 0:
        band = {k: pe[k] * est_eps for k in ("low", "mid", "high")}
    # 成長價（使用者 Excel 口徑）＝ 今年預估 EPS × 目前本益比：倍數不變、讓獲利成長推股價
    cur_pe = _current_pe(per)
    growth_price = cur_pe["pe"] * est_eps if (cur_pe and est_eps and est_eps > 0) else None
    if pe and pe["wide"]:
        warns.append(f"近 5 年各年平均本益比差很大（{pe['low']:.0f}～{pe['high']:.0f} 倍），"
                     "多半是過去獲利很薄時本益比被撐高；歷史倍數參考性低。")

    risk = risk_levels(px) if (px is not None and not px.empty) else None

    cyc = _cycle_block(q)
    if cyc and cyc["pct"] >= 0.8:
        infos.append(f"最新一季營益率 {cyc['current']:.1%}，在近 {cyc['n']} 季裡贏過 "
                     f"{cyc['pct']:.0%} 的季（區間 {cyc['min']:.1%}～{cyc['max']:.1%}）。"
                     "景氣循環股在獲利高峰時，市場給的本益比通常偏低。")
    nonop_hi = bool(lq_pretax != 0 and abs(nonop_latest) / abs(lq_pretax) > NONOP_WARN_RATIO)
    buy = buy_range(price, band["mid"] if (band and not (pe and pe["wide"])) else None,
                    growth_price, cycle_peak=bool(cyc and cyc["pct"] >= 0.8), nonop_high=nonop_hi)
    # 停損參考只在現價落在買進區間內才給（使用者 2026-10-30 改：原本是現價 < 成長價）
    if risk is not None:
        risk["buyable"] = bool(buy and buy["state"] in BUY_IN_STATES)
        risk["no_growth"] = growth_price is None          # 畫面要分「沒有成長價」與「不在買進區間」
        risk["hold"] = None if risk["buyable"] else hold_stop(px)
    if rv["same_as_reported_q"]:
        infos.append("近 3 個月就是最新一季財報期間：試算只是把已公布的那一季換算，不是新資訊。")

    return {
        "ok": True, "reason": None,
        "asof": {"fin_q": _qlabel(lq["period_end"]), "rev_month": rv["last_month"],
                 "px_date": px_date},
        "rev": rv,
        "inputs": {"gm": gm, "opex": opex, "opex_ratio": opex_ratio,
                   "opex_est": m3 * opex_ratio if opex_ratio is not None else None,
                   "run_fixed_opex": run_fixed_opex, "nonop_latest": nonop_latest,
                   "nonop_avg4": nonop_avg4, "conv": conv, "shares": shares},
        "nonop_hist": [{"q": _qlabel(r.period_end), "nonop": float(r.nonop),
                        "pretax": float(r.pretax_income)} for r in last8.itertuples()],
        "eps": {"ttm": ttm_eps, "run_ex": run_ex, "run_incl": run_incl},
        "year": yb, "cur_pe": cur_pe, "growth_price": growth_price, "risk": risk,
        "buy": buy,
        "price": price, "implied_pe": implied_pe, "pe": pe, "band": band,
        "sens": sens, "cycle": cyc, "warns": warns, "infos": infos,
    }
