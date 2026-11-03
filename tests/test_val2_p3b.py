"""估值 2.0 P3b（docs/val2/P3b_spec.md）：預期值由 Opus 定，實作者不得改。"""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd

import build_classification as bc
import screener.classify as cl
from reference.loader import merge_statements
from screener.candidate_pool import _invalidation, canslim_fundamental

NAN = float("nan")


# ── 1 loader：歸母淨利頂替 ────────────────────────────────────

def _stmts():
    pe = pd.Timestamp("2026-06-30")
    inc = pd.DataFrame({
        "ticker": ["A", "B", "C", "D", "E"], "period_end": [pe] * 5,
        "eps": [1.0] * 5,
        "equity_parent": [NAN, NAN, 90.0, NAN, NAN],      # 損益表的歸母淨利（loader 改名 ni_parent）
        "net_income": [100.0, 100.0, 100.0, 100.0, NAN],
        "revenue": [1000.0] * 5,
    })
    bal = pd.DataFrame({
        "ticker": ["A", "B", "C", "E"], "period_end": [pe] * 4,
        "equity_parent": [NAN, 800.0, NAN, NAN],
        "equity": [1000.0, 1000.0, 1000.0, 1000.0],
        "total_assets": [5000.0] * 4,
    })
    cf = pd.DataFrame({"ticker": ["A", "B", "C", "D", "E"], "period_end": [pe] * 5, "ocf": [50.0] * 5})
    return inc, bal, cf


def _ni(q, t):
    return q.loc[q["ticker"] == t, "ni_parent"].iloc[0]


def test_歸母淨利缺且歸母權益也缺_用合併淨利():
    q = merge_statements(*_stmts())
    assert _ni(q, "A") == 100.0
    assert q.loc[q["ticker"] == "A", "equity_parent"].iloc[0] == 1000.0   # 權益照舊用權益總額補


def test_歸母淨利缺但歸母權益有值_不頂替():
    assert np.isnan(_ni(merge_statements(*_stmts()), "B"))


def test_歸母淨利缺且歸母權益等於權益總額_用合併淨利():
    inc, bal, cf = _stmts()
    bal.loc[bal["ticker"] == "B", "equity_parent"] = 1000.0          # 等於權益總額＝沒有非控制權益
    assert _ni(merge_statements(inc, bal, cf), "B") == 100.0


def test_歸母淨利有值_不動():
    assert _ni(merge_statements(*_stmts()), "C") == 90.0


def test_資產負債表沒有該季_用合併淨利():
    assert _ni(merge_statements(*_stmts()), "D") == 100.0


def test_合併淨利也缺_留NaN():
    assert np.isnan(_ni(merge_statements(*_stmts()), "E"))


def test_頂替不新增欄位():
    inc, bal, cf = _stmts()
    q = merge_statements(inc, bal, cf)
    assert not [c for c in q.columns if c.startswith("_")]
    assert q.columns[-1] == "ni_parent"


# ── 2 classify：死狀態、金融閘門、by_type、遲滯重算 ─────────────────

START = "2015-03-31"


def _q(n=44, rev=1000.0, op=100.0):
    idx = pd.DatetimeIndex(pd.date_range(START, periods=n, freq="QE"), name="period_end")
    return pd.DataFrame({"revenue": [rev] * n, "op_income": [op] * n, "eps": [op / 100] * n,
                         "total_assets": [4000.0] * n, "capital_stock": [1000.0] * n,
                         "capex": [-50.0] * n}, index=idx)


def _inp(q, **kw):
    base = dict(ticker="T", industry_group="other", quarters=q, oroa_amp_pct=0.5,
                asset_ta_rev_pct=0.5, asset_capex_rev_pct=0.5, rev_beta=1.0, ind_sync=0.3)
    base.update(kw)
    return cl.ClassInputs(**base)


def _cyc_q():
    """高→低→高：營收 1000／700（第 12～23 季）／1000；營業利益 200／0／200（同 test_classify._cyc_q）。"""
    n = 44
    rev = [1000.0] * n
    op = [200.0] * n
    for i in range(12, 24):
        rev[i], op[i] = 700.0, 0.0
    q = _q(n)
    q["revenue"], q["op_income"], q["eps"] = rev, op, [o / 100 for o in op]
    return q


def test_死狀態已刪除():
    for name in ("STATE_FWD_LOSS", "STATE_FWD_EXPAND", "FWD_EXPAND_MIN", "UNSTABLE_EPSNC_REL"):
        assert not hasattr(cl, name), name
    fields = {f.name for f in dataclasses.fields(cl.ClassInputs)}
    assert not {"eps_nc", "eps_f4"} & fields
    assert cl.RULE_VERSION == "class-v2-2026-11-02"


def test_金融股沒有營收_仍判金融():
    q = _q()
    q["revenue"] = NAN
    c = cl.classify(_inp(q, industry_group="financial"))
    assert c.type == cl.TYPE_FINANCIAL
    assert c.metrics["n_quarters"] == 44
    assert c.metrics["by_type"] == {}


def test_金融股EPS不足12季_資料不足():
    q = _q()
    q["revenue"] = NAN
    q.iloc[:36, q.columns.get_loc("eps")] = NAN
    c = cl.classify(_inp(q, industry_group="financial"))
    assert c.type == cl.TYPE_INSUFFICIENT
    assert c.why[0] == "單季財報僅 8 季（< 12 季），不分類"


def test_非金融沒有營收_資料不足():
    q = _q()
    q["revenue"] = NAN
    assert cl.classify(_inp(q)).type == cl.TYPE_INSUFFICIENT


def _own(c):
    return {"subtags": c.subtags, "state": c.state, "reasons_degrade": c.reasons_degrade}


def test_by_type_一般股_三類都有且與本身一致():
    c = cl.classify(_inp(_q()))
    assert c.type == cl.TYPE_NORMAL
    bt = c.metrics["by_type"]
    assert set(bt) == {cl.TYPE_CYCLICAL, cl.TYPE_GROWTH, cl.TYPE_NORMAL}
    assert bt[cl.TYPE_NORMAL] == _own(c)
    assert {cl.SUB_ASSET_HEAVY, cl.SUB_ASSET_LIGHT} & set(bt[cl.TYPE_CYCLICAL]["subtags"])


def test_by_type_循環股_一般那份不帶循環副標():
    c = cl.classify(_inp(_cyc_q(), oroa_amp_pct=0.9, rev_beta=1.6))
    assert c.type == cl.TYPE_CYCLICAL
    bt = c.metrics["by_type"]
    assert bt[cl.TYPE_CYCLICAL] == _own(c)
    assert cl.SUB_ASSET_LIGHT in bt[cl.TYPE_CYCLICAL]["subtags"]
    assert not {cl.SUB_ASSET_HEAVY, cl.SUB_ASSET_LIGHT} & set(bt[cl.TYPE_NORMAL]["subtags"])
    assert not {cl.SUB_ASSET_HEAVY, cl.SUB_ASSET_LIGHT} & set(bt[cl.TYPE_GROWTH]["subtags"])


Q = pd.date_range("2024-03-31", periods=12, freq="QE")
C, N = cl.TYPE_CYCLICAL, cl.TYPE_NORMAL


def _hist(rows):
    """rows: (季序號, candidate_type, final_type, switched, candidate_states)"""
    return pd.DataFrame([{"ticker": "T", "decided_at": Q[i], "candidate_type": cand, "final_type": fin,
                          "switched": sw, "candidate_states": cs, "final_states": ""}
                         for i, cand, fin, sw, cs in rows], columns=list(cl.HISTORY_COLS))


def _new_normal(i, by_type=True):
    m = {"asof": Q[i], "stay_ok": {}}
    if by_type:
        m["by_type"] = {
            C: {"subtags": [cl.SUB_ASSET_HEAVY], "state": [cl.STATE_TROUGH_RECOVERY],
                "reasons_degrade": ["循環未觀察完整"]},
            N: {"subtags": [cl.SUB_SHRINKING], "state": [cl.STATE_TURNAROUND],
                "reasons_degrade": ["一般的降級"]},
            cl.TYPE_GROWTH: {"subtags": [], "state": [cl.STATE_TURNAROUND], "reasons_degrade": []},
        }
    return cl.Classification(type=N, state=[cl.STATE_TURNAROUND], subtags=[cl.SUB_SHRINKING],
                             reasons_degrade=["一般的降級"], metrics=m)


def test_遲滯維持循環_子分類與狀態照循環重算():
    # 前一季候選已是一般（狀態「轉機」）；離開循環要連 4 季，本季只第 2 季 → 維持循環
    h = _hist([(i, C, C, False, "") for i in range(5)] + [(5, N, C, False, cl.STATE_TURNAROUND)])
    r = cl.apply_hysteresis(_new_normal(6), h)
    assert r.type == C
    assert r.subtags == [cl.SUB_ASSET_HEAVY]
    assert r.reasons_degrade == ["循環未觀察完整"]
    assert r.state == [cl.STATE_TROUGH_RECOVERY]          # 轉機／谷底回升視為同一狀態延續
    assert r.metrics["subtags_recomputed"] is True


def test_遲滯沒有by_type_沿用原欄位():
    h = _hist([(i, C, C, False, "") for i in range(5)] + [(5, N, C, False, "")])
    r = cl.apply_hysteresis(_new_normal(6, by_type=False), h)
    assert r.type == C
    assert r.subtags == [cl.SUB_SHRINKING]
    assert r.metrics["subtags_recomputed"] is False


def test_遲滯最終等於候選_不重算():
    h = _hist([(i, N, N, False, "") for i in range(6)])
    r = cl.apply_hysteresis(_new_normal(6), h)
    assert r.type == N and r.subtags == [cl.SUB_SHRINKING]
    assert r.metrics["subtags_recomputed"] is False


# ── 3 build_classification：金融有效檔、coverage_mktcap_k ─────────────

def test_有效檔_金融股不需要營收():
    pe = pd.Timestamp("2026-06-30")
    q = pd.DataFrame({"ticker": ["2881", "1101", "2330"], "period_end": [pe] * 3,
                      "eps": [4.27, 1.0, 10.0], "revenue": [NAN, NAN, 1e9], "ni_parent": [5e10, 1e8, 1e11]})
    assert bc._valid_tickers(q, pe, financial={"2881"}) == {"2881", "2330"}
    assert bc._valid_tickers(q, pe) == {"2330"}


def test_金融股集合_由universe產業判斷():
    uni = pd.DataFrame({"ticker": ["2881.TW", "2330.TW"], "industry": ["金融保險", "半導體業"]})
    assert bc._financial_set(uni) == {"2881"}
    assert bc._financial_set(uni.drop(columns=["industry"])) == set()


def _uni(ranks):
    return pd.DataFrame({"ticker": [f"{t}.TW" for t in "abcdef"][:len(ranks)], "mktcap_rank": ranks})


def test_coverage_k_連續涵蓋到第3名():
    assert bc.coverage_mktcap_k(_uni([1, 2, 3, 4, 5]), {"a", "b", "c", "e"}) == 3


def test_coverage_k_第1名不在_為0():
    assert bc.coverage_mktcap_k(_uni([1, 2, 3]), {"b", "c"}) == 0


def test_coverage_k_rank缺值略過_沒有欄位回None():
    assert bc.coverage_mktcap_k(_uni([1, NAN, 2]), {"a", "c"}) == 2
    assert bc.coverage_mktcap_k(_uni([1, 2]).drop(columns=["mktcap_rank"]), {"a"}) is None


def test_coverage_顯示捨去到百位():
    assert bc._floor_hundred(801) == 800 and bc._floor_hundred(1000) == 1000
    assert bc._floor_hundred(99) == 99 and bc._floor_hundred(None) is None


# ── 4 candidate_pool：季 EPS 年增改用 growth ───────────────────────

ASOF = pd.Timestamp("2026-09-07")


def _qf(eps_now, eps_ago):
    rows = []
    for i in range(20):
        pe = pd.Timestamp("2021-12-31") + pd.DateOffset(months=3 * i)
        e = eps_ago if i < 16 else eps_now
        rows.append(dict(ticker="1001", period_end=pe, disclosure_date=pe + pd.Timedelta(days=45),
                         eps=e, ttm_eps=e * 4, roe=0.25, f_score=8, gross_margin=0.3))
    return pd.DataFrame(rows)


def test_推薦卡_虧損擴大不過門檻():
    f = canslim_fundamental(_qf(-4.0, -2.0), ASOF).loc["1001"]
    assert f["c_eps_yoy"] == False                                   # noqa: E712
    assert f["eps_yoy_label"] == "loss_wider"
    assert np.isnan(f["eps_yoy_q"])


def test_推薦卡_基期低含五分之一規則():
    f = canslim_fundamental(_qf(12.0, 2.0), ASOF).loc["1001"]       # 2 < 12/5
    assert f["eps_yoy_low_base"] == True                             # noqa: E712
    assert f["c_eps_yoy"] == True                                    # noqa: E712
    assert f["eps_yoy_q"] == 5.0


def _rec(**kw):
    base = dict(dist_50ma=0.1, trend_cnt=8, revenue_yoy=0.1, revenue_accel=None,
                eps_yoy_q=None, eps_yoy_base=1.0, eps_yoy_label="pct")
    base.update(kw)
    return base


def _eps_inval(rec):
    return _invalidation(rec)[-1]["目前"]


def test_失效條件_季EPS轉負():
    assert _eps_inval(_rec(eps_yoy_label="turn_loss")) == "已轉負"
    assert _eps_inval(_rec(eps_yoy_label="pct", eps_yoy_q=-0.3)) == "已轉負"
    assert _eps_inval(_rec(eps_yoy_label="flat", eps_yoy_base=1.0)) == "已轉負"
    assert _eps_inval(_rec(eps_yoy_label="flat", eps_yoy_base=-1.0)) == "未觸發"
    assert _eps_inval(_rec(eps_yoy_label="loss_wider", eps_yoy_base=-2.0)) == "未觸發"
    assert _eps_inval(_rec(eps_yoy_label="pct", eps_yoy_q=0.3)) == "未觸發"


def test_失效條件_舊JSON沒有label():
    rec = _rec(eps_yoy_q=-0.2)
    del rec["eps_yoy_label"]
    assert _eps_inval(rec) == "已轉負"
