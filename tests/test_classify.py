"""screener.classify：類型＋狀態＋遲滯（草案 §1；合成資料，預期值手算）。

共用設定：季別從 2015Q1 起，n=44 → 最後一季 2025Q4；總資產固定 4000 → OROA＝TTM 營業利益 ÷ 4000；
eps 預設＝op_income ÷ 100。OROA 從第 5 季（idx 4）起才有值（需 5 個季末總資產），44 季 → 40 個。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

import screener.classify as cl

START = "2015-03-31"


def _col(v, n):
    return list(v) if isinstance(v, (list, tuple, np.ndarray)) else [v] * n


def _q(n=44, rev=1000.0, op=100.0, eps=None, ta=4000.0, cap=1000.0, capex=-50.0) -> pd.DataFrame:
    idx = pd.date_range(START, periods=n, freq="QE")
    rev, op, ta, cap, capex = (_col(x, n) for x in (rev, op, ta, cap, capex))
    eps = [o / 100 for o in op] if eps is None else _col(eps, n)
    return pd.DataFrame({"revenue": rev, "op_income": op, "eps": eps, "total_assets": ta,
                         "capital_stock": cap, "capex": capex},
                        index=pd.DatetimeIndex(idx, name="period_end"))


def _inp(q, **kw) -> cl.ClassInputs:
    base = dict(ticker="T", industry_group="other", quarters=q, oroa_amp_pct=0.5,
                asset_ta_rev_pct=0.5, asset_capex_rev_pct=0.5, rev_beta=1.0, ind_sync=0.3)
    base.update(kw)
    return cl.ClassInputs(**base)


def _monthly(stock_val=0.1, neg_months=None):
    """market：2016-01..2025-12 每月 +5%，2023 全年 −5%（市場收縮）；stock 常數，neg_months 指定的月份改 −2%。"""
    idx = pd.date_range("2016-01-01", "2025-12-01", freq="MS")
    mkt = pd.Series(0.05, index=idx)
    mkt.loc["2023-01-01":"2023-12-01"] = -0.05
    stk = pd.Series(stock_val, index=idx, dtype=float)
    for m in neg_months or []:
        stk.loc[pd.Timestamp(m)] = -0.02
    return stk, mkt


# ── 合成序列 ────────────────────────────────────────

def _cyc_q(tail_op=None):
    """高→低→高：營收 1000／700（idx 12..23）／1000；營業利益 200／0／200。
    TTM op：800 → 0（idx 15..23）→ 800；OROA：0.2 → 0 → 0.2，振幅 P90−P10＝0.2。
    回撤：峰 idx 11（2017Q4，同值取最晚）→ 谷 idx 15（2018Q4）跌 100%；
    期間 TTM 營收年增最低＝idx 15：2800/4000−1＝−30%。"""
    rev = [1000.0] * 12 + [700.0] * 12 + [1000.0] * 20
    op = [200.0] * 12 + [0.0] * 12 + [200.0] * 20
    if tail_op is not None:
        op[-len(tail_op):] = tail_op
    return _q(rev=rev, op=op)


def _cyc_trough_q(turn=False):
    """高→低（停在谷底）：營收 1000（idx 0..23）／700；營業利益 200／0。循環未觀察完整。
    turn=True：idx 36..39 營業利益 −100，idx 40..43 為 −80、−40、20、60（谷底回升形狀）。"""
    rev = [1000.0] * 24 + [700.0] * 20
    op = [200.0] * 24 + [0.0] * 20
    if turn:
        op[36:40] = [-100.0] * 4
        op[40:44] = [-80.0, -40.0, 20.0, 60.0]
    return _q(rev=rev, op=op)


def _bubble_q():
    """單一年泡沫：營收固定 1000；營業利益 100，只有 idx 30 一季 500。
    TTM op 400 → 800（idx 30..33）→ 400：回撤正好 50%，但營收年增始終 0（沒收縮）。
    OROA：36 個 0.1、4 個 0.2 → P90＝0.1+0.1×0.1＝0.11、P10＝0.1 → 振幅 0.01。"""
    op = [100.0] * 44
    op[30] = 500.0
    return _q(op=op)


def _growth_q(n=44, g=1.25):
    """營收每季 ×g^(1/4)（TTM 年增恰為 g−1）；營業利益＝營收 × 10%。
    g=1.25 → 3 年、5 年 CAGR 都是 25%；TTM 營收年增每季 25%。"""
    rev = [1000.0 * g ** (i / 4) for i in range(n)]
    return _q(n=n, rev=rev, op=[0.1 * r for r in rev])


def _growth_cyc_q():
    """既循環又高成長：營收 1000（0..11）／600（12..19）／1000（20..27）／1000×1.1^(i−27)（28..43）；
    營業利益＝營收×20%，但 idx 12..19 為 0。
    循環：TTM op 800 → 0，回撤 100%，期間 TTM 營收年增最低 2400/4000−1＝−40%。
    高成長：3 年 CAGR＝(1.1^12)^(1/3)−1＝1.1^4−1＝46.41%；
      5 年：TTM43/TTM23＝1000×(1.1^13+…+1.1^16)/4000＝4.0055 → 32.0%；
      營業利益 3 年 CAGR 同 46.41%；近 12 季 TTM 營收年增皆 > 0。"""
    rev = [1000.0] * 12 + [600.0] * 8 + [1000.0] * 8 + [1000.0 * 1.1 ** (i - 27) for i in range(28, 44)]
    op = [0.2 * r for r in rev]
    op[12:20] = [0.0] * 8
    return _q(rev=rev, op=op)


# ── 單檔計算 ───────────────────────────────────────

def test_OROA_用5季末總資產平均():
    q = _q(n=8, ta=[1000.0, 2000.0, 3000.0, 4000.0, 5000.0, 5000.0, 5000.0, 5000.0])
    o = cl.oroa_series(q)
    assert np.isnan(o.iloc[3])                                # 只有 4 個季末總資產
    assert o.iloc[4] == pytest.approx(400 / 3000)              # (1000+…+5000)/5＝3000
    assert o.iloc[7] == pytest.approx(400 / 4800)              # idx 3..7：4000、5000×4


def test_OROA振幅_高低高為0點2():
    assert cl.oroa_amplitude(cl.oroa_series(_cyc_q())) == pytest.approx(0.2)


def test_單一年泡沫_振幅幾乎不受影響():
    assert cl.oroa_amplitude(cl.oroa_series(_bubble_q())) == pytest.approx(0.01)


def test_OROA振幅_觀察值不足_NaN():
    assert np.isnan(cl.oroa_amplitude(cl.oroa_series(_q(n=15))))   # 11 個 OROA < 12


def test_營運回撤_循環股():
    d = cl.op_drawdown(_cyc_q())
    assert d["max_dd"] == pytest.approx(1.0)
    assert d["dd_peak"] == pd.Timestamp("2017-12-31")
    assert d["dd_trough"] == pd.Timestamp("2018-12-31")
    assert d["rev_yoy_min"] == pytest.approx(-0.30)
    assert d["contraction"] is True
    assert d["recovered_half"] is True


def test_營運回撤_泡沫_回撤50但營收沒收縮():
    d = cl.op_drawdown(_bubble_q())
    assert d["max_dd"] == pytest.approx(0.5)
    assert d["contraction"] is False


def test_營運回撤_停在谷底_未回升():
    d = cl.op_drawdown(_cyc_trough_q())
    assert d["max_dd"] == pytest.approx(1.0)
    assert d["recovered_half"] is False


def _two_dd_q(second_rev_drop):
    """兩段深回撤：營業利益 200 → 0（idx 8..15）→ 200 → 0（idx 28..35）→ 200。
    第一段營收不變（1000，沒收縮）；第二段營收降為 second_rev_drop 比例（idx 28..35），
    之後營收回到 1000。TTM 營收年增在第二段期間最低約 −(1−比例)×(4季)/4。"""
    rev = [1000.0] * 44
    rev[28:36] = [1000.0 * second_rev_drop] * 8
    op = [200.0] * 44
    op[8:16] = [0.0] * 8
    op[28:36] = [0.0] * 8
    return _q(rev=rev, op=op)


def test_航運型循環_早期溫和回撤_後期深回撤且營收大減_判循環():
    # 前段回撤 100% 但營收沒縮；後段回撤 100% 且 TTM 營收年增最低 −50%
    # 舊語意只看「最大回撤那一段」（同值取最早＝第一段，營收沒縮）→ 條件②不成立；新語意看任何一段
    d = cl.op_drawdown(_two_dd_q(0.5))
    assert d["contraction"] is True
    assert d["max_dd"] == pytest.approx(1.0)
    assert d["dd_trough"] > pd.Timestamp("2015-03-31") + pd.offsets.QuarterEnd(24)   # 記錄的是後段
    assert d["rev_yoy_min"] < -0.10
    c = cl.classify(_inp(_two_dd_q(0.5), oroa_amp_pct=0.9, rev_beta=1.6))
    assert c.type == cl.TYPE_CYCLICAL and c.metrics["cyclical_necessary"] is True


def test_有大回撤但營收從不收縮_條件2不成立():
    d = cl.op_drawdown(_two_dd_q(1.0))
    assert d["max_dd"] == pytest.approx(1.0)          # 無滿足段 → 記錄整體最大回撤（維持原行為）
    assert d["contraction"] is False
    c = cl.classify(_inp(_two_dd_q(1.0), oroa_amp_pct=0.9, rev_beta=1.6))
    assert c.metrics["cyclical_necessary"] is False and c.type != cl.TYPE_CYCLICAL


@pytest.mark.parametrize("vals,amp,expected", [
    ([0.2, 0.0, 0.2], 0.2, True),           # 高→低→高，每段 0.2 ≥ 0.1
    ([0.0, 0.2, 0.0], 0.2, True),           # 低→高→低
    ([0.2, 0.0], 0.2, False),               # 只有一段
    ([0.2, 0.12, 0.2], 0.2, False),         # 每段 0.08 < 0.1
    ([0.2, 0.1, 0.2], 0.2, True),           # 剛好 0.1（≥）
    ([0.2, 0.0, 0.2], float("nan"), False),
])
def test_循環涵蓋檢查(vals, amp, expected):
    s = pd.Series(vals, index=pd.date_range(START, periods=len(vals), freq="QE"))
    assert cl.cycle_coverage(s, amp) is expected


def test_資產強度():
    a = cl.asset_intensity(_q())
    assert a["ta_rev"] == pytest.approx(1.0)                  # 4000 ÷ TTM 營收 4000
    assert a["capex_rev"] == pytest.approx(0.05)              # 20×50 ÷ 20×1000


def test_資產強度_capex季數不足_NaN():
    assert np.isnan(cl.asset_intensity(_q(n=6))["capex_rev"])   # 6 < 8


def test_橫斷面分位():
    s = pd.Series([4.0, 1.0, np.nan, 3.0, 2.0], index=list("abcde"))
    p = cl.cross_section_pct(s)
    assert p["a"] == 1.0 and p["b"] == 0.25 and p["d"] == 0.75 and p["e"] == 0.5
    assert np.isnan(p["c"])


def test_TTM_CAGR():
    idx = pd.date_range(START, periods=13, freq="QE")
    s = pd.Series([4000.0] + [5000.0] * 11 + [6912.0], index=idx)
    assert cl.ttm_cagr(s, 3) == pytest.approx(0.2)            # (6912/4000)^(1/3)−1＝1.728^(1/3)−1
    assert np.isnan(cl.ttm_cagr(s, 5))                         # 20 季前不存在
    s.iloc[0] = -1.0
    assert np.isnan(cl.ttm_cagr(s, 3))


def test_穿越檢定_市場收縮期個股仍成長():
    stk, mkt = _monthly(0.1)
    r = cl.crossing_test(stk, mkt)
    assert r == {"n": 12, "k": 0, "passed": True, "executed": True}


def test_穿越檢定_市場收縮期個股也縮():
    stk, mkt = _monthly(0.1, neg_months=["2023-02-01", "2023-05-01", "2023-09-01"])
    r = cl.crossing_test(stk, mkt)
    assert r["n"] == 12 and r["k"] == 3 and r["passed"] is False


def test_穿越檢定_期間無市場收縮月_未執行():
    stk, mkt = _monthly(0.1)
    mkt[:] = 0.05
    r = cl.crossing_test(stk, mkt)
    assert r == {"n": 0, "k": 0, "passed": True, "executed": False}


# ── 0 資料閘門、1 金融 ───────────────────────────────

def test_財報不足12季_不分類():
    c = cl.classify(_inp(_q(n=11)))
    assert c.type == cl.TYPE_INSUFFICIENT
    assert c.state == [] and c.subtags == []
    assert c.why == ["單季財報僅 11 季（< 12 季），不分類"]
    assert c.rule_version == cl.RULE_VERSION


def test_財報剛好12季_可分類():
    assert cl.classify(_inp(_q(n=12))).type == cl.TYPE_NORMAL


def test_金融保險_走PB分支_不看數字():
    c = cl.classify(_inp(_cyc_q(), industry_group="financial", oroa_amp_pct=0.9, rev_beta=1.6))
    assert c.type == cl.TYPE_FINANCIAL
    assert c.why[0] == "產業為金融保險，走 PB"


def test_缺欄位_KeyError():
    with pytest.raises(KeyError):
        cl.classify(_inp(_q().drop(columns=["capital_stock"])))


# ── 2 特殊退出 ──────────────────────────────────────

def test_生技近12季8季虧損_特殊退出():
    eps = [1.0] * 36 + [-0.5] * 8
    c = cl.classify(_inp(_q(eps=eps), industry_group="biotech"))
    assert c.type == cl.TYPE_SPECIAL
    assert c.metrics["special_triggers"] == ["biotech_loss"]
    assert "生技醫療近 12 季有 8 季虧損（≥ 8）" in c.why


def test_生技近12季7季虧損_不退出():
    eps = [1.0] * 37 + [-0.5] * 7
    c = cl.classify(_inp(_q(eps=eps), industry_group="biotech"))
    assert c.type != cl.TYPE_SPECIAL


def test_非生技虧損多_不因此退出():
    eps = [1.0] * 32 + [-0.5] * 12
    assert cl.classify(_inp(_q(eps=eps))).type != cl.TYPE_SPECIAL


def test_建材營造_特殊退出():
    c = cl.classify(_inp(_q(), industry_group="construction"))
    assert c.type == cl.TYPE_SPECIAL
    assert c.metrics["special_triggers"] == ["construction"]
    assert "建材營造：營收認列不連續，只給 PB 位置" in c.why


def test_股本增50趴_特殊退出():
    cap = [1000.0] * 40 + [1500.0] * 4                       # 1500 ÷ 4 季前 1000 − 1＝+50%
    c = cl.classify(_inp(_q(cap=cap)))
    assert c.type == cl.TYPE_SPECIAL
    assert c.metrics["special_triggers"] == ["cap_change"]
    assert "股本 4 季變動 +50%（> 30%）" in c.why


def test_減資40趴_也算股本變動_特殊退出():
    cap = [1000.0] * 40 + [600.0] * 4
    assert cl.classify(_inp(_q(cap=cap))).type == cl.TYPE_SPECIAL


def test_股本增25趴_不退出():
    cap = [1000.0] * 40 + [1250.0] * 4
    assert cl.classify(_inp(_q(cap=cap))).type != cl.TYPE_SPECIAL


def test_營收年增逾100趴且股本同步增_疑似併購_特殊退出():
    # TTM 營收 10000 ÷ 4000 − 1＝+150%；股本 +20%（< 30%，但 > 10%）
    rev = [1000.0] * 40 + [2500.0] * 4
    cap = [1000.0] * 40 + [1200.0] * 4
    c = cl.classify(_inp(_q(rev=rev, cap=cap)))
    assert c.type == cl.TYPE_SPECIAL
    assert c.metrics["special_triggers"] == ["rev_jump_cap"]
    assert "TTM 營收年增 +150% 且股本同步增 +20%，疑似併購/重組" in c.why


def test_營收年增逾100趴但股本只增5趴_不退出():
    rev = [1000.0] * 40 + [2500.0] * 4
    cap = [1000.0] * 40 + [1050.0] * 4
    assert cl.classify(_inp(_q(rev=rev, cap=cap))).type != cl.TYPE_SPECIAL


# ── 3 景氣循環 ──────────────────────────────────────

def test_OROA高低高_營收收縮_輔助成立_判循環():
    c = cl.classify(_inp(_cyc_q(), oroa_amp_pct=0.9, rev_beta=1.6))
    assert c.type == cl.TYPE_CYCLICAL
    assert cl.SUB_SUSPECT_CYCLE not in c.subtags
    assert cl.SUB_CYCLE_INCOMPLETE not in c.subtags
    assert cl.SUB_ASSET_LIGHT in c.subtags
    m = c.metrics
    assert m["oroa_amp"] == pytest.approx(0.2)
    assert m["max_dd"] == pytest.approx(1.0) and m["contraction"] is True and m["coverage"] is True
    assert m["cyclical_necessary"] is True and m["cyclical_aux"] is True
    assert "OROA 振幅 20.0%，位於全體前 10%" in c.why
    assert "TTM 營業利益自 2017Q4 高點最多跌 100%，期間 TTM 營收年增最低 -30%" in c.why
    assert "營收 beta 1.60（≥ 1.5）" in c.why
    assert c.reasons_degrade == []


def test_必要兩條但無輔助_疑似循環():
    c = cl.classify(_inp(_cyc_q(), oroa_amp_pct=0.9, rev_beta=1.0, ind_sync=0.3))
    assert c.type == cl.TYPE_CYCLICAL
    assert cl.SUB_SUSPECT_CYCLE in c.subtags
    assert "疑似循環（缺輔助條件）" in c.reasons_degrade
    assert "缺輔助條件（營收 beta 1.00、產業同步度 0.30），列疑似循環" in c.why


def test_同步度0點6_輔助成立():
    c = cl.classify(_inp(_cyc_q(), oroa_amp_pct=0.9, rev_beta=float("nan"), ind_sync=0.6))
    assert c.type == cl.TYPE_CYCLICAL and cl.SUB_SUSPECT_CYCLE not in c.subtags
    assert "產業同步度 0.60（≥ 0.6）" in c.why


def test_beta剛好1點5_輔助成立():
    c = cl.classify(_inp(_cyc_q(), oroa_amp_pct=0.9, rev_beta=1.5))
    assert cl.SUB_SUSPECT_CYCLE not in c.subtags


def test_振幅分位0點70_剛好前30趴_判循環():
    assert cl.classify(_inp(_cyc_q(), oroa_amp_pct=0.70, rev_beta=1.6)).type == cl.TYPE_CYCLICAL


def test_振幅分位0點69_不在前30趴_不判循環():
    c = cl.classify(_inp(_cyc_q(), oroa_amp_pct=0.69, rev_beta=1.6))
    assert c.type == cl.TYPE_NORMAL
    assert c.why == ["未符合景氣循環或高成長條件"]


def test_振幅分位NaN_不判循環():
    assert cl.classify(_inp(_cyc_q(), oroa_amp_pct=float("nan"), rev_beta=1.6)).type == cl.TYPE_NORMAL


def test_單一年泡沫_不判循環():
    # 振幅分位即使給 0.95、beta 2，回撤 50% 期間營收沒收縮 → 必要②不成立
    c = cl.classify(_inp(_bubble_q(), oroa_amp_pct=0.95, rev_beta=2.0))
    assert c.type == cl.TYPE_NORMAL
    assert c.metrics["cyclical_necessary"] is False


def test_回撤不足50趴_不判循環():
    rev = [1000.0] * 12 + [700.0] * 12 + [1000.0] * 20
    op = [200.0] * 12 + [120.0] * 12 + [200.0] * 20          # TTM 800 → 480，回撤 40%
    c = cl.classify(_inp(_q(rev=rev, op=op), oroa_amp_pct=0.9, rev_beta=1.6))
    assert c.type == cl.TYPE_NORMAL
    assert c.metrics["max_dd"] == pytest.approx(0.4)


def test_停在谷底_循環未觀察完整_降級():
    c = cl.classify(_inp(_cyc_trough_q(), oroa_amp_pct=0.9, rev_beta=1.6))
    assert c.type == cl.TYPE_CYCLICAL
    assert cl.SUB_CYCLE_INCOMPLETE in c.subtags
    assert "循環未觀察完整" in c.reasons_degrade
    assert "回撤後未回到前高 50%（可能為結構衰退）" in c.reasons_degrade
    assert c.metrics["coverage"] is False


def test_資產重_總資產營收比在前40趴():
    c = cl.classify(_inp(_cyc_q(), oroa_amp_pct=0.9, rev_beta=1.6, asset_ta_rev_pct=0.60))
    assert cl.SUB_ASSET_HEAVY in c.subtags and c.metrics["asset_heavy"] is True


def test_資產重_capex強度在前40趴():
    c = cl.classify(_inp(_cyc_q(), oroa_amp_pct=0.9, rev_beta=1.6,
                         asset_ta_rev_pct=0.1, asset_capex_rev_pct=0.61))
    assert cl.SUB_ASSET_HEAVY in c.subtags


def test_資產輕_兩項都在前40趴之外():
    c = cl.classify(_inp(_cyc_q(), oroa_amp_pct=0.9, rev_beta=1.6,
                         asset_ta_rev_pct=0.59, asset_capex_rev_pct=0.59))
    assert cl.SUB_ASSET_LIGHT in c.subtags and c.metrics["asset_heavy"] is False


def test_非循環類_不加資產重輕副標():
    c = cl.classify(_inp(_q(), asset_ta_rev_pct=0.9))
    assert cl.SUB_ASSET_HEAVY not in c.subtags and cl.SUB_ASSET_LIGHT not in c.subtags


# ── 4 高成長 ─────────────────────────────────────────

def test_高成長_全部成立():
    stk, mkt = _monthly(0.25)
    c = cl.classify(_inp(_growth_q(), stock_rev_ttm_yoy=stk, market_rev_ttm_yoy=mkt))
    assert c.type == cl.TYPE_GROWTH
    assert c.metrics["rev_cagr3"] == pytest.approx(0.25)
    assert c.metrics["rev_cagr5"] == pytest.approx(0.25)
    assert c.metrics["op_cagr3"] == pytest.approx(0.25)
    assert c.metrics["growth_core"] is True
    assert "TTM 營收 3 年 CAGR 25%、5 年 25%" in c.why
    assert "近 12 季 TTM 營收年增最低 +25%（≥ -10%）" in c.why


def test_三年營收CAGR30但市場收縮期也縮_判循環不判高成長():
    stk, mkt = _monthly(0.3, neg_months=["2023-03-01", "2023-06-01"])
    c = cl.classify(_inp(_growth_cyc_q(), oroa_amp_pct=0.9, rev_beta=1.6,
                         stock_rev_ttm_yoy=stk, market_rev_ttm_yoy=mkt))
    assert c.metrics["rev_cagr3"] == pytest.approx(1.1 ** 4 - 1)
    assert c.metrics["rev_cagr5"] == pytest.approx(
        (1.1 ** 13 * (1 + 1.1 + 1.1 ** 2 + 1.1 ** 3) / 4) ** 0.2 - 1)
    assert c.type == cl.TYPE_CYCLICAL
    assert cl.SUB_GROWTH_CYCLE in c.subtags
    assert "市場營收收縮的 12 個月，個股有 2 個月 ≤ 0" in c.why


def test_市場收縮期個股仍成長_通過穿越檢定():
    stk, mkt = _monthly(0.3)
    c = cl.classify(_inp(_growth_cyc_q(), oroa_amp_pct=0.9, rev_beta=1.6,
                         stock_rev_ttm_yoy=stk, market_rev_ttm_yoy=mkt))
    assert c.type == cl.TYPE_GROWTH
    assert cl.SUB_CYCLICAL_GROWTH in c.subtags
    assert "市場營收收縮的 12 個月，個股營收年增皆 > 0" in c.why


def test_循環加高成長_無市場收縮月_視為通過但降級():
    stk, mkt = _monthly(0.3)
    mkt[:] = 0.05
    c = cl.classify(_inp(_growth_cyc_q(), oroa_amp_pct=0.9, rev_beta=1.6,
                         stock_rev_ttm_yoy=stk, market_rev_ttm_yoy=mkt))
    assert c.type == cl.TYPE_GROWTH
    assert "期間無市場營收收縮月，穿越檢定未執行" in c.reasons_degrade


def test_高成長_營業利益3年前為負_不成立():
    q = _growth_q()
    q.iloc[28:32, q.columns.get_loc("op_income")] = -10.0     # idx 31 的 TTM op＝−40 ≤ 0
    c = cl.classify(_inp(q))
    assert c.type == cl.TYPE_NORMAL
    assert math.isnan(c.metrics["op_cagr3"])


def _growth_q_min_yoy(target):
    """_growth_q 只改 idx 38 的營收，使近 12 季 TTM 營收年增的最低點（idx 38）＝target。
    原 TTM(38)＝1.25×TTM(34)；改後 TTM(38)＝(1+target)×TTM(34)，差額從 idx 38 單季營收扣掉。
    營業利益不動（3 年 CAGR 只看最後一季，不受影響）。"""
    q = _growth_q()
    rev = q["revenue"].to_numpy(dtype=float).copy()
    s34 = rev[31:35].sum()
    rev[38] = rev[38] - (1.25 - (1 + target)) * s34
    q["revenue"] = rev
    return q


def test_近12季TTM營收年增最低跌破負10pct_不判高成長():
    q = _growth_q()
    q.iloc[38, q.columns.get_loc("revenue")] = 0.0
    # TTM(38)÷TTM(34)＝1.25×(1+g+g²)/(1+g+g²+g³)，g＝1.25^0.25 → 約 0.911（年增 −8.9%）；
    # 2026-11-01 起門檻放寬為最低 ≥ −10%，所以再把 idx 37 也歸零，年增最低跌破 −10% 才不成立
    q.iloc[37, q.columns.get_loc("revenue")] = 0.0
    assert cl.classify(_inp(q)).type == cl.TYPE_NORMAL


def test_高成長_營收年增最低負5pct_仍通過第三條():
    q = _growth_q_min_yoy(-0.05)
    c = cl.classify(_inp(q))
    assert c.type == cl.TYPE_GROWTH and c.metrics["growth_core"] is True
    assert "近 12 季 TTM 營收年增最低 -5%（≥ -10%）" in c.why


def test_高成長_營收年增最低負15pct_不通過():
    q = _growth_q_min_yoy(-0.15)
    c = cl.classify(_inp(q))
    assert c.type == cl.TYPE_NORMAL and c.metrics["growth_core"] is False


def test_5年CAGR不足12_不判高成長():
    # 營收 1000（0..39）、1750（40..43）：3 年＝1.75^(1/3)−1＝20.5%，5 年＝1.75^(1/5)−1＝11.8%
    rev = [1000.0] * 40 + [1750.0] * 4
    c = cl.classify(_inp(_q(rev=rev, op=[0.1 * r for r in rev])))
    assert c.metrics["rev_cagr3"] == pytest.approx(1.75 ** (1 / 3) - 1)
    assert c.metrics["rev_cagr5"] == pytest.approx(1.75 ** 0.2 - 1)
    assert c.type == cl.TYPE_NORMAL


def test_上市未滿20季_降一級_5年CAGR未檢查():
    c = cl.classify(_inp(_growth_q(n=20), listed_quarters=18))
    assert c.type == cl.TYPE_GROWTH
    assert math.isnan(c.metrics["rev_cagr5"])
    assert "上市未滿 20 季" in c.reasons_degrade
    assert "營收歷史不足 5 年，5 年 CAGR 未檢查" in c.reasons_degrade
    assert "TTM 營收 3 年 CAGR 25%、5 年 —" in c.why


def test_高成長留任門檻_寫在stay_ok():
    # 3 年 CAGR 15%：進入門檻 20% 不過，但留任門檻 12% 過
    c = cl.classify(_inp(_growth_q(g=1.15)))
    assert c.type == cl.TYPE_NORMAL
    assert c.metrics["stay_ok"][cl.TYPE_GROWTH] is True


def test_高成長留任門檻_CAGR10_不能留任():
    c = cl.classify(_inp(_growth_q(g=1.10)))
    assert c.metrics["stay_ok"][cl.TYPE_GROWTH] is False


# ── 5 一般與副標 ────────────────────────────────────

def test_三年營收CAGR小於負5_副標營運收縮():
    rev = [1000.0] * 32 + [800.0] * 12                        # (3200/4000)^(1/3)−1＝−7.2%
    c = cl.classify(_inp(_q(rev=rev)))
    assert c.type == cl.TYPE_NORMAL
    assert cl.SUB_SHRINKING in c.subtags


def test_近5年有虧損年_副標獲利不穩():
    eps = [1.0] * 44
    eps[33] = -5.0                                            # 2023Q2 → 2023 全年 −2
    c = cl.classify(_inp(_q(eps=eps)))
    assert cl.SUB_UNSTABLE in c.subtags


def test_虧損年在5年以前_不加副標():
    eps = [1.0] * 44
    eps[18] = -5.0                                            # 2019Q3；近 5 個完整年＝2021～2025
    assert cl.SUB_UNSTABLE not in cl.classify(_inp(_q(eps=eps))).subtags


# ── 狀態 ────────────────────────────────────────────

def test_TTM_EPS小於等於0_虧損狀態():
    eps = [1.0] * 40 + [-1.0, 0.5, 0.25, 0.25]               # 合計 0
    c = cl.classify(_inp(_q(eps=eps)))
    assert cl.STATE_LOSS in c.state
    assert cl.STATE_UNSTABLE in c.state


def test_預估EPS_NC小於等於0_另列預估轉虧():
    c = cl.classify(_inp(_q(), eps_nc=-0.1))
    assert cl.STATE_FWD_LOSS in c.state and cl.STATE_LOSS not in c.state


def test_近4季有虧損季_獲利不穩():
    eps = [1.0] * 40 + [2.0, -0.5, 2.0, 2.0]
    c = cl.classify(_inp(_q(eps=eps)))
    assert c.state[0] == cl.STATE_UNSTABLE and cl.STATE_LOSS not in c.state


def test_EPS_NC低於5年TTM中位數兩成_獲利不穩():
    # TTM EPS 恆為 4 → 中位數 4 → 門檻 0.8
    assert cl.STATE_UNSTABLE in cl.classify(_inp(_q(), eps_nc=0.7)).state
    assert cl.STATE_UNSTABLE not in cl.classify(_inp(_q(), eps_nc=0.8)).state


def _turn_q():
    """一般股轉機：營收 1000；營業利益 100，idx 36..39 −100，idx 40..43 −80、−40、20、60。
    TTM op：idx41 −320、idx42 −200、idx43 −40（連 2 季上升）；最新季 60 > 0。
    最新 4 季 eps −0.8、−0.4、0.2、0.6 → 合計 −0.4。"""
    op = [100.0] * 36 + [-100.0] * 4 + [-80.0, -40.0, 20.0, 60.0]
    return _q(op=op)


def test_轉機_非循環():
    c = cl.classify(_inp(_turn_q(), g3=0.05))
    assert c.type == cl.TYPE_NORMAL
    assert c.state[:3] == [cl.STATE_LOSS, cl.STATE_UNSTABLE, cl.STATE_TURNAROUND]
    assert cl.display_type(c) == "轉機"


def test_g3不大於0_不算轉機():
    c = cl.classify(_inp(_turn_q(), g3=0.0))
    assert cl.STATE_TURNAROUND not in c.state


def test_g3為NaN_不算轉機():
    assert cl.STATE_TURNAROUND not in cl.classify(_inp(_turn_q())).state


def test_轉機條件_循環類改稱谷底回升_不被覆蓋():
    c = cl.classify(_inp(_cyc_trough_q(turn=True), oroa_amp_pct=0.9, rev_beta=1.6, g3=0.05))
    assert c.type == cl.TYPE_CYCLICAL
    assert cl.STATE_TROUGH_RECOVERY in c.state and cl.STATE_TURNAROUND not in c.state
    assert cl.STATE_LOSS in c.state
    assert cl.display_type(c) == "景氣循環"


def test_歷史高獲利區_非循環類不得稱景氣高檔():
    op = [100.0] * 43 + [200.0]                               # 最新 OROA 0.125，40 季唯一最高 → 分位 1.0
    ind = pd.Series(0.1, index=pd.date_range("2016-01-01", "2025-12-01", freq="MS"))
    c = cl.classify(_inp(_q(op=op), industry_rev_ttm_yoy=ind))
    assert cl.STATE_PROFIT_HIGH in c.state
    assert cl.STATE_CYCLE_HIGH not in c.state
    assert c.metrics["oroa_pct_self"] == pytest.approx(1.0)


def test_歷史低獲利區():
    op = [100.0] * 43 + [50.0]
    assert cl.STATE_PROFIT_LOW in cl.classify(_inp(_q(op=op))).state


def test_循環類_涵蓋完整_產業同向_疑似景氣高檔():
    # 最後 4 季營業利益 300 → 最新 OROA 0.3，唯一最高；涵蓋 0.2→0→0.3 完整
    ind = pd.Series(0.1, index=pd.date_range("2016-01-01", "2025-12-01", freq="MS"))
    c = cl.classify(_inp(_cyc_q(tail_op=[300.0] * 4), oroa_amp_pct=0.9, rev_beta=1.6,
                         industry_rev_ttm_yoy=ind))
    assert c.type == cl.TYPE_CYCLICAL and c.metrics["coverage"] is True
    assert cl.STATE_PROFIT_HIGH in c.state and cl.STATE_CYCLE_HIGH in c.state


def test_循環類_產業指數反向_不稱景氣高檔():
    ind = pd.Series(-0.1, index=pd.date_range("2016-01-01", "2025-12-01", freq="MS"))
    c = cl.classify(_inp(_cyc_q(tail_op=[300.0] * 4), oroa_amp_pct=0.9, rev_beta=1.6,
                         industry_rev_ttm_yoy=ind))
    assert cl.STATE_PROFIT_HIGH in c.state and cl.STATE_CYCLE_HIGH not in c.state


def test_前瞻擴張():
    c = cl.classify(_inp(_q(), eps_nc=4.5, eps_f4=4.6))      # 4.5/4 − 1＝12.5% ≥ 10%
    assert cl.STATE_FWD_EXPAND in c.state


def test_前瞻擴張_F4低於NC_不成立():
    assert cl.STATE_FWD_EXPAND not in cl.classify(_inp(_q(), eps_nc=4.5, eps_f4=4.3)).state


def test_前瞻擴張_不到10趴_不成立():
    assert cl.STATE_FWD_EXPAND not in cl.classify(_inp(_q(), eps_nc=4.2, eps_f4=4.6)).state


def test_metrics帶asof與stay_ok():
    c = cl.classify(_inp(_q()))
    assert c.metrics["asof"] == pd.Timestamp("2025-12-31")
    assert isinstance(c.metrics["stay_ok"], dict)


# ── 遲滯 ────────────────────────────────────────────

Q = pd.date_range("2024-03-31", periods=12, freq="QE")      # Q[0]＝2024Q1 … Q[11]＝2026Q4


def _cls(t, i, state=None, stay_ok=None):
    return cl.Classification(type=t, state=list(state or []),
                             metrics={"asof": Q[i], "stay_ok": stay_ok or {}})


def _hist(rows):
    """rows: (季序號, candidate_type, final_type, switched[, candidate_states])"""
    out = []
    for r in rows:
        i, cand, fin, sw = r[:4]
        cs = r[4] if len(r) > 4 else ""
        out.append({"ticker": "T", "decided_at": Q[i], "candidate_type": cand, "final_type": fin,
                    "switched": sw, "candidate_states": cs, "final_states": ""})
    return pd.DataFrame(out, columns=list(cl.HISTORY_COLS))


N, G = cl.TYPE_NORMAL, cl.TYPE_GROWTH


def test_遲滯_無歷史_直接採用():
    r = cl.apply_hysteresis(_cls(G, 0), _hist([]))
    assert r.type == G and r.metrics["switched"] is False and r.metrics["last_switch"] is None


def test_連續1季門檻外_不切換():
    h = _hist([(i, N, N, False) for i in range(6)])
    r = cl.apply_hysteresis(_cls(G, 6), h)
    assert r.type == N
    assert r.metrics["candidate_type"] == G and r.metrics["switched"] is False
    assert "本季判定為高成長，未連續 2 季，維持一般" in r.why


def test_連續2季才切換_切後鎖4季():
    h = _hist([(i, N, N, False) for i in range(5)] + [(5, G, N, False)])
    r = cl.apply_hysteresis(_cls(G, 6), h)
    assert r.type == G and r.metrics["switched"] is True and r.metrics["last_switch"] == Q[6]
    assert r.metrics["locked_until"] == Q[9]                  # 含切換當季共 4 季：Q6..Q9


def test_鎖定期內_連2季也不切():
    # Q5 切成高成長；Q6、Q7 候選一般；Q8 仍在鎖定（Q5..Q8）
    h = _hist([(i, N, N, False) for i in range(4)]
              + [(4, G, N, False), (5, G, G, True), (6, N, G, False), (7, N, G, False)])
    r = cl.apply_hysteresis(_cls(N, 8), h)
    assert r.type == G and r.metrics["switched"] is False
    assert "切換後鎖定中（至 2026Q1），維持高成長" in r.why


def test_鎖定期滿_連2季即切():
    h = _hist([(i, N, N, False) for i in range(4)]
              + [(4, G, N, False), (5, G, G, True), (6, N, G, False), (7, N, G, False),
                 (8, N, G, False)])
    r = cl.apply_hysteresis(_cls(N, 9), h)                    # Q9 ≥ Q5 + 4 季
    assert r.type == N and r.metrics["switched"] is True


def test_留任門檻_高成長CAGR降到15_不退出():
    h = _hist([(0, G, G, True)] + [(i, G, G, False) for i in range(1, 5)])
    r = cl.apply_hysteresis(_cls(N, 5, stay_ok={G: True}), h)
    assert r.type == G
    assert r.metrics["candidate_type"] == G and r.metrics["raw_type"] == N
    assert "高成長留任：3 年營收 CAGR 仍 ≥ 12%" in r.why


def test_跌破留任門檻_仍要連2季():
    h = _hist([(0, G, G, True)] + [(i, G, G, False) for i in range(1, 5)])
    r = cl.apply_hysteresis(_cls(N, 5, stay_ok={G: False}), h)
    assert r.type == G and r.metrics["candidate_type"] == N


def test_金融_不受遲滯():
    h = _hist([(i, N, N, False) for i in range(3)])
    r = cl.apply_hysteresis(_cls(cl.TYPE_FINANCIAL, 3), h)
    assert r.type == cl.TYPE_FINANCIAL and r.metrics["switched"] is True


def test_季別不連續_不算連續2季():
    h = _hist([(i, N, N, False) for i in range(4)] + [(4, G, N, False)])
    r = cl.apply_hysteresis(_cls(G, 6), h)                    # 跳過 Q5
    assert r.type == N


def test_同季重判_報錯():
    h = _hist([(0, N, N, False)])
    with pytest.raises(ValueError):
        cl.apply_hysteresis(_cls(G, 0), h)


def test_history缺欄_報錯():
    h = _hist([(0, N, N, False)]).drop(columns=["candidate_states"])
    with pytest.raises(ValueError):
        cl.apply_hysteresis(_cls(G, 1), h)


def test_狀態虧損立即生效_其他要連2次():
    h = _hist([(0, N, N, False, "")])
    r = cl.apply_hysteresis(_cls(N, 1, state=[cl.STATE_LOSS, cl.STATE_PROFIT_LOW]), h)
    assert r.state == [cl.STATE_LOSS]


def test_其他狀態連2次一致才生效():
    h = _hist([(0, N, N, False, cl.STATE_PROFIT_HIGH)])
    r = cl.apply_hysteresis(_cls(N, 1, state=[cl.STATE_PROFIT_HIGH]), h)
    assert r.state == [cl.STATE_PROFIT_HIGH]


def test_首次判定_狀態直接採用():
    # 2026-11-01 起：首次出現的 ticker 類型與狀態都直接採用（原本只放行立即狀態）
    r = cl.apply_hysteresis(_cls(N, 0, state=[cl.STATE_LOSS, cl.STATE_TURNAROUND]), _hist([]))
    assert r.state == [cl.STATE_LOSS, cl.STATE_TURNAROUND]
    assert r.metrics["switched"] is False and r.metrics["last_switch"] is None
    assert r.metrics["locked_until"] is None


def test_有歷史_狀態仍需連2季():
    h = _hist([(0, N, N, False, "")])
    r = cl.apply_hysteresis(_cls(N, 1, state=[cl.STATE_TURNAROUND]), h)
    assert r.state == []


def test_遲滯不改動輸入():
    new = _cls(G, 6)
    h = _hist([(i, N, N, False) for i in range(6)])
    cl.apply_hysteresis(new, h)
    assert new.type == G and "switched" not in new.metrics


# ── 顯示名 ──────────────────────────────────────────

@pytest.mark.parametrize("t,state,expected", [
    (cl.TYPE_NORMAL, [cl.STATE_LOSS], "轉機"),
    (cl.TYPE_GROWTH, [cl.STATE_TURNAROUND], "轉機"),
    (cl.TYPE_NORMAL, [], "一般"),
    (cl.TYPE_GROWTH, [], "高成長"),
    (cl.TYPE_CYCLICAL, [cl.STATE_LOSS], "景氣循環"),
    (cl.TYPE_FINANCIAL, [cl.STATE_LOSS], "金融"),
    (cl.TYPE_SPECIAL, [cl.STATE_LOSS], "特殊"),
    (cl.TYPE_INSUFFICIENT, [], "資料不足"),
])
def test_顯示類型_覆蓋規則(t, state, expected):
    assert cl.display_type(cl.Classification(type=t, state=state)) == expected
