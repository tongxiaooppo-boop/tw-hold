"""第二批共用地基：曆季、比率、三表合併與事件表失敗。"""
import numpy as np
import pandas as pd
import pytest

import build_classification as bc
from factors.factors import quarterly_factors
from reference import corporate_actions as ca
from reference.loader import merge_statements
from screener import quarterly_prep as qp, val_card as vc, multiples as mu
from screener.candidate_pool import canslim_fundamental
from screener.detect import near_zero_eps


def _q(n=6, start="2025-03-31"):
    q = pd.DataFrame({"ticker": "1111", "period_end": pd.date_range(start, periods=n, freq="QE"),
                      "eps": np.arange(1, n + 1, dtype=float)})
    for col, value in dict(revenue=100., net_income=10., gross_profit=30., op_income=20.,
                           pretax_income=15., total_assets=1000., equity_parent=500.,
                           total_liabilities=500., current_assets=200., current_liabilities=100.,
                           ocf=12., ocf_net=12., capex=3., capital_stock=100.).items():
        q[col] = value
    q["disclosure_date"] = q["period_end"] + pd.Timedelta(days=45)
    return q


def _series():
    return _q().set_index("period_end")["eps"]


def test_last_n_quarters_連續才給():
    s = _series()
    pd.testing.assert_series_equal(qp.last_n_quarters(s, 4), s.iloc[-4:])


def test_last_n_quarters_缺季回None():
    s = _series().drop(pd.Timestamp("2025-12-31"))
    assert qp.last_n_quarters(s, 4) is None
    pd.testing.assert_series_equal(qp.last_n_quarters(s, 2), s.iloc[-2:])


def test_last_n_quarters_有NaN或不足回None():
    s = _series()
    assert qp.last_n_quarters(s, 7) is None
    s.iloc[-1] = np.nan
    assert qp.last_n_quarters(s, 4) is None
    for bad in (s.iloc[::-1], pd.concat([s, s.iloc[-1:]]), s.reset_index(drop=True)):
        with pytest.raises(ValueError):
            qp.last_n_quarters(bad, 4)
    with pytest.raises(ValueError):
        qp.last_n_quarters(s, 0)


def test_panel_ttm_缺季的窗都是NaN_重複季拋ValueError():
    q = _q(10).drop(index=3).sample(frac=1, random_state=1)
    result = qp.panel_ttm(q, "eps")
    assert result.index.equals(q.index)
    assert result.loc[[4, 5, 6]].isna().all()
    assert result.loc[7] == 26.
    assert qp.panel_ttm(q, "missing").isna().all()
    with pytest.raises(ValueError):
        qp.panel_ttm(pd.concat([q, q.iloc[-1:]]), "eps")


def test_panel_lag_用曆季不是列數():
    q = _q().drop(index=1).iloc[::-1]
    result = qp.panel_lag(q, "eps", 4)
    assert result.index.equals(q.index)
    assert np.isnan(result.loc[5])
    assert result.loc[4] == 1.
    with pytest.raises(ValueError):
        qp.panel_lag(pd.concat([q, q.iloc[-1:]]), "eps", 4)
    with pytest.raises(ValueError):
        qp.panel_lag(q, "eps", 0)


def test_factors_缺季TTM為NaN且重複季不重複加():
    q = _q()
    extra = q.iloc[-1:].assign(eps=60.)
    out = quarterly_factors(pd.concat([q, extra], ignore_index=True))
    assert len(out) == 6
    assert out.iloc[-1]["ttm_eps"] == 3 + 4 + 5 + 60
    assert np.isnan(quarterly_factors(q.drop(index=3)).iloc[-1]["ttm_eps"])


def test_factors_權益零或負ROE為NaN():
    q = _q()
    q.loc[4:, "equity_parent"] = [0., -1.]
    assert quarterly_factors(q).iloc[-2:]["roe"].isna().all()


def test_factors_比率無限大變NaN():
    q = _q()
    q.loc[5, ["equity_parent", "total_assets", "current_liabilities"]] = np.inf
    q.loc[5, "gross_profit"] = np.inf
    out = quarterly_factors(q).iloc[-1]
    assert out[["roe", "roa", "debt_ratio", "current_ratio", "asset_turnover", "gross_margin"]].isna().all()
    q = _q()
    q.loc[5, "total_liabilities"] = np.inf
    assert np.isnan(quarterly_factors(q).iloc[-1]["debt_ratio"])


def test_canslim_缺季時去年同季比較為NaN():
    q = quarterly_factors(_q().drop(index=1))
    result = canslim_fundamental(q, pd.Timestamp("2027-01-01")).loc["1111"]
    assert np.isnan(result["eps_yoy_base"])
    assert np.isnan(result["eps_yoy_q"])
    assert not result["c_eps_yoy"]


def test_val_card_近四季與三年EPS缺季回None():
    q = _q(14, "2023-03-31")
    assert vc._ttm_eps(q) == sum(range(11, 15))
    assert vc._avg3_eps(q) == sum(range(3, 15)) / 3
    gap = q.drop(index=12)
    assert vc._ttm_eps(gap) is None
    assert vc._avg3_eps(gap) is None
    out = vc._q(pd.concat([q, q.iloc[-1:].assign(eps=99.)]))
    assert len(out) == len(q) and out.iloc[-1]["eps"] == 99.


def test_near_zero_eps_缺季不跨窗():
    q = _q(24, "2020-03-31")
    q["eps"] = np.nan
    # 20 個有值的季分散成短段，只有最後四季連續，舊 rolling 會把高 EPS 跨缺季加總。
    q["eps"] = 100.
    q.loc[[3, 7, 11, 15], "eps"] = np.nan
    q.loc[16:, "eps"] = 1.
    assert q["eps"].count() == 20
    assert near_zero_eps(1., q).level == "ok"
    q.loc[16:, "eps"] = 100.
    assert near_zero_eps(1., q).level == "block"


def _inputs(q):
    return bc.assemble_inputs(q, pd.DataFrame(columns=["ticker", "month", "revenue"]),
                              pd.DataFrame({"ticker": ["1111"], "industry": ["半導體業"]}))


def test_組輸入_缺季補成NaN列且季度索引連續():
    quarters = _inputs(_q().drop(index=3))["1111"].quarters
    assert quarters.index.equals(pd.date_range("2025-03-31", periods=6, freq="QE", name="period_end"))
    assert quarters.iloc[3].isna().all()
    bc.cl.classify(_inputs(_q(24).drop(index=10))["1111"])


@pytest.fixture
def main_data(monkeypatch, tmp_path):
    import reference.loader as loader
    q = _q(16, "2021-03-31")
    m, u = tmp_path / "revenue.parquet", tmp_path / "universe.parquet"
    pd.DataFrame(columns=["ticker", "month", "revenue"]).to_parquet(m)
    pd.DataFrame({"ticker": ["1111"], "industry": ["半導體業"]}).to_parquet(u)
    monkeypatch.setattr(bc, "REVENUE", m)
    monkeypatch.setattr(bc, "UNIVERSE", u)
    monkeypatch.setattr(loader, "load_quarterly", lambda: q.copy())
    return q


def test_主程式_分類輸入用調整後EPS(main_data, monkeypatch, tmp_path):
    monkeypatch.setattr(ca, "adjust_eps", lambda q: q.assign(eps=q["eps"] * .1))
    real, seen = bc.cl.classify, []

    def capture(inp):
        np.testing.assert_allclose(inp.quarters["eps"], main_data["eps"] * .1)
        seen.append(inp.ticker)
        return real(inp)

    monkeypatch.setattr(bc.cl, "classify", capture)
    assert bc.main(["--out", str(tmp_path / "out.json"), "--no-history"]) == 0
    assert seen == ["1111"]


def test_multiples_無限大不算有效倍數():
    per = pd.DataFrame({"date": pd.to_datetime(["2026-01-01", "2026-01-30", "2026-02-28"]),
                        "per": [12., np.inf, -np.inf]})
    assert mu.month_end_values(per, "per").tolist() == [12.]
    assert mu.band(per, "per", years=None, min_months=2)["n_months"] == 1
    assert mu._number(np.inf) is None and mu._number(-np.inf) is None


@pytest.mark.parametrize("bad_event", ['{}', '{"date":null,"m":2}', '{"date":"2025-01-01","m":-1}'])
def test_事件檔單筆壞事件只略過其他照常(monkeypatch, tmp_path, capsys, bad_event):
    path = tmp_path / "events.json"
    path.write_text('{"events":{"1111":[' + bad_event + '],'
                    '"2222":[{"date":"2025-01-01","m":2.0,"type":"split"}]}}', encoding="utf-8")
    monkeypatch.setattr(ca, "_RESOLVED_PATH", path)
    out = ca._load_resolved()
    assert ca.EVENTS_OK and ca.EVENTS_ERROR is None
    assert list(out) == ["2222"]
    assert "格式不對已略過" in capsys.readouterr().err


@pytest.mark.parametrize("contents", [None, "{", "[]", '{"events": []}'])
def test_事件檔損壞_EVENTS_OK為False_val_card可信度低(monkeypatch, tmp_path, capsys, contents):
    path = tmp_path / "events.json"
    if contents is not None:
        path.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(ca, "_RESOLVED_PATH", path)
    monkeypatch.setattr(ca, "EVENTS_OK", True)
    monkeypatch.setattr(ca, "EVENTS_ERROR", None)
    q = _q(24, "2020-03-31")
    per = pd.DataFrame({"date": pd.date_range("2021-01-31", periods=60, freq="ME"), "per": 15.})
    args = (q, pd.DataFrame(), pd.DataFrame(), per, {"type": "normal"})
    before = vc.build_card(*args)
    assert before["confidence"]["level"] != "低"
    assert ca._load_resolved() == {}
    assert not ca.EVENTS_OK and ca.EVENTS_ERROR
    assert capsys.readouterr().err.count("警告：股數事件表讀取失敗：") == 1
    after = vc.build_card(*args)
    assert after["confidence"]["level"] == "低"
    assert after["prices"] == before["prices"]
    assert any(c["name"] == "股數事件表" and c["why"] == "股數事件表讀取失敗，股數還原可能失效"
               for c in after["checks"])
    path.write_text('{"events": {}}', encoding="utf-8")
    assert ca._load_resolved() == {} and ca.EVENTS_OK and ca.EVENTS_ERROR is None


def test_事件檔損壞_分類不寫檔回傳1(main_data, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ca, "EVENTS_OK", False)
    monkeypatch.setattr(ca, "EVENTS_ERROR", "JSON 損壞")
    out = tmp_path / "out.json"
    assert bc.main(["--out", str(out), "--no-history"]) == 1
    assert not out.exists() and "股數事件表讀取失敗" in capsys.readouterr().err


def _statements():
    key = dict(ticker=["1111"], period_end=["2026-06-30"])
    return (pd.DataFrame({**key, "equity_parent": [10.], "eps": [1.]}),
            pd.DataFrame({**key, "equity_parent": [500.], "equity": [600.]}), pd.DataFrame())


def test_merge_statements_權益只取資產負債表():
    result = merge_statements(*_statements()).iloc[0]
    assert result["equity_parent"] == 500. and result["ni_parent"] == 10.


def test_merge_statements_資產負債表缺權益時退equity不用淨利():
    inc, bal, cf = _statements()
    for frame in (bal.assign(equity_parent=np.nan), bal.drop(columns="equity_parent")):
        result = merge_statements(inc, frame, cf).iloc[0]
        assert result["equity_parent"] == 600. and result["ni_parent"] == 10.
    assert np.isnan(merge_statements(inc, pd.DataFrame(), cf).iloc[0]["equity_parent"])


def test_merge_statements_重複列去重():
    inc, bal, _ = _statements()
    cf = inc[["ticker", "period_end"]].assign(ocf=5.)
    result = merge_statements(pd.concat([inc, inc.assign(eps=2.)]),
                              pd.concat([bal, bal.assign(equity_parent=700.)]),
                              pd.concat([cf, cf.assign(ocf=6.)]))
    assert len(result) == 1
    assert result.iloc[0][["eps", "equity_parent", "ocf"]].tolist() == [2., 700., 6.]


def test_merge_statements_how_left保留損益表列():
    inc, bal, cf = _statements()
    bal = pd.concat([bal, bal.assign(period_end="2026-09-30")])
    assert len(merge_statements(inc, bal, cf, how="left")) == 1
    assert len(merge_statements(inc, bal, cf)) == 2


def test_bundle_financials_equity_parent是權益(monkeypatch):
    from app import bundle_data
    inc, bal, cf = _statements()
    tables = dict(zip(["income.parquet", "balance.parquet", "cashflow.parquet"], [inc, bal, cf]))
    monkeypatch.setattr(bundle_data, "_read", lambda name, *args: tables[name].copy())
    out = bundle_data.financials("1111")
    assert out.iloc[0]["equity_parent"] == 500.
    assert out.iloc[0]["ni_parent"] == 10.
