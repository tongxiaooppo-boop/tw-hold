"""load_quarterly(live=...)：線上產品提早公布的財報抓到就用；回測維持期末 +45 天。"""
import pandas as pd

from reference import loader


def _fake_read(name):
    base = {"ticker": ["2337"], "period_end": [pd.Timestamp("2026-09-30")]}
    if name == "income":
        return pd.DataFrame({**base, "eps": [1.2], "equity_parent": [10.0]})
    if name == "balance":
        return pd.DataFrame({**base, "equity_parent": [100.0]})
    return pd.DataFrame(base)


def test_線上模式_提早公布的季_期末隔天就看得到(monkeypatch):
    monkeypatch.setattr(loader, "_read", _fake_read)
    q = loader.load_quarterly(live=True)
    assert q["disclosure_date"].iloc[0] == pd.Timestamp("2026-10-01")
    # 11/2（Q3 期限 11/14 之前）就能用
    assert (q["disclosure_date"] <= pd.Timestamp("2026-11-02")).all()


def test_預設回測模式_維持期末加45天(monkeypatch):
    monkeypatch.setattr(loader, "_read", _fake_read)
    q = loader.load_quarterly()
    assert q["disclosure_date"].iloc[0] == pd.Timestamp("2026-11-14")
    assert not (q["disclosure_date"] <= pd.Timestamp("2026-11-02")).any()


def test_回測模式_各季用法定期限_Q4是隔年3月31():
    pe = pd.Series(pd.to_datetime(["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]))
    got = loader.statement_deadline(pe)
    assert list(got) == list(pd.to_datetime(["2025-05-15", "2025-08-14", "2025-11-14", "2026-03-31"]))


def test_回測模式_年報2月中還看不到():
    pe = pd.Series([pd.Timestamp("2025-12-31")])
    assert not (loader.statement_deadline(pe) <= pd.Timestamp("2026-02-20")).any()
