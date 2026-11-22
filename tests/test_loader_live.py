"""load_quarterly(live=...)：線上產品提早公布的財報抓到就用；回測維持期末 +45 天。"""
import pandas as pd
import pytest

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


# ── 淨股本（股本扣預收股本） ─────────────────────────────────

def _cap_q(cap, adv=None, periods=None):
    n = len(cap)
    pe = periods or list(pd.date_range("2024-03-31", periods=n, freq="QE"))
    d = pd.DataFrame({"ticker": ["9999"] * n, "period_end": pe, "capital_stock": cap})
    if adv is not None:
        d["advance_capital"] = adv
    return d


def test_capital_net_subtracts_advance():
    q = _cap_q([148.25e8], [89.63e8])
    assert loader.capital_net(q).iloc[0] == pytest.approx(58.62e8)


def test_capital_net_missing_advance_keeps_capital():
    no_col = loader.capital_net(_cap_q([100.0]))
    assert no_col.iloc[0] == 100.0
    nan_adv = loader.capital_net(_cap_q([100.0], [float("nan")]))
    assert nan_adv.iloc[0] == 100.0
    assert loader.capital_net(pd.DataFrame({"ticker": ["9"], "period_end": [pd.Timestamp("2024-03-31")]})).isna().all()


def test_capital_net_bad_advance_ignored():
    assert loader.capital_net(_cap_q([100.0], [-5.0])).iloc[0] == 100.0
    assert loader.capital_net(_cap_q([100.0], [100.0])).iloc[0] == 100.0
    assert loader.capital_net(_cap_q([100.0], [150.0])).iloc[0] == 100.0


def test_capital_net_near_zero_past_only():
    got = loader.capital_net(_cap_q([100, 100, 100, 100, 5, 100])).tolist()
    assert got[:4] == [100.0] * 4
    assert pd.isna(got[4])
    assert got[5] == 100.0
    # 後面的值怎麼變都不影響第 5 季（只看過去）
    for last in (1, 1000):
        again = loader.capital_net(_cap_q([100, 100, 100, 100, 5, last])).tolist()
        assert pd.isna(again[4])
    # 前面不足 4 筆不判
    short = loader.capital_net(_cap_q([100, 100, 100, 5])).tolist()
    assert short[3] == 5.0


def test_merge_statements_adds_capital_net():
    pe = pd.Timestamp("2026-06-30")
    inc = pd.DataFrame({"ticker": ["1"], "period_end": [pe], "eps": [1.0]})
    bal = pd.DataFrame({"ticker": ["1"], "period_end": [pe], "capital_stock": [148.25e8],
                        "advance_capital": [89.63e8], "equity_parent": [1.0], "equity": [1.0]})
    q = loader.merge_statements(inc, bal, pd.DataFrame({"ticker": ["1"], "period_end": [pe]}))
    assert q["capital_net"].iloc[0] == pytest.approx(58.62e8)
