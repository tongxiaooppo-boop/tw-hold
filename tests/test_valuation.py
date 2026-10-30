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


def test_停損_沒支撐就用2倍週ATR():
    rk = va.risk_levels(_ohlcv())
    assert rk["by"] == "watr" and rk["stop"] == pytest.approx(92.0, rel=0.01)


def test_停損_下方大量區_改用支撐下緣減半個週ATR():
    rk = va.risk_levels(_ohlcv(hot_lo=95.0))            # 大量區約 93～97，現價 100
    z = rk["support"]
    assert z is not None and z["hi"] < 100 and z["share"] > 0.5
    assert rk["by"] == "support"
    assert rk["stop"] == pytest.approx(z["lo"] - 0.5 * rk["watr"])
    assert 92.0 < rk["stop"] < 100 - rk["watr"]


def test_現價不低於成長價_不算買點():
    q = _qf()
    r = va.estimate(q, _rev(), _ohlcv(base=100.0), _per())
    assert r["growth_price"] < 100 and r["risk"]["buyable"] is False
    r = va.estimate(q, _rev(), _ohlcv(base=40.0), _per())
    assert r["growth_price"] > 40 and r["risk"]["buyable"] is True
