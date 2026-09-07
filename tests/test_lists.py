"""M0.5：`build_factors.screen_all()` + `build_lists` 端到端——用合成 bundle。
不打網路、不碰真 bundle。"""

from __future__ import annotations

import importlib
import json

import pandas as pd
import pytest


def _synth_income(ticker: str, n: int = 32, grow: float = 0.03):
    rows = []
    for i in range(n):
        pe = pd.Timestamp("2018-03-31") + pd.DateOffset(months=3 * i)
        k = 1 + grow * (i // 4)
        rows.append(dict(ticker=ticker, period_end=pe, revenue=1000 * k, eps=2 * k,
                         net_income=200 * k, gross_profit=300 * k, op_income=200 * k,
                         pretax_income=180 * k, equity_parent=200 * k))
    return pd.DataFrame(rows)


def _synth_balance(ticker: str, n: int = 32, grow: float = 0.03):
    rows = []
    for i in range(n):
        pe = pd.Timestamp("2018-03-31") + pd.DateOffset(months=3 * i)
        k = 1 + grow * (i // 4)
        rows.append(dict(ticker=ticker, period_end=pe, capital_stock=1000.0, cash=500.0,
                         current_assets=2500.0, current_liabilities=1000.0,
                         equity=3000 * k, equity_parent=3000 * k,
                         total_liabilities=2000.0, total_assets=5000.0))
    return pd.DataFrame(rows)


def _synth_cashflow(ticker: str, n: int = 32, grow: float = 0.03):
    rows = []
    for i in range(n):
        pe = pd.Timestamp("2018-03-31") + pd.DateOffset(months=3 * i)
        k = 1 + grow * (i // 4)
        rows.append(dict(ticker=ticker, period_end=pe, ocf=250 * k, ocf_net=250 * k,
                         capex=80.0, icf=-50.0))
    return pd.DataFrame(rows)


def _synth_dividend(ticker: str, years=range(2018, 2026), amt: float = 3.0):
    rows = []
    for y in years:
        rows.append(dict(ticker=ticker, year=y, pay_date=pd.Timestamp(f"{y}-07-01"),
                         CashEarningsDistribution=amt, CashStatutorySurplus=0.0,
                         StockEarningsDistribution=0.0, AnnouncementDate=pd.NaT,
                         CashExDividendTradingDate=pd.Timestamp(f"{y}-06-25"),
                         CashDividendPaymentDate=pd.NaT))
    return pd.DataFrame(rows)


@pytest.fixture()
def bundle(tmp_path, monkeypatch):
    fund = tmp_path / "fundamentals"
    fund.mkdir(parents=True)
    tickers = ["1001", "1002", "1003"]
    pd.concat([_synth_income(t) for t in tickers]).to_parquet(fund / "income.parquet")
    pd.concat([_synth_balance(t) for t in tickers]).to_parquet(fund / "balance.parquet")
    pd.concat([_synth_cashflow(t) for t in tickers]).to_parquet(fund / "cashflow.parquet")
    pd.concat([_synth_dividend(t) for t in tickers]).to_parquet(fund / "dividend.parquet")
    (tmp_path / "_meta.json").write_text(
        json.dumps({"schema_version": 1, "trading_date": "2026-09-02", "files": {}}))
    monkeypatch.setenv("TWHOLD_BUNDLE_DIR", str(tmp_path))
    import reference.loader as loader
    importlib.reload(loader)
    import build_factors
    importlib.reload(build_factors)
    import build_lists
    importlib.reload(build_lists)
    monkeypatch.setattr(build_lists, "DERIVED", tmp_path / "derived")
    return build_lists


def test_screen_all_無股價也能出兩清單(bundle):
    r = bundle.screen_all()
    assert set(r) == {"deposit", "value", "context"}
    assert not r["value"].empty and not r["deposit"].empty
    assert r["context"]["has_prices"] is False
    # 沒股價時 value_score 用品質排序、不是全 NaN
    ok = r["value"][r["value"]["passes"]]
    assert ok["value_score"].notna().any()


def test_build_lists_寫出三個_json_帶_changes(bundle):
    assert bundle.main() == 0
    d = bundle.DERIVED
    for name in ("value", "deposit", "swing"):
        p = d / f"{name}_list.json"
        assert p.exists()
        payload = json.loads(p.read_text(encoding="utf-8"))
        assert "_meta" in payload and "holdings" in payload and "changes" in payload
    meta = json.loads((d / "_meta.json").read_text(encoding="utf-8"))
    assert meta["trading_date"] == "2026-09-02"
    assert meta["u1b_pending"] is True


def test_changes_diff_對上一期(bundle):
    bundle.main()
    val = json.loads((bundle.DERIVED / "value_list.json").read_text(encoding="utf-8"))
    first = {h["ticker"] for h in val["holdings"]}
    assert val["changes"]["added"] == sorted(first)      # 第一次跑：全部都是新進
    bundle.main()                                        # 再跑一次
    val2 = json.loads((bundle.DERIVED / "value_list.json").read_text(encoding="utf-8"))
    assert val2["changes"]["added"] == [] and val2["changes"]["removed"] == []
