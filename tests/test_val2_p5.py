"""P5 官方股數接線、倍數更新及月收盤合併的離線驗收。"""
import os
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from app import val_inputs as vi
from build_multiples import _load_closes
from reference import corporate_actions as ca
from screener import detect as dt, val_card as vc
from test_val2_card import Q, REV, PX, CLS, MH, ASOF


@pytest.fixture(autouse=True)
def _events(monkeypatch):
    monkeypatch.setattr(ca, "SPLITS", {})
    monkeypatch.setattr(ca, "EVENTS_OK", True)


def basic(par=10.0, pref=0, asof=ASOF):
    return dict(par_value=par, preferred_shares=pref, asof=asof)


def checks(b=None, q=None):
    return {c.name: c for c in dt.share_checks("9999", Q() if q is None else q, ASOF, basic=b)}


def test_share_checks_basic_none():
    c = checks()["面額與特別股"]
    assert c.level == "unchecked" and "假設面額 10 元" in c.why


def test_share_checks_basic_ok():
    assert checks(basic())["面額與特別股"].level == "ok"


def test_share_checks_basic_stale():
    assert checks(basic(asof=ASOF - pd.Timedelta(days=31)))["面額與特別股"].level == "unchecked"
    assert checks(basic(asof=ASOF - pd.Timedelta(days=30)))["面額與特別股"].level == "ok"
    for par in (np.nan, np.inf, 0, -1):
        assert checks(basic(par=par))["面額與特別股"].level == "unchecked"


def test_share_checks_preferred_warn():
    c = checks(basic(pref=2e8))["面額與特別股"]
    assert c.level == "warn" and c.value == 2e8 and "2.00 億股" in c.why
    assert checks(basic(pref=np.nan))["面額與特別股"].level == "ok"


def capital_q(capital):
    q = Q()
    q.loc[q.index[-1], ["capital_stock", "ni_parent", "eps"]] = [capital, 1e9, 1.0]
    return q


def test_share_checks_preferred_capital():
    q = capital_q(1.2e10)
    c = checks(basic(pref=2e8), q)["股數對不上"]
    assert c.level == "ok" and c.value == pytest.approx(0)
    fallback = checks(None, q)["股數對不上"]
    assert fallback.level == "warn" and fallback.value == pytest.approx(1 / 6)


def test_share_checks_par_1():
    c = checks(basic(par=1.0), capital_q(1e9))["股數對不上"]
    assert c.level == "ok" and c.value == pytest.approx(0)


def test_build_card_passes_basic():
    card = vc.build_card(Q(), REV(), PX(), CLS(), MH(), None, None, ASOF, basic=basic(pref=2e8))
    assert any(c["name"] == "面額與特別股" and c["level"] == "warn"
               for c in card["status"]["share_basis"]["items"])


def test_card_inputs_basic(tmp_path, monkeypatch):
    for name in (vi.MH_FILE, vi.REV_FILE, vi.IND_FILE):
        (tmp_path / name).touch()
    monkeypatch.setattr(vi, "quarterly", lambda *args: Q())
    monkeypatch.setattr(vi, "load_mh", lambda *args: MH())
    monkeypatch.setattr(vi, "load_rev_hist", lambda *args: pd.DataFrame())
    monkeypatch.setattr(vi, "load_industry_pe", lambda *args: None)

    class Bundle:
        def read(self, name, code):
            return PX() if name == "prices_raw_close" else REV()

    b = basic()
    class Official(Bundle):
        def company_basic(self, code):
            assert code == "9999"
            return b

    assert vi.card_inputs("9999", ASOF, CLS(), tmp_path, Official())["basic"] is b
    assert vi.card_inputs("9999", ASOF, CLS(), tmp_path, Bundle())["basic"] is None
    assert vi._AppBundle(Official()).company_basic("9999") is b
    assert vi._AppBundle(Bundle()).company_basic("9999") is None


def test_ensure_multiples_missing(tmp_path):
    calls = []
    def fetch(url, path):
        calls.append((url, path))
        assert path.suffix == ".part"
        path.write_bytes(b"new")
    vi.ensure_multiples(tmp_path, now=100_000, fetch=fetch)
    assert len(calls) == 2
    assert {url.rsplit("/", 1)[1] for url, _ in calls} == {vi.MH_FILE, vi.REV_FILE}
    assert all((tmp_path / name).read_bytes() == b"new" for name in (vi.MH_FILE, vi.REV_FILE))
    assert not list(tmp_path.glob("*.part"))


def old_files(path, age):
    now = 100_000
    for name in (vi.MH_FILE, vi.REV_FILE):
        file = path / name
        file.write_bytes(b"old")
        os.utime(file, (now - age * 3600, now - age * 3600))
    return now


def test_ensure_multiples_fresh(tmp_path):
    def fetch(*args):
        pytest.fail("新檔不應下載")
    vi.ensure_multiples(tmp_path, now=old_files(tmp_path, 1), fetch=fetch)


def test_ensure_multiples_stale_fail(tmp_path):
    now = old_files(tmp_path, 7)
    calls = []
    def fetch(url, path):
        calls.append(url)
        path.write_bytes(b"partial")
        raise OSError("offline")
    vi.ensure_multiples(tmp_path, now=now, fetch=fetch)
    assert len(calls) == 2 and not list(tmp_path.glob("*.part"))
    assert all((tmp_path / name).read_bytes() == b"old" for name in (vi.MH_FILE, vi.REV_FILE))


def test_build_multiples_closes_union(tmp_path, capsys):
    months = pd.period_range("2015-01", "2020-09", freq="M")
    pd.DataFrame(dict(ticker="9999", date=months.to_timestamp("M"), close=1.0)).to_parquet(tmp_path / "monthly_raw_close.parquet")
    days = pd.date_range("2020-10-01", "2021-01-15", freq="B")
    pd.DataFrame(dict(ticker="9999.TW", date=days, close=2.0)).to_parquet(tmp_path / "prices_raw_close.parquet")
    result = _load_closes(pd.Timestamp("2021-01-15"), tmp_path)
    assert result.month.tolist() == pd.period_range("2015-01", "2020-12", freq="M").astype(str).tolist()
    assert not result.duplicated(["ticker", "month"]).any()
    assert result.loc[result.month == "2020-10", "close"].iloc[0] == 2.0
    (tmp_path / "monthly_raw_close.parquet").unlink()
    result = _load_closes(pd.Timestamp("2021-01-15"), tmp_path)
    assert result.month.min() == "2020-10"
    assert "⚠️ 沒有 monthly_raw_close，原始收盤只從 prices_raw_close 起" in capsys.readouterr().out


def test_help_valuation_exists():
    path = Path(__file__).resolve().parents[1] / "app/help_valuation.md"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 90
    assert all(word not in text for word in ("P20", "NC", "F4", "TTM", "YoY", ".py"))


def test_merge_mops_revenue_補缺月_官方優先_不看未來(tmp_path):
    rev = pd.DataFrame(dict(month=pd.to_datetime(["2026-08-01", "2026-09-01"]), revenue=[100.0, 110.0]))
    pd.DataFrame(dict(code=["2402", "2402", "1101"], period=["2026-09", "2026-10", "2026-10"],
                      revenue=[999.0, 120.0, 50.0],
                      first_seen_at=pd.to_datetime(["2026-10-05 01:00", "2026-11-03 04:30", "2026-11-02 00:55"]))
                 ).to_parquet(tmp_path / "2026-10.parquet")
    out = vi.merge_mops_revenue(rev, "2402", pd.Timestamp("2026-11-03"), tmp_path)
    assert out.revenue.tolist() == [100.0, 110.0, 120.0]       # 9 月以官方為準，10 月由 MOPS 補
    assert out.month.iloc[-1] == pd.Timestamp("2026-10-01")
    assert vi.merge_mops_revenue(rev, "2402", pd.Timestamp("2026-11-02"), tmp_path).equals(rev)  # 還沒看到
    assert vi.merge_mops_revenue(rev, "2402", pd.Timestamp("2026-11-03"), tmp_path / "無").equals(rev)
