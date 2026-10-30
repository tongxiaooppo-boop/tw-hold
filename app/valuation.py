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
- 停損參考與大量區（2026-10-30 使用者要求，`risk_levels`）：只替**現價**算，且現價要低於
  成長價才給（使用者 2026-10-30：「需在成長價下，不一定是合理價下」）。
  停損＝現價 − 2×週 ATR14；下方若有大量支撐區，改用「支撐區下緣 − 0.5 週 ATR」（離現價要 ≥ 1 週 ATR）
  （跌破支撐＝買進理由失效，比較早出場）。大量區＝近 250 日成交量分布（典型價分箱）裡量
  ≥ 平均 1.5 倍的連續價格帶；現價上方最近一塊＝壓力區（減碼參考）。日線 2×ATR 只有
  5～8%，長抱型股票正常拉回就被洗掉，所以用週線。只是參考，沒有回測。

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
SUPPORT_BUFFER_WATR = 0.5       # 支撐停損＝支撐區下緣 − 0.5 週 ATR
SUPPORT_MIN_WATR = 1.0          # 支撐區下緣離現價不到 1 週 ATR → 太近，不拿來當停損
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
    if (months.iloc[-1] - months.iloc[0]).n != 2:      # 中間缺月 → 不是連續三個月，不湊
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
    if p.empty or not p["per"].iloc[-1] > 0:
        return None
    return {"pe": float(p["per"].iloc[-1]),
            "date": pd.Timestamp(p["date"].iloc[-1]).strftime("%Y/%m/%d")}


def weekly_atr(px: pd.DataFrame, weeks: int = WATR_WEEKS) -> float | None:
    """週 K（週五收）的 Wilder ATR。週數不足 weeks+1 → None。px＝[date, high, low, close]。"""
    if px is None or px.empty or not {"date", "high", "low", "close"} <= set(px.columns):
        return None
    d = px[["date", "high", "low", "close"]].copy()
    d["date"] = pd.to_datetime(d["date"])
    for c in ("high", "low", "close"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    w = (d.dropna().set_index("date").sort_index()
          .resample("W-FRI").agg({"high": "max", "low": "min", "close": "last"}).dropna())
    if len(w) < weeks + 1:
        return None
    pc = w["close"].shift()
    tr = pd.concat([w["high"] - w["low"], (w["high"] - pc).abs(), (w["low"] - pc).abs()],
                   axis=1).max(axis=1).iloc[1:]
    v = float(tr.ewm(alpha=1 / weeks, adjust=False).mean().iloc[-1])
    return v if v > 0 else None


def volume_zones(px: pd.DataFrame, days: int = VP_DAYS, bins: int = VP_BINS,
                 ratio: float = VP_NODE_RATIO) -> list[dict]:
    """近 days 日成交量分布：典型價 (H+L+C)/3 分 bins 箱，量 ≥ 平均×ratio 的相鄰箱併成一區。
    回 `[{"lo", "hi", "share"}]`（share＝該區量占全期），由低到高。資料不足 60 日 → []。"""
    need = {"date", "high", "low", "close", "volume"}
    if px is None or px.empty or not need <= set(px.columns):
        return []
    d = px[list(need)].copy()
    for c in ("high", "low", "close", "volume"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna().sort_values("date").tail(days)
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
    total = float(vol.sum())
    hot = vol >= vol.mean() * ratio
    zones, start = [], None
    for i in range(bins + 1):
        if i < bins and hot.iloc[i]:
            start = i if start is None else start
        elif start is not None:
            zones.append({"lo": lo + start * width, "hi": lo + i * width,
                          "share": float(vol.iloc[start:i].sum()) / total})
            start = None
    return zones


def risk_levels(px: pd.DataFrame) -> dict | None:
    """現價的停損參考＋上下最近的大量區。週 ATR 算不出來 → None。
    回 `{"watr", "price", "stop", "risk", "by", "anchor", "mult", "support", "resist", "at"}`；
    stop＝anchor − mult×watr（anchor＝現價或支撐區下緣，畫面拿來顯示算式）；
    by＝"watr"（現價 − 2×週 ATR）或 "support"（支撐區下緣 − 0.5 週 ATR）；support＝現價下方最近一塊
    （hi < 現價）、resist＝上方最近（lo > 現價）、at＝現價所在的區（沒有就 None）。"""
    watr = weekly_atr(px)
    price = _num(px.sort_values("date").iloc[-1]["close"]) if watr is not None else None
    if watr is None or price is None or price <= 0:
        return None
    zones = volume_zones(px)
    below = [z for z in zones if z["hi"] < price]
    above = [z for z in zones if z["lo"] > price]
    at = next((z for z in zones if z["lo"] <= price <= z["hi"]), None)
    stop, by = price - STOP_WATR_MULT * watr, "watr"
    # 支撐區下緣再留 0.5 週 ATR（防下影線洗掉）；離現價不到 1 週 ATR 的不用（太近）
    anchor = price
    los = [z["lo"] for z in zones
           if z["lo"] - SUPPORT_BUFFER_WATR * watr <= price - SUPPORT_MIN_WATR * watr]
    if los and max(los) - SUPPORT_BUFFER_WATR * watr > stop:
        anchor = max(los)
        stop, by = anchor - SUPPORT_BUFFER_WATR * watr, "support"
    stop = stop if stop > 0 else None
    return {"watr": watr, "price": price, "stop": stop,
            "risk": (stop / price - 1) if stop else None, "by": by,
            "anchor": anchor, "mult": SUPPORT_BUFFER_WATR if by == "support" else STOP_WATR_MULT,
            "support": below[-1] if below else None, "resist": above[0] if above else None,
            "at": at}


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
    t4ok = t4[["pretax_income", "net_income"]].notna().all(axis=1).all()   # 缺一季就不湊
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

    # 停損只替現價算，且現價要低於成長價才給（使用者 2026-10-30：不必低於合理價）
    risk = risk_levels(px) if (px is not None and not px.empty) else None
    if risk is not None:
        risk["buyable"] = bool(price and growth_price and price < growth_price)

    cyc = _cycle_block(q)
    if cyc and cyc["pct"] >= 0.8:
        infos.append(f"最新一季營益率 {cyc['current']:.1%}，在近 {cyc['n']} 季裡贏過 "
                     f"{cyc['pct']:.0%} 的季（區間 {cyc['min']:.1%}～{cyc['max']:.1%}）。"
                     "景氣循環股在獲利高峰時，市場給的本益比通常偏低。")
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
        "price": price, "implied_pe": implied_pe, "pe": pe, "band": band,
        "sens": sens, "cycle": cyc, "warns": warns, "infos": infos,
    }
