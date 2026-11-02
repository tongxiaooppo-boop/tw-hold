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
