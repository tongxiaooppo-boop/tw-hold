"""build_classification：assemble_inputs（合成資料）與 main（--out tmp_path）。"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

import build_classification as bc
from screener import classify as cl


def _quarterly(tickers, n=16, start="2021-03-31"):
    ends = pd.date_range(start, periods=n, freq="QE")
    rows = []
    for t in tickers:
        for i, pe in enumerate(ends):
            ytd_mult = (pe.month // 3)                      # 年初累計：Q1=1 … Q4=4
            rows.append({"ticker": t, "period_end": pe, "revenue": 100.0 + i, "op_income": 10.0 + i % 3,
                         "eps": 1.0, "total_assets": 1000.0, "capital_stock": 100.0,
                         "capex": -5.0 * ytd_mult, "ni_parent": 8.0})
    return pd.DataFrame(rows)


def _monthly(tickers, n=48, start="2021-01"):
    months = pd.period_range(start, periods=n, freq="M").astype(str)
    rows = [{"ticker": t, "month": m, "revenue": 100.0 + i, "announced": pd.NaT}
            for t in tickers for i, m in enumerate(months)]
    return pd.DataFrame(rows)


def _universe(tickers, industry="半導體業"):
    return pd.DataFrame({"ticker": tickers, "stock_name": [f"名{t}" for t in tickers],
                         "industry": industry, "in_universe": True})


TK = ["1001", "1002", "1003", "1004", "1005", "1006"]


def test_組輸入_每檔都有ClassInputs且欄位齊全():
    out = bc.assemble_inputs(_quarterly(TK), _monthly(TK), _universe(TK))
    assert set(out) == set(TK)
    inp = out["1001"]
    assert isinstance(inp, cl.ClassInputs)
    assert list(inp.quarters.columns) == list(cl.QUARTER_COLS)
    assert isinstance(inp.quarters.index, pd.DatetimeIndex) and len(inp.quarters) == 16
    assert inp.industry_group == "other"
    assert len(inp.market_rev_ttm_yoy) > 0 and len(inp.stock_rev_ttm_yoy) > 0


def test_組輸入_有equity_parent時quarters也帶上():
    qdf = _quarterly(TK)
    qdf["equity_parent"] = 500.0
    out = bc.assemble_inputs(qdf, _monthly(TK), _universe(TK))
    assert "equity_parent" in out["1001"].quarters.columns
    assert list(out["1001"].quarters.columns[:len(cl.QUARTER_COLS)]) == list(cl.QUARTER_COLS)


def test_組輸入_capex累計會差分成單季():
    out = bc.assemble_inputs(_quarterly(TK), _monthly(TK), _universe(TK))
    capex = out["1001"].quarters["capex"].iloc[:4].tolist()
    # 累計 -5,-10,-15,-20 → 單季 -5 每季
    assert capex == [-5.0, -5.0, -5.0, -5.0]


def test_組輸入_代號後綴會正規化成裸代號():
    m = _monthly(TK)
    m["ticker"] = m["ticker"] + ".TW"
    out = bc.assemble_inputs(_quarterly(TK), m, _universe(TK))
    assert len(out["1001"].stock_rev_ttm_yoy) > 0


def test_組輸入_只輸出指定代號但橫斷面用全體():
    full = bc.assemble_inputs(_quarterly(TK), _monthly(TK), _universe(TK))
    part = bc.assemble_inputs(_quarterly(TK), _monthly(TK), _universe(TK), tickers=["1002"])
    assert set(part) == {"1002"}
    a, b = full["1002"].oroa_amp_pct, part["1002"].oroa_amp_pct
    assert (np.isnan(a) and np.isnan(b)) or a == b


def test_組輸入_單檔缺月營收或缺季報不會炸():
    q = _quarterly(TK)
    m = _monthly(TK[:-1])                                  # 1006 沒有月營收
    uni = _universe(TK + ["9999"])                         # 9999 沒有季報
    skipped: dict = {}
    out = bc.assemble_inputs(q, m, uni, skipped=skipped)
    assert "1006" in out and len(out["1006"].stock_rev_ttm_yoy) == 0
    assert np.isnan(out["1006"].g3)
    assert "9999" not in out and "9999" in skipped


def test_組輸入_金融業分組與asof截斷():
    uni = _universe(TK)
    uni.loc[0, "industry"] = "金融保險"
    out = bc.assemble_inputs(_quarterly(TK), _monthly(TK), uni, asof=pd.Timestamp("2023-12-31"))
    assert out["1001"].industry_group == "financial"
    assert out["1001"].quarters.index.max() == pd.Timestamp("2023-12-31")


@pytest.fixture
def fake_data(monkeypatch, tmp_path):
    q, m, u = _quarterly(TK), _monthly(TK), _universe(TK)
    pq = tmp_path / "rev.parquet"
    pu = tmp_path / "uni.parquet"
    m.to_parquet(pq)
    u.to_parquet(pu)
    monkeypatch.setattr(bc, "REVENUE", pq)
    monkeypatch.setattr(bc, "UNIVERSE", pu)
    import reference.loader as loader
    monkeypatch.setattr(loader, "load_quarterly", lambda: q)
    return tmp_path


def test_主程式_寫出JSON且數值JSON安全(fake_data, capsys):
    out = fake_data / "sc.json"
    rc = bc.main(["--out", str(out), "--no-history"])
    assert rc == 0
    txt = out.read_text(encoding="utf-8")
    assert "NaN" not in txt and "Infinity" not in txt
    d = json.loads(txt)
    assert d["count"] == len(TK)
    s = d["stocks"][0]
    for k in ("ticker", "name", "industry", "industry_group", "type", "display_type", "state",
              "subtags", "why", "reasons_degrade", "metrics", "rule_version", "decided_at"):
        assert k in s
    assert s["name"].startswith("名")
    assert not (fake_data / "class_history.parquet").exists()


def test_主程式_指定代號只輸出這幾檔並寫遲滯紀錄(fake_data, capsys):
    out = fake_data / "sc.json"
    assert bc.main(["--out", str(out), "--tickers", "1001,1003"]) == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    assert sorted(s["ticker"] for s in d["stocks"]) == ["1001", "1003"]
    h = pd.read_parquet(fake_data / "class_history.parquet")
    assert list(h.columns) == list(cl.HISTORY_COLS) and len(h) == 2
    # 同季再跑一次：應取代而非重複、不拋例外
    assert bc.main(["--out", str(out), "--tickers", "1001,1003"]) == 0
    assert len(pd.read_parquet(fake_data / "class_history.parquet")) == 2
    assert "1001" in capsys.readouterr().out


def test_主程式_單檔分類例外只略過不拖垮整批(fake_data, monkeypatch, capsys):
    real = cl.classify

    def boom(inp):
        if inp.ticker == "1002":
            raise ValueError("故意壞")
        return real(inp)

    monkeypatch.setattr(cl, "classify", boom)
    out = fake_data / "sc.json"
    assert bc.main(["--out", str(out), "--no-history"]) == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["count"] == len(TK) - 1
    assert "1002" not in {s["ticker"] for s in d["stocks"]}
    assert "略過 1002" in capsys.readouterr().out


def test_主程式_整批零檔不寫檔且回傳1(fake_data, monkeypatch):
    def boom(inp):
        raise ValueError("全壞")

    monkeypatch.setattr(cl, "classify", boom)
    out = fake_data / "sc.json"
    assert bc.main(["--out", str(out), "--no-history"]) == 1
    assert not out.exists()


# ---- 季更閘門 new_quarter_ready ----
def _uni(tickers):
    return pd.DataFrame({"ticker": tickers})


def test_gate_coverage_ok_and_newer_than_snapshot():
    tk = [f"{1000 + i}" for i in range(100)]
    q = _quarterly(tk, n=4, start="2025-12-31")            # 最新季 2026-09-30，100% 涵蓋
    ok, why, latest = bc.new_quarter_ready(q, _uni(tk), pd.Timestamp("2026-06-30"), today="2026-11-14")
    assert ok and latest == pd.Timestamp("2026-09-30")


def test_gate_partial_coverage_waits():
    tk = [f"{1000 + i}" for i in range(100)]
    q = _quarterly(tk, n=3, start="2025-12-31")            # 到 2026-06-30 全有
    extra = _quarterly(tk[:50], n=1, start="2026-09-30")   # 2026-09-30 只有一半公司公布
    q = pd.concat([q, extra], ignore_index=True)
    ok, why, latest = bc.new_quarter_ready(q, _uni(tk), pd.Timestamp("2026-06-30"))
    assert not ok and "不分型" in why and latest == pd.Timestamp("2026-09-30")


def test_gate_snapshot_already_latest_skips():
    tk = [f"{1000 + i}" for i in range(10)]
    q = _quarterly(tk, n=4, start="2025-12-31")
    ok, why, _ = bc.new_quarter_ready(q, _uni(tk), pd.Timestamp("2026-09-30"))
    assert not ok and "已是最新季" in why


def test_gate_no_snapshot_only_checks_coverage():
    tk = [f"{1000 + i}" for i in range(10)]
    q = _quarterly(tk, n=4, start="2025-12-31")
    ok, _, _ = bc.new_quarter_ready(q, _uni(tk), None)
    assert ok


def test_gate_ticker_suffix_normalized():
    q = _quarterly(["2330.TW", "2317.TW"], n=2, start="2026-06-30")
    ok, _, _ = bc.new_quarter_ready(q, _uni(["2330", "2317"]), pd.Timestamp("2026-03-31"))
    assert ok


def test_gate_waits_until_rebalance_day():
    tk = [f"{1000 + i}" for i in range(10)]
    q = _quarterly(tk, n=4, start="2025-12-31")            # 最新季 2026-09-30，100% 涵蓋，換股日 11/14
    ok, why, _ = bc.new_quarter_ready(q, _uni(tk), pd.Timestamp("2026-06-30"), today="2026-11-13")
    assert not ok and "未到換股日" in why
    ok, _, _ = bc.new_quarter_ready(q, _uni(tk), pd.Timestamp("2026-06-30"), today="2026-11-14")
    assert ok


def test_gate_after_rebalance_but_low_coverage_says_so():
    tk = [f"{1000 + i}" for i in range(100)]
    q = pd.concat([_quarterly(tk, n=3, start="2025-12-31"), _quarterly(tk[:80], n=1, start="2026-09-30")],
                  ignore_index=True)
    ok, why, _ = bc.new_quarter_ready(q, _uni(tk), pd.Timestamp("2026-06-30"), today="2026-11-20")
    assert not ok and "不分型" in why


def test_rebalance_dates_match_build_lists():
    import build_lists as bl
    got = sorted((v[0], v[1]) for v in bc.REBALANCE_FOR_QUARTER.values())
    assert got == sorted(bl.REBALANCE_MD)
    assert bc.rebalance_date_for("2026-12-31") == pd.Timestamp("2027-03-31")
