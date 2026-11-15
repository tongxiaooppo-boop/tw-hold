import pandas as pd

from reference import revenue_merge as rm


def _mops(tmp_path, rows):
    pd.DataFrame(rows).to_parquet(tmp_path / "2026-10.parquet")


def test_mops_months_過濾未來與無效值(tmp_path):
    _mops(tmp_path, dict(code=["1101", "1102", "1103", "1104"], period=["2026-10"] * 4,
                         revenue=[10.0, 20.0, 0.0, float("nan")],
                         first_seen_at=pd.to_datetime(["2026-11-02", "2026-11-09", "2026-11-02", "2026-11-02"])))
    out = rm.mops_months(tmp_path, pd.Timestamp("2026-11-03"))
    assert out.ticker.tolist() == ["1101"]
    assert len(rm.mops_months(tmp_path)) == 2   # asof=None 不過濾日期，仍排除 0／NaN


def test_mops_months_目錄不存在回空表(tmp_path):
    out = rm.mops_months(tmp_path / "無")
    assert out.empty and list(out.columns) == rm.MOPS_COLS


def _long():
    return pd.DataFrame(dict(ticker=["2402"], month=["2026-09"], revenue=[110.0],
                             announced=pd.to_datetime(["2026-10-05"])))


def test_fill_missing_months_長表優先():
    mops = pd.DataFrame(dict(ticker=["2402"], month=["2026-09"], revenue=[999.0],
                             first_seen_at=pd.to_datetime(["2026-10-06 01:00"])))
    out, n = rm.fill_missing_months(_long(), mops)
    assert n == 0 and out.revenue.tolist() == [110.0]


def test_fill_missing_months_補缺月與announced():
    mops = pd.DataFrame(dict(ticker=["2402"], month=["2026-10"], revenue=[120.0],
                             first_seen_at=pd.to_datetime(["2026-11-03 04:30"])))
    long = _long()
    out, n = rm.fill_missing_months(long, mops)
    assert n == 1 and out.month.tolist() == ["2026-09", "2026-10"]
    assert out.announced.iloc[-1] == pd.Timestamp("2026-11-03")
    assert (out.dtypes == long.dtypes).all() and list(out.columns) == list(long.columns)


def test_bundle_data_revenue_補mops缺月(tmp_path, monkeypatch):
    from app import bundle_data as bd
    _mops(tmp_path, dict(code=["2402"], period=["2026-10"], revenue=[120.0],
                         first_seen_at=pd.to_datetime(["2026-11-03 04:30"])))
    monkeypatch.setattr(rm, "MOPS_DIR_DEFAULT", tmp_path)
    monkeypatch.setattr(bd, "_read", lambda *a, **k: _long())
    out = bd.revenue("2402")
    assert out.revenue.tolist() == [110.0, 120.0]
    assert out.month.iloc[-1] == pd.Timestamp("2026-10-01")
