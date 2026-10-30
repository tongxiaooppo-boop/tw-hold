"""個股查詢「估值速覽」試算（合成資料，預期值手算）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import app.valuation as va

SHARES = 5e8


def _qf(n: int = 8, nonop: float = 0.0, last_nonop: float | None = None,
        gp_nan: bool = False, last_opex: float | None = None) -> pd.DataFrame:
    """每季營收 25 億、毛利率 40%、營業費用 3 億（費用率 12%）、稅後轉換率 80%、股數 5 億。"""
    pe = pd.date_range("2024-09-30", periods=n, freq="QE")
    rows = []
    for i, p in enumerate(pe):
        no = last_nonop if (last_nonop is not None and i == n - 1) else nonop
        rev, gp = 2.5e9, 1.0e9
        op = gp - (last_opex if (last_opex is not None and i == n - 1) else 3e8)
        pretax = op + no
        net = pretax * 0.8
        rows.append({"period_end": p, "revenue": rev, "gross_profit": np.nan if gp_nan else gp,
                     "op_income": op, "pretax_income": pretax, "net_income": net,
                     "eps": round(net / SHARES, 2)})
    return pd.DataFrame(rows)


def _rev(last: str = "2026-09", n: int = 15, val: float = 1e9, gap: bool = False):
    months = pd.period_range(end=last, periods=n, freq="M").to_timestamp()
    d = pd.DataFrame({"month": months, "revenue": val})
    d.loc[d.index[:-3], "revenue"] = val / 2          # 去年同期一半 → YoY +100%
    if gap:
        d = d.drop(d.index[-2])
    return d.reset_index(drop=True)


def _px(price: float = 100.0):
    return pd.DataFrame({"date": [pd.Timestamp("2026-10-22")], "close": [price]})


def _per(n: int = 1400, lo: float = 12, hi: float = 12):
    """預設 2021 起每天 PE 12 倍（涵蓋近 5 個日曆年）；lo≠hi → 逐日線性變化。"""
    d = pd.date_range(end="2026-10-22", periods=n, freq="B")
    return pd.DataFrame({"date": d, "per": np.linspace(lo, hi, n)})


def test_基本試算_手算對得上():
    r = va.estimate(_qf(), _rev(), _px(), _per())
    assert r["ok"]
    # 近 3 月 30 億 × (40% − 費用率 12%) = 8.4 億 → × 0.8 = 6.72 億 ÷ 5 億股 = 1.344 → × 4
    assert r["rev"]["m3_sum"] == pytest.approx(3e9)
    assert r["rev"]["vs_last_q"] == pytest.approx(0.2)
    assert r["rev"]["yoy"] == pytest.approx(1.0)
    assert r["inputs"]["conv"] == pytest.approx(0.8)
    assert r["inputs"]["shares"] == pytest.approx(SHARES, rel=0.01)
    assert r["eps"]["run_ex"] == pytest.approx(5.376, rel=0.01)
    assert r["implied_pe"] == pytest.approx(100 / 5.376, rel=0.01)
    assert r["pe"]["mid"] == pytest.approx(12, rel=0.01)
    assert [y["year"] for y in r["pe"]["years"]] == [2022, 2023, 2024, 2025, 2026]
    # 今年（2026）已公布 Q1、Q2 各 1.12 ＋ 未公布 2 季 × 1.344 = 4.928；去年 4 × 1.12 = 4.48
    y = r["year"]
    assert y["reported_q"] == 2 and y["est"] == pytest.approx(4.928, rel=0.01)
    assert y["growth"] == pytest.approx(4.928 / 4.48 - 1, rel=0.02)
    assert r["band"]["mid"] == pytest.approx(12 * 4.928, rel=0.02)
    # 成長價 ＝ 預估 EPS × 最新本益比（12）
    assert r["growth_price"] == pytest.approx(12 * 4.928, rel=0.02)
    assert r["warns"] == []


def test_今年四季都公布_預估就是實際():
    r = va.estimate(_qf(n=10), _rev(), _px(), _per())   # 2024Q3..2026Q4
    assert r["year"]["reported_q"] == 4
    assert r["year"]["est"] == pytest.approx(4 * 1.12, rel=0.01)


def test_敏感度矩陣中間格等於主試算():
    r = va.estimate(_qf(), _rev(), _px(), _per())
    s = r["sens"]["eps"]
    assert s[1][1] == pytest.approx(r["eps"]["run_ex"])
    assert s[0][0] < s[1][1] < s[2][2]


def test_大額業外_警示且只進對照版():
    r = va.estimate(_qf(nonop=1e8, last_nonop=6e8), _rev(), _px(), _per())
    assert any("業外" in w for w in r["warns"])
    assert r["inputs"]["nonop_avg4"] == pytest.approx((3 * 1e8 + 6e8) / 4)
    assert r["eps"]["run_incl"] > r["eps"]["run_ex"]


def test_金融業_無毛利_不試算():
    r = va.estimate(_qf(gp_nan=True), _rev(), _px(), _per())
    assert not r["ok"] and "金融" in r["reason"]


def test_財報不足四季():
    r = va.estimate(_qf(n=3), _rev(), _px(), _per())
    assert not r["ok"]


def test_月營收中間缺月_不湊():
    r = va.estimate(_qf(), _rev(gap=True), _px(), _per())
    assert not r["ok"] and "月營收" in r["reason"]


def test_近三月就是最新一季財報期間():
    r = va.estimate(_qf(), _rev(last="2026-06"), _px(), _per())
    assert r["rev"]["same_as_reported_q"]
    assert any("最新一季財報期間" in i for i in r["infos"])


def test_試算虧損_不給本益比與價格區間():
    # 最新季費用率 44% > 毛利率 40% → 試算單季虧損（近 4 季稅前合計仍為正）
    r = va.estimate(_qf(last_opex=1.1e9), _rev(), _px(), _per())
    assert r["ok"] and r["eps"]["run_ex"] < 0
    assert r["implied_pe"] is None
    # 今年預估 ＝ 已公布實際 ＋ 負的試算季 → 比已公布的少；三段價只在預估 > 0 時給
    y = r["year"]
    assert y["est"] < y["reported_eps"]
    assert (r["band"] is None) == (y["est"] <= 0)


def test_本益比樣本不足():
    r = va.estimate(_qf(), _rev(), _px(), _per(n=50))
    assert r["pe"] is None and r["band"] is None and r["implied_pe"] is not None


def test_本益比區間太寬_警示():
    d = pd.date_range("2022-01-03", "2026-10-22", freq="B")
    pe = d.year.map({2022: 5, 2023: 8, 2024: 12, 2025: 20, 2026: 30}).astype(float)
    r = va.estimate(_qf(), _rev(), _px(), pd.DataFrame({"date": d, "per": pe}))
    assert any("各年平均本益比差很大" in w for w in r["warns"])
    assert r["pe"]["wide"] and r["band"] is not None      # 卡片不列、展開照列
    assert not va.estimate(_qf(), _rev(), _px(), _per())["pe"]["wide"]


def test_股數跳過EPS近零的季():
    q = _qf()
    q.loc[q.index[-2], "eps"] = 0.01                  # 這季淨利/EPS 會推出離譜股數
    r = va.estimate(q, _rev(), _px(), _per())
    assert r["inputs"]["shares"] == pytest.approx(SHARES, rel=0.01)


def test_三段價_各年平均本益比的最低中間最高():
    d = pd.date_range("2022-01-03", "2026-10-22", freq="B")
    pe = d.year.map({2022: 8, 2023: 10, 2024: 12, 2025: 14, 2026: 20}).astype(float)
    r = va.estimate(_qf(), _rev(), _px(), pd.DataFrame({"date": d, "per": pe}))
    assert (r["pe"]["low"], r["pe"]["mid"], r["pe"]["high"]) == (8, 12, 20)
    assert r["band"]["low"] == pytest.approx(8 * 4.928, rel=0.01)
    assert not r["pe"]["wide"]


def test_虧損年不算進三段價():
    d = pd.date_range("2022-01-03", "2026-10-22", freq="B")
    pe = d.year.map({2022: 8, 2023: 10, 2024: 0, 2025: 14, 2026: 20}).astype(float)
    r = va.estimate(_qf(), _rev(), _px(), pd.DataFrame({"date": d, "per": pe}))
    assert [y["year"] for y in r["pe"]["years"]] == [2022, 2023, 2025, 2026]
    assert r["pe"]["mid"] == pytest.approx(12)


def test_營業費用用費用率_固定金額只當對照():
    r = va.estimate(_qf(), _rev(), _px(), _per())
    inp = r["inputs"]
    assert inp["opex_ratio"] == pytest.approx(0.12)
    assert inp["opex_est"] == pytest.approx(3e9 * 0.12)
    # 固定 3 億：30 億 × 40% − 3 億 = 9 億 → 7.2 億 ÷ 5 億 × 4 = 5.76（營收升時比費用率版樂觀）
    assert inp["run_fixed_opex"] == pytest.approx(5.76, rel=0.01)
    assert inp["run_fixed_opex"] > r["eps"]["run_ex"]


def test_有非控制權益_轉換率與股數用歸母淨利():
    """net_income（合併）比歸母多 25% → 只看 net_income 會推出 6.25 億股、轉換率 100%；
    用 ni_parent 才回到 5 億股、80%。兩種算法的單季 EPS 剛好抵銷，所以比 conv／shares。"""
    q = _qf()
    q["ni_parent"] = q["net_income"]
    q["net_income"] = q["net_income"] * 1.25
    r = va.estimate(q, _rev(), _px(), _per())
    assert r["ok"]
    assert abs(r["inputs"]["conv"] - 0.8) < 1e-9
    assert abs(r["inputs"]["shares"] - SHARES) / SHARES < 0.01


def test_最新一天交易所本益比空白_不給成長價():
    per = _per()
    per.loc[per.index[-1], "per"] = np.nan
    r = va.estimate(_qf(), _rev(), _px(), per)
    assert r["cur_pe"] is None and r["growth_price"] is None


def _ohlcv(n: int = 300, base: float = 100.0, hot_lo: float | None = None):
    """每天高低 ±2、收在 base；hot_lo 給值 → 最後 120 天改在 hot_lo 附近、量放大 5 倍（造一塊大量區）。"""
    d = pd.bdate_range(end="2026-10-22", periods=n)
    close = np.full(n, base)
    vol = np.full(n, 1000.0)
    if hot_lo is not None:
        close[-120:-20] = hot_lo
        vol[-120:-20] = 5000.0
    return pd.DataFrame({"date": d, "open": close, "high": close + 2, "low": close - 2,
                         "close": close, "volume": vol})


def test_週ATR_每週高低差4():
    assert va.weekly_atr(_ohlcv()) == pytest.approx(4.0, rel=0.01)
    assert va.weekly_atr(_ohlcv(n=40)) is None          # 8 週不足 15 週


def test_停損只看波動_不被下方大量區改動():
    """停損與支撐分開（2026-10-30 定案）：有大量區也維持現價 − 2×週ATR。"""
    rk = va.risk_levels(_ohlcv(hot_lo=95.0))            # 大量區約 93～97，現價 100
    assert rk["stop"] == pytest.approx(100 - 2 * rk["watr"])
    assert rk["support"] is not None                  # 有支撐候選，但停損照樣不動
    assert rk["sup_far"] is (rk["sup_px"] < rk["stop"])


def test_停損距離_提示不改價():
    rk = va.risk_levels(_ohlcv())                       # 週ATR 4 → 停損 92（−8%）
    assert rk["stop"] == pytest.approx(92.0, rel=0.01)
    d = _ohlcv(base=20.0)                               # 週ATR 4 占 20% → 停損 −40%
    rk = va.risk_levels(d)
    assert rk["stop"] == pytest.approx(12.0, rel=0.01) and "波動大" in rk["hint"]


def test_週ATR_未收完的週不算():
    d = _ohlcv()                                        # 最後一天 10/22 是週四 → 該週不算
    d.loc[d.index[-1], "high"] = 200.0
    assert va.weekly_atr(d) == pytest.approx(4.0, rel=0.01)


def test_現價不低於成長價_不算買點(monkeypatch):
    monkeypatch.setattr(va, "BUY_RANGE_PAUSED", False)   # 驗改版前的邏輯
    q = _qf()
    r = va.estimate(q, _rev(), _ohlcv(base=100.0), _per())
    assert r["growth_price"] < 100 and r["risk"]["buyable"] is False
    r = va.estimate(q, _rev(), _ohlcv(base=40.0), _per())
    assert r["growth_price"] > 40 and r["risk"]["buyable"] is True


def _wave(n: int = 300):
    """收盤 100 ± 10 正弦擺盪、最後一天收 100；|收盤−100| < 5 的日子量 5 倍（大量區約 95～105）。"""
    d = pd.bdate_range(end="2026-10-22", periods=n)
    close = 100 + 10 * np.sin(np.arange(n) / 8)
    close[-1] = 100.0
    vol = np.where(np.abs(close - 100) < 5, 5000.0, 1000.0)
    return pd.DataFrame({"date": d, "open": close, "high": close + 1, "low": close - 1,
                         "close": close, "volume": vol})


def test_現價在大量區內_支撐壓力是該區下緣上緣():
    rk = va.risk_levels(_wave())
    at = rk["at"]
    assert at is not None and at["lo"] < 100 < at["hi"]
    assert rk["support"] is at and rk["sup_px"] == pytest.approx(at["lo"])
    assert rk["resist"] is at and rk["res_px"] == pytest.approx(at["hi"])
    assert rk["stop"] == pytest.approx(100 - 2 * rk["watr"])


def test_上方沒有大量區_壓力候選留空_另給近一年高():
    """130 線性跌到 100、量平均 → 沒有大量區；壓力候選 None，近一年高 131 另列。"""
    n = 300
    close = np.linspace(130, 100, n)
    d = pd.DataFrame({"date": pd.bdate_range(end="2026-10-22", periods=n), "open": close,
                      "high": close + 1, "low": close - 1, "close": close, "volume": 1000.0})
    rk = va.risk_levels(d)
    assert rk["resist"] is None and rk["res_px"] is None and rk["at"] is None
    assert rk["high"] == pytest.approx(close[-250] + 1)


def test_大量區占量_等於區間內實際的量():
    """合併時中間橋接箱的量也要算（sol 審查 2026-10-30）：占量＝典型價落在區內那些天的量。"""
    d = _wave()
    tp = (d["high"] + d["low"] + d["close"]) / 3
    tot = d["volume"].sum()
    for z in va.volume_zones(d):
        inside = d["volume"][(tp >= z["lo"] - 1e-9) & (tp < z["hi"] - 1e-9)].sum()
        assert z["share"] == pytest.approx(inside / tot, abs=0.02)


def test_月營收重複月或空白_不湊三個月():
    d = _rev()
    d.loc[d.index[-2], "month"] = d.loc[d.index[-3], "month"]        # 07、07、09
    assert va.estimate(_qf(), d, _px(), _per())["ok"] is False
    d = _rev()
    d.loc[d.index[-2], "revenue"] = np.nan
    assert va.estimate(_qf(), d, _px(), _per())["ok"] is False


def test_近四季中間漏一季_不算轉換率():
    q = _qf().drop(index=5).reset_index(drop=True)                    # 抽掉倒數第三季
    r = va.estimate(q, _rev(), _px(), _per())
    assert r["ok"] and r["inputs"]["conv"] is None


def test_買進區間_各狀態():
    b = va.buy_range(100, 120, 150)                       # 現價 < 合理 → 現價～135
    assert b["c"] == 0.9 and b["state"] == "in" and b["lo"] == 100 and b["hi"] == pytest.approx(135)
    assert va.buy_range(125, 120, 150)["state"] == "in_above_fair"   # 合理 < 現價 ≤ 135
    assert va.buy_range(140, 120, 150)["state"] == "above"           # 現價 > 上限，合理 ≤ 上限
    assert va.buy_range(140, 138, 150)["state"] == "none"            # 上限 135 < 合理 138
    assert va.buy_range(100, None, 150)["state"] == "cap_in"
    assert va.buy_range(140, None, 150)["state"] == "cap_above"
    assert va.buy_range(100, 120, None) is None


def test_買進區間_景氣高峰或業外大改用08_不疊加():
    b = va.buy_range(100, 120, 150, cycle_peak=True, nonop_high=True)
    assert b["c"] == 0.8 and b["hi"] == pytest.approx(120) and len(b["why"]) == 2
    assert b["min_growth"] == pytest.approx(0.25)
    assert va.buy_range(100, 120, 150)["min_growth"] == pytest.approx(1 / 0.9 - 1)


def test_estimate_有買進區間欄位(monkeypatch):
    monkeypatch.setattr(va, "BUY_RANGE_PAUSED", False)   # 驗改版前的邏輯
    r = va.estimate(_qf(), _rev(), _ohlcv(base=40.0), _per())
    assert r["buy"] is not None and r["buy"]["hi"] == pytest.approx(0.9 * r["growth_price"])


def _flat_fri(n: int = 200, end: str = "2026-10-23", tail: list[float] | None = None):
    """收盤 100、高低 ±2 → 週ATR 4、22 週高 102 → 持股停損 102 − 8 ＝ 94。
    end 預設週五（最後一週已收完）；tail 把最後幾天的收盤（含高低）換掉。"""
    d = _ohlcv(n=n)
    d["date"] = pd.bdate_range(end=end, periods=n)
    for i, c in enumerate(tail or []):
        k = d.index[len(d) - len(tail) + i]
        d.loc[k, ["open", "close"]] = c
        d.loc[k, "high"], d.loc[k, "low"] = c + 2, c - 2
    return d


def test_持股停損_近22週高減2倍週ATR_線上():
    hd = va.hold_stop(_flat_fri())
    assert hd["line"] == pytest.approx(94.0, rel=0.01)
    assert hd["state"] == "above" and hd["reset"] is False and hd["under_now"] is False
    assert hd["dist"] == pytest.approx(-0.06, abs=0.005) and hd["brk_date"] is None
    assert va.hold_stop(_ohlcv(n=60)) is None            # 週數不足 22＋1


def test_持股停損_本週收盤剛跌破_紅字用跌破的那條線_另給新線():
    hd = va.hold_stop(_flat_fri(tail=[80.0] * 5))        # 最後一整週收 80 < 上週線 94
    assert hd["state"] == "new" and hd["brk_line"] == pytest.approx(94.0, rel=0.01)
    assert hd["reset"] is True and hd["line"] < 80       # 新線從跌破那週的高點 82 起算
    assert hd["hh"] == pytest.approx(82.0)


def test_持股停損_跌破後沒賣_線從跌破那週重算_不會卡在舊高點():
    """2317 案例（2026-10-30）：舊版 22 週高 − 2×ATR 卡在現價上方 20 週、顯示「不適用」。"""
    hd = va.hold_stop(_flat_fri(tail=[80.0] * 10))       # 跌破後又盤 1 週
    assert hd["state"] == "above" and hd["reset"] is True
    assert hd["line"] < 80 and hd["dist"] < 0            # 線在現價下方，可以用
    assert hd["brk_line"] == pytest.approx(94.0, rel=0.01) and hd["brk_date"] is not None


def test_持股停損_週中跌破還沒週收盤_只標現價在線下():
    hd = va.hold_stop(_flat_fri(end="2026-10-22", tail=[90.0]))   # 週四收 90，本週沒收完
    assert hd["state"] == "above" and hd["under_now"] is True
    assert hd["line"] == pytest.approx(94.0, rel=0.01)


def test_不在買進區間_給持股停損_在區間內不給(monkeypatch):
    monkeypatch.setattr(va, "BUY_RANGE_PAUSED", False)   # 驗改版前的邏輯
    q = _qf()
    r = va.estimate(q, _rev(), _ohlcv(base=100.0), _per())   # 現價高於成長價 → 不在區間
    assert r["risk"]["buyable"] is False and r["risk"]["hold"] is not None
    r = va.estimate(q, _rev(), _ohlcv(base=40.0), _per())
    assert r["risk"]["buyable"] is True and r["risk"]["hold"] is None
    g = r["growth_price"]                                 # 低於成長價、但高於上緣（成長價×c）
    r = va.estimate(q, _rev(), _ohlcv(base=g * 0.97), _per())
    assert r["buy"]["state"] not in va.BUY_IN_STATES
    assert r["buy"]["impl"] == pytest.approx(g / (g * 0.97) - 1)   # 卡片「預估獲利成長約」＝成長價/現價−1
    assert r["buy"]["impl"] < r["buy"]["min_growth"]
    assert r["risk"]["buyable"] is False and r["risk"]["hold"] is not None


def _lq(eps: list[float], om: list[float] | None = None, end: str = "2025-12-31") -> pd.DataFrame:
    """每季營收 10 億；eps 依序到 end 那一季；om 沒給＝每季 20%。"""
    pe = pd.date_range(end=end, periods=len(eps), freq="QE")
    om = om or [0.2] * len(eps)
    return pd.DataFrame({"period_end": pe, "revenue": 1e9, "op_income": [1e9 * m for m in om],
                         "eps": eps})


def _pe3(vals, years=(2023, 2024, 2025)):
    return {"years": [{"year": y, "pe": v, "days": 200} for y, v in zip(years, vals)]}


def _lab(eps=(2.0, 2.5, 3.0, 4.0), ttm=4.0):
    return {"ttm_eps": ttm, "eps_years": [{"year": 2022 + i, "eps": e} for i, e in enumerate(eps)]}


def _yq(years: list[float]) -> list[float]:
    """年 EPS → 每季平均分配（2020～2025）。"""
    return [e / 4 for e in years for _ in range(4)]


def test_標籤_穩定_一般():
    r = va.stock_label(_lq([1.0] * 24), 4.0)
    assert r["type"] == "normal" and r["state"] is None
    assert r["type_why"] == [] and r["state_why"] == []
    assert r["om_min"] == pytest.approx(0.2) and r["om_max"] == pytest.approx(0.2)
    assert r["max_drop"] == 0.0 and r["loss_years"] == []
    assert r["ttm_eps"] == pytest.approx(4.0)
    assert len(r["eps_years"]) == 6


def test_標籤_近四季合計虧損_虧損中():
    r = va.stock_label(_lq([1.0] * 20 + [-0.5, -0.2, 0.1, 0.1]), 0.5)
    assert r["state"] == "loss"
    assert r["state_why"] == ["近四季 EPS 合計 -0.50 ≤ 0"]
    assert r["type"] == "normal"


def test_標籤_有虧損季但合計為正_獲利不穩():
    r = va.stock_label(_lq([1.0] * 20 + [-0.1, 0.5, 0.5, 0.5]), 2.0)
    assert r["state"] == "unstable"
    assert r["state_why"] == ["近四季有虧損季（合計 1.40）"]


def test_標籤_低基期回升_邊界含等號():
    r = va.stock_label(_lq([1.0] * 20 + [0.1] * 4), 0.8)
    assert r["state"] == "low_base"
    assert r["state_why"] == ["今年預估 EPS 0.80 ≥ 近四季 0.40 的 2 倍，近四季不到 2020 年高點 4.00 的一半"]
    assert r["eps_peak"] == pytest.approx(4.0) and r["eps_peak_year"] == 2020


def test_標籤_預估不到2倍_沒有狀態():
    r = va.stock_label(_lq([1.0] * 20 + [0.1] * 4), 0.79)
    assert r["state"] is None


def test_標籤_預估翻倍但近四季在高點_成長股不是低基期():
    r = va.stock_label(_lq(_yq([2, 3, 4, 5, 6, 7])), 14.0)
    assert r["state"] is None and r["type"] == "normal"


def test_標籤_營益率與EPS都起伏_景氣循環():
    r = va.stock_label(_lq(_yq([2, 4, 8, 4, 5, 6]), om=[0.05, 0.30] * 12), 6.0)
    assert r["type"] == "cyclical" and r["state"] is None
    assert r["max_drop"] == pytest.approx(0.5)
    assert r["drop_from"] == 2022 and r["drop_to"] == 2023
    assert r["type_why"] == ["近 24 季營益率 5%～30%", "年 EPS 從 2022 年 8.00 掉到 2023 年 4.00"]


def test_標籤_只有EPS大跌_一般():
    r = va.stock_label(_lq(_yq([2, 4, 8, 4, 5, 6])), 6.0)
    assert r["type"] == "normal"
    assert r["max_drop"] == pytest.approx(0.5)


def test_標籤_只有營益率起伏_一般():
    r = va.stock_label(_lq([1.0] * 24, om=[0.05, 0.30] * 12), 4.0)
    assert r["type"] == "normal"


def test_標籤_營益率絕對差大但相對穩_一般():
    """2330 型：39%～60% 差 21 個百分點，但最低仍超過最高的一半。"""
    r = va.stock_label(_lq(_yq([2, 4, 8, 4, 5, 6]), om=[0.39, 0.60] * 12), 6.0)
    assert r["type"] == "normal"


def test_標籤_跌30趴_EPS條件不成立():
    r = va.stock_label(_lq(_yq([4, 6, 8, 5.6, 6, 7]), om=[0.05, 0.30] * 12), 7.0)
    assert r["type"] == "normal"
    assert r["max_drop"] == pytest.approx(0.3)


def test_標籤_連年虧損後大賺_虧損年也算_景氣循環():
    """陽明型：沒有正的前高可算跌幅，靠虧損年判。"""
    r = va.stock_label(_lq(_yq([-2, -1, -0.5, 1, 8, 10]), om=[-0.10, 0.40] * 12), 10.0)
    assert r["max_drop"] == 0.0
    assert r["loss_years"] == [2020, 2021, 2022]
    assert r["type"] == "cyclical"
    assert r["type_why"] == ["近 24 季營益率 -10%～40%", "2022 年虧損（EPS -0.50）"]


def test_標籤_循環股有虧損季_兩層都保留():
    q = _lq(_yq([2, 4, 8, 4, 5, 6]), om=[0.05, 0.30] * 12)
    q.loc[q.index[-1], "eps"] = -0.1
    r = va.stock_label(q, 6.0)
    assert r["type"] == "cyclical" and r["state"] == "unstable"
    assert r["state_why"] == ["近四季有虧損季（合計 4.40）"]


def test_標籤_資料太短_不判循環():
    r = va.stock_label(_lq([1.0] * 6), 4.0)
    assert r["type"] == "normal" and r["state"] is None
    assert r["om_n"] == 6 and r["om_min"] is None and r["om_max"] is None
    assert r["max_drop"] is None
    assert [d["year"] for d in r["eps_years"]] == [2025]


def test_標籤_近四季漏一季_不判狀態():
    q = _lq([1.0] * 20 + [-1.0] * 4)
    q = q.drop(q.index[-2]).reset_index(drop=True)
    r = va.stock_label(q, -1.0)
    assert r["ttm_eps"] is None
    assert r["state"] is None


def test_estimate_有標籤欄位():
    r = va.estimate(_qf(), _rev(), _ohlcv(base=40.0), _per())
    assert r["label"]["type"] in {"cyclical", "normal"}
    assert r["label"]["state"] in {None, "loss", "unstable", "low_base"}


def test_高PE_循環股不適用():
    r = va.high_pe_price(_pe3([40, 45, 35]), 6.0, {**_lab(), "type": "cyclical", "state": None}, 150)
    assert r["fail"] == ["景氣循環股不適用"]
    assert r["price_high_pe"] == 210


def test_高PE_有狀態不適用():
    r = va.high_pe_price(_pe3([40, 45, 35]), 6.0, {**_lab(), "type": "normal", "state": "unstable"}, 150)
    assert r["fail"] == ["目前獲利不穩不適用"]


def test_高PE_全過():
    r = va.high_pe_price(_pe3([40, 45, 35]), 6.0, _lab(), 150)
    assert r["eligible"] and r["fail"] == []
    assert r["pe_min_3y"] == 35 and r["pe_ref_high"] == 35
    assert r["price_high_pe"] == 210
    assert r["upside_high_pe"] == pytest.approx(0.4)
    assert r["eps_fwd_growth"] == pytest.approx(0.5)
    assert r["eps_cagr_3y"] == pytest.approx(2 ** (1 / 3) - 1)


def test_高PE_倍數上限50():
    r = va.high_pe_price(_pe3([60, 70, 80]), 6.0, _lab(), 150)
    assert r["eligible"]
    assert r["pe_ref_high"] == 50 and r["price_high_pe"] == 300


def test_高PE_有一年不到30():
    r = va.high_pe_price(_pe3([40, 28, 45]), 6.0, _lab(), 150)
    assert not r["eligible"]
    assert r["fail"] == ["近 3 年最低年均本益比 28.0 ≤ 30"]
    assert r["price_high_pe"] == 168


def test_高PE_年份不連續():
    r = va.high_pe_price(_pe3([40, 45, 35], years=(2021, 2023, 2025)), 6.0, _lab(), 150)
    assert "近 3 年年均本益比不足 3 年或不連續" in r["fail"]
    assert r["pe_min_3y"] is None
    assert r["price_high_pe"] is None
    assert "算不出情境價" in r["fail"]


def test_高PE_pe為None():
    r = va.high_pe_price(None, 6.0, _lab(), 150)
    assert r["pe_years_3y"] == []
    assert not r["eligible"]


def test_高PE_預估成長不足():
    r = va.high_pe_price(_pe3([40, 45, 35]), 4.4, _lab(), 150)
    assert r["fail"] == ["預估成長 10% 未達 11%"]


def test_高PE_情境價不高於現價():
    r = va.high_pe_price(_pe3([40, 45, 35]), 6.0, _lab(), 250)
    assert r["fail"] == ["情境價 210 ≤ 現價 250"]


def test_高PE_有虧損年():
    r = va.high_pe_price(_pe3([40, 45, 35]), 6.0, _lab(eps=(2.0, -0.5, 3.0, 4.0)), 150)
    assert r["fail"] == ["近 3 年有虧損年或年度不足"]


def test_高PE_EPS衰退():
    r = va.high_pe_price(_pe3([40, 45, 35]), 6.0, _lab(eps=(5.0, 4.0, 4.5, 4.0)), 150)
    assert r["fail"] == ["近 3 年 EPS 年複合成長 -7% ≤ 0"]


def test_estimate_有高PE欄位():
    r = va.estimate(_qf(), _rev(), _ohlcv(base=40.0), _per())
    assert isinstance(r["high_pe"]["eligible"], bool)
    assert isinstance(r["high_pe"]["fail"], list)



def test_買進區間停用中_不給區間但持股停損照給():
    """2026-10-30 使用者：歸類完成前停用買進區間與成長價（會跟股價一起漲）。"""
    assert va.BUY_RANGE_PAUSED is True
    r = va.estimate(_qf(), _rev(), _ohlcv(base=40.0), _per())   # 開關關掉時這組在區間內
    assert r["buy"] is None
    assert r["risk"]["paused"] is True and r["risk"]["buyable"] is False
    assert r["risk"]["hold"] is not None
    assert r["band"] is not None                                 # 三段價照給
